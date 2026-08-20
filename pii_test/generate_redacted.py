"""
Generate redacted versions of CSV files where PII was detected.

Reads the tracking table to find files with pii_detected=True,
downloads them from S3, applies redaction, and uploads redacted copies.

Usage:
    python generate_redacted.py                 # redact all flagged files
    python generate_redacted.py --batch 1       # redact batch 1 only
    python generate_redacted.py --max-rows 250  # rows to process per CSV
"""

import argparse
import logging
import multiprocessing as mp
import os
import tempfile

import boto3
import duckdb
import pandas as pd
import torch
from botocore.exceptions import ClientError
from presidio_anonymizer import AnonymizerEngine

from pii_utils import (
    KEEP,
    LOT2_S3_ROOT_PREFIX,
    analyze_multi_language,
    build_analyzer,
    detect_language,
    regex_pii_matches,
    regex_matches_to_results,
    select_detection_columns,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def add_file_logging(log_path):
    """Attach a FileHandler to the root logger (LOT 2). Called before the
    worker Pool is created; on Linux's default 'fork' start method the
    workers inherit this handler along with the rest of process state."""
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(handler)


S3_BUCKET = "nic-ogdp-datasets"
S3_DATASET_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"
S3_TRACKING_PREFIX = "metadata/pii_detection"
S3_REDACTED_PREFIX = "redacted-datasets"

# LOT 2: per-ministry S3 folders, flagged files read from the local
# remain_raw_metadata table instead of the batch-wise tracking parquet.
DB_PATH = "transformation/metadata.db"
LOT2_LOCAL_TABLE = "remain_raw_metadata"
S3_LOT2_REDACTED_PREFIX = "redacted-datasets-lot2"
LOT2_LOG_PATH = "pii_test/pii_redact_lot2.log"


def get_s3_client():
    return boto3.client("s3")


def read_tracking_table(s3_client):
    """Download tracking parquet from S3."""
    response = s3_client.list_objects_v2(
        Bucket=S3_BUCKET, Prefix=S3_TRACKING_PREFIX + "/"
    )
    keys = [
        obj["Key"]
        for obj in response.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    ]
    if not keys:
        raise FileNotFoundError(
            f"No parquet files at s3://{S3_BUCKET}/{S3_TRACKING_PREFIX}/"
        )

    tracking_key = keys[0]
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        s3_client.download_file(S3_BUCKET, tracking_key, tmp_path)
        df = pd.read_parquet(tmp_path)
    finally:
        os.unlink(tmp_path)

    return df


def get_flagged_uuids(tracking_df, batch=None):
    """Get (uuid, batch) tuples where pii_detected is True."""
    mask = tracking_df["pii_detected"] == True
    if batch is not None:
        mask = mask & (tracking_df["batch"] == batch)
    flagged = tracking_df.loc[mask, ["uuid", "batch"]]
    return list(flagged.itertuples(index=False, name=None))


def get_flagged_uuids_lot2(ministry=None):
    """Get (uuid, ministry_folder) tuples where pii_detected is True, read
    directly from remain_raw_metadata (LOT 2 has no S3 tracking parquet)."""
    conn = duckdb.connect(DB_PATH)
    query = f"SELECT uuid, ministry_folder FROM {LOT2_LOCAL_TABLE} WHERE pii_detected = TRUE"
    params = []
    if ministry is not None:
        query += " AND ministry_folder = ?"
        params.append(ministry)
    df = conn.execute(query, params).fetch_df()
    conn.close()
    return list(df[["uuid", "ministry_folder"]].itertuples(index=False, name=None))


# Global worker state
_analyzer = None
_anonymizer = None
_max_rows = 250


def _init_worker(use_gpu, max_rows):
    global _analyzer, _anonymizer, _max_rows
    device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
    _analyzer, _ = build_analyzer(include_transformer_recognizer=True, device=device)
    _anonymizer = AnonymizerEngine()
    _max_rows = max_rows
    logging.info(f"Redaction worker {os.getpid()} initialized (device={device})")


def _redact_s3_csv(s3_client, uuid, s3_key, redacted_key):
    """Download one CSV from S3, redact PII in place, and upload the redacted
    copy to redacted_key. Shared by LOT 1's batch-wise redact_file and LOT 2's
    per-ministry redact_file_lot2."""
    global _analyzer, _anonymizer, _max_rows

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        s3_client.download_file(S3_BUCKET, s3_key, tmp_path)

        df = pd.read_csv(tmp_path)
        columns = select_detection_columns(df)
        if columns:
            rows_limit = min(_max_rows, len(df))

            for row_i in range(rows_limit):
                for col in columns:
                    text = str(df.iloc[row_i].get(col) or "").strip()
                    if not text:
                        continue

                    language = detect_language(text)
                    langs = [language] if language == "en" else [language, "en"]

                    try:
                        analyzer_results = analyze_multi_language(_analyzer, text, langs)
                    except Exception:
                        analyzer_results = []

                    filtered = [r for r in analyzer_results if r.entity_type in KEEP]
                    regex_hits = regex_pii_matches(text)
                    regex_results = regex_matches_to_results(regex_hits)

                    all_results = filtered + regex_results
                    if all_results:
                        # Dedupe by (type, start, end)
                        seen = set()
                        deduped = []
                        for r in all_results:
                            key = (r.entity_type, r.start, r.end)
                            if key not in seen:
                                seen.add(key)
                                deduped.append(r)

                        try:
                            anonymized = _anonymizer.anonymize(
                                text=text, analyzer_results=deduped
                            )
                            df.iat[row_i, df.columns.get_loc(col)] = anonymized.text
                        except Exception as e:
                            logging.warning(f"Redaction failed for {uuid} col={col}: {e}")

        # Upload redacted CSV
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as out_tmp:
            out_path = out_tmp.name
        try:
            df.to_csv(out_path, index=False)
            s3_client.upload_file(out_path, S3_BUCKET, redacted_key)
            logging.info(f"Redacted: s3://{S3_BUCKET}/{redacted_key}")
        finally:
            os.unlink(out_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def redact_file(args):
    """Download a CSV, redact PII, upload redacted version (LOT 1, batch-wise)."""
    uuid, batch = args
    s3_key = f"{S3_DATASET_PREFIX}/batch_{batch}/{uuid}.csv"
    redacted_key = f"{S3_REDACTED_PREFIX}/batch_{batch}/{uuid}.csv"
    result = {"uuid": uuid, "batch": batch, "redacted": False, "error": None}

    try:
        _redact_s3_csv(boto3.client("s3"), uuid, s3_key, redacted_key)
        result["redacted"] = True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchKey"):
            result["error"] = f"File not found: {s3_key}"
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


def redact_file_lot2(args):
    """Download a CSV from a ministry S3 folder, redact PII, upload redacted version (LOT 2)."""
    uuid, ministry = args
    s3_key = f"{LOT2_S3_ROOT_PREFIX}{ministry}/{uuid}.csv"
    redacted_key = f"{S3_LOT2_REDACTED_PREFIX}/{ministry}/{uuid}.csv"
    result = {"uuid": uuid, "ministry": ministry, "redacted": False, "error": None}

    try:
        _redact_s3_csv(boto3.client("s3"), uuid, s3_key, redacted_key)
        result["redacted"] = True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchKey"):
            result["error"] = f"File not found: {s3_key}"
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description="Generate redacted CSVs for PII-flagged files.")
    parser.add_argument("--batch", type=int, default=None, help="Process only this batch")
    parser.add_argument("--max-rows", type=int, default=250, help="Max rows to redact per CSV")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU")
    parser.add_argument("--lot2", action="store_true",
                        help="Run LOT 2: redact files flagged in remain_raw_metadata (per-ministry S3 "
                             "folders) instead of the batch-wise tracking parquet.")
    parser.add_argument("--ministry", type=str, default=None,
                        help="LOT 2 only: restrict to a single ministry folder (e.g. ministry-of-tourism)")
    args = parser.parse_args()

    if args.lot2:
        add_file_logging(LOT2_LOG_PATH)

    use_gpu = not args.no_gpu and torch.cuda.is_available()
    num_workers = mp.cpu_count()
    logging.info(f"Workers: {num_workers} | GPU: {use_gpu}")

    if args.lot2:
        flagged = get_flagged_uuids_lot2(ministry=args.ministry)
        redact_fn = redact_file_lot2
    else:
        s3_client = get_s3_client()
        tracking_df = read_tracking_table(s3_client)
        flagged = get_flagged_uuids(tracking_df, batch=args.batch)
        redact_fn = redact_file

    if not flagged:
        logging.info("No PII-flagged files to redact.")
        return

    logging.info(f"Redacting {len(flagged)} files...")

    pool = mp.Pool(
        processes=num_workers,
        initializer=_init_worker,
        initargs=(use_gpu, args.max_rows),
    )
    results = pool.map(redact_fn, flagged)
    pool.close()
    pool.join()

    success = sum(1 for r in results if r["redacted"])
    errors = sum(1 for r in results if r["error"])
    for r in results:
        if r["error"]:
            logging.warning(f"Error on {r['uuid']}: {r['error']}")

    logging.info("=" * 50)
    logging.info(f"Done. Redacted: {success} | Errors: {errors}")
    logging.info("=" * 50)


if __name__ == "__main__":
    main()
