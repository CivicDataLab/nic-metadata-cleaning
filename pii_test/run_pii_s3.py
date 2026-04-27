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

from pii_utils import (
    KEEP,
    analyze_multi_language,
    build_analyzer,
    detect_language,
    is_phone_entity,
    regex_pii_matches,
    select_detection_columns,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

S3_BUCKET = "nic-ogdp-datasets"
S3_DATASET_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"
S3_RESULTS_PREFIX = "pii-results"

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"


# --- S3 helpers ---

def get_s3_client():
    return boto3.client("s3")


def read_dublin_core_metadata():
    """Read dublin_core_metadata from DuckDB."""
    try:
        conn = duckdb.connect(DB_PATH)
        df = conn.execute("SELECT uuid, batch FROM dublin_core_metadata").fetch_df()
        conn.close()
        logging.info(f"Read {len(df)} records from dublin_core_metadata")
        return df
    except Exception as e:
        logging.error(f"Failed to read dublin_core_metadata: {e}")
        raise


def update_dublin_core_metadata(df):
    """Update dublin_core_metadata table with pii_tested and pii_detected flags."""
    try:
        conn = duckdb.connect(DB_PATH)

        # Ensure columns exist
        conn.execute("ALTER TABLE dublin_core_metadata ADD COLUMN IF NOT EXISTS pii_tested BOOLEAN DEFAULT FALSE")
        conn.execute("ALTER TABLE dublin_core_metadata ADD COLUMN IF NOT EXISTS pii_detected BOOLEAN DEFAULT FALSE")

        # Update flags
        for _, row in df.iterrows():
            uuid = row['uuid']
            pii_tested = row['pii_tested']
            pii_detected = row['pii_detected']
            conn.execute(
                f"UPDATE dublin_core_metadata SET pii_tested={pii_tested}, pii_detected={pii_detected} WHERE uuid='{uuid}'"
            )

        conn.close()
        logging.info(f"Updated {len(df)} records in dublin_core_metadata")
    except Exception as e:
        logging.error(f"Failed to update dublin_core_metadata: {e}")
        raise


def get_pending_uuids(dublin_df, batch=None):
    """Get list of (uuid, batch) tuples from dublin_core_metadata."""
    if batch is not None:
        pending = dublin_df[dublin_df["batch"] == batch]
    else:
        pending = dublin_df

    return list(pending[["uuid", "batch"]].itertuples(index=False, name=None))


def save_detection_results(s3_client, detections, batch):
    """Save detailed detection records as parquet to S3."""
    if not detections:
        return

    det_df = pd.DataFrame(detections)
    s3_key = f"{S3_RESULTS_PREFIX}/batch_{batch}/pii_detections.parquet"

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        det_df.to_parquet(tmp_path, index=False)
        s3_client.upload_file(tmp_path, S3_BUCKET, s3_key)
        logging.info(f"Saved {len(detections)} detections to s3://{S3_BUCKET}/{s3_key}")
    finally:
        os.unlink(tmp_path)



# Global analyzer, initialized once per worker process
_analyzer = None
_max_rows = 250


def _init_worker(use_gpu, max_rows):
    global _analyzer, _max_rows
    device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
    _analyzer = build_analyzer(include_transformer_recognizer=True, device=device)
    _max_rows = max_rows
    logging.info(f"Worker {os.getpid()} initialized (device={device})")


def scan_file(args):
    """Process one CSV file from S3. Returns a result dict."""
    uuid, batch = args
    global _analyzer, _max_rows

    s3_key = f"{S3_DATASET_PREFIX}/batch_{batch}/{uuid}.csv"
    result = {
        "uuid": uuid,
        "batch": batch,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "error": None,
    }

    tmp_path = None
    try:
        # Download CSV
        s3 = boto3.client("s3")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        s3.download_file(S3_BUCKET, s3_key, tmp_path)

        df = pd.read_csv(tmp_path)
        columns = select_detection_columns(df)
        if not columns:
            return result

        rows_limit = min(_max_rows, len(df))
        pii_types_found = set()
        detections = []

        for row_i in range(rows_limit):
            row = df.iloc[row_i]
            for col in columns:
                text = str(row.get(col) or "").strip()
                if not text:
                    continue

                language = detect_language(text)
                langs = [language] if language == "en" else [language, "en"]

                # Presidio + IndicNER analysis
                try:
                    analyzer_results = analyze_multi_language(_analyzer, text, langs)
                except Exception:
                    analyzer_results = []

                filtered = [r for r in analyzer_results if r.entity_type in KEEP]

                # Regex-based detection
                regex_hits = regex_pii_matches(text)

                # Check what was found
                person_detected = any(r.entity_type == "PERSON" for r in filtered)
                phone_detected = (
                    any(is_phone_entity(r.entity_type) for r in filtered)
                    or any(label == "PHONE_NUMBER" for label, *_ in regex_hits)
                )
                aadhaar_detected = any(label == "AADHAAR_NUMBER" for label, *_ in regex_hits)
                pan_detected = any(label == "PAN_NUMBER" for label, *_ in regex_hits)
                regid_detected = any(label == "FARMER_REGISTRATION_ID" for label, *_ in regex_hits)
                email_detected = any(r.entity_type == "EMAIL_ADDRESS" for r in filtered)

                # Record detections
                for r in filtered:
                    snippet = text[r.start:r.end]
                    pii_types_found.add(r.entity_type)
                    detections.append({
                        "uuid": uuid,
                        "column": col,
                        "row_index": row_i,
                        "entity_type": r.entity_type,
                        "entity_text": snippet,
                        "score": r.score,
                        "source": "presidio",
                    })

                for label, snippet, start, end in regex_hits:
                    pii_types_found.add(label)
                    detections.append({
                        "uuid": uuid,
                        "column": col,
                        "row_index": row_i,
                        "entity_type": label,
                        "entity_text": snippet,
                        "score": 1.0,
                        "source": "regex",
                    })

        result["rows_scanned"] = rows_limit
        result["pii_found"] = len(detections) > 0
        result["pii_types"] = list(pii_types_found)
        result["entity_count"] = len(detections)
        result["detections"] = detections

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404" or error_code == "NoSuchKey":
            result["error"] = f"File not found: {s3_key}"
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return result


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Run PII detection on S3 datasets.")
    parser.add_argument("--batch", type=int, default=None, help="Process only this batch")
    parser.add_argument("--max-rows", type=int, default=250, help="Max rows to scan per CSV")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU, use CPU only")
    args = parser.parse_args()

    use_gpu = not args.no_gpu and torch.cuda.is_available()
    num_workers = mp.cpu_count()
    logging.info(f"Workers: {num_workers} | GPU: {use_gpu} | Max rows: {args.max_rows}")

    s3_client = get_s3_client()

    # Read dublin_core_metadata from DuckDB
    dublin_df = read_dublin_core_metadata()
    logging.info(f"Total records: {len(dublin_df)}")

    # Get pending files
    pending = get_pending_uuids(dublin_df, batch=args.batch)
    if not pending:
        logging.info("No pending files to process.")
        return

    logging.info(f"Processing {len(pending)} files...")

    # Run with multiprocessing
    pool = mp.Pool(
        processes=num_workers,
        initializer=_init_worker,
        initargs=(use_gpu, args.max_rows),
    )
    results = pool.map(scan_file, pending)
    pool.close()
    pool.join()

    # Collect results and detections
    pii_count = 0
    error_count = 0
    all_detections = {}  # batch -> list of detection dicts
    updates_for_db = []

    for result in results:
        uuid = result["uuid"]
        batch = result["batch"]

        if result["error"]:
            logging.warning(f"Error on {uuid}: {result['error']}")
            error_count += 1
            continue

        pii_found = result["pii_found"]
        updates_for_db.append({
            "uuid": uuid,
            "pii_tested": True,
            "pii_detected": pii_found,
        })

        if pii_found:
            pii_count += 1
            logging.info(
                f"PII found: {uuid} | types: {result['pii_types']} | "
                f"entities: {result['entity_count']}"
            )

        if result["detections"]:
            all_detections.setdefault(batch, []).extend(result["detections"])

    # Update dublin_core_metadata in DuckDB
    if updates_for_db:
        updates_df = pd.DataFrame(updates_for_db)
        update_dublin_core_metadata(updates_df)

    # Save detailed detections per batch to S3
    for batch, detections in all_detections.items():
        save_detection_results(s3_client, detections, batch)

    # Summary
    processed = len(results) - error_count
    logging.info("=" * 50)
    logging.info(f"Done. Processed: {processed} | PII found: {pii_count} | Errors: {error_count}")
    logging.info("=" * 50)


if __name__ == "__main__":
    main()
