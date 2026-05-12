import argparse
import logging
from datetime import datetime, timezone
import multiprocessing as mp
import os
import tempfile
from pii_filters import filter_detections
import boto3
import duckdb
import pandas as pd
import torch
from botocore.exceptions import ClientError
import re
from pii_utils import (
    KEEP,
    batch_analyze_cells,
    build_analyzer,
    detect_language,
    is_phone_entity,
    keep_result,
    regex_pii_matches,
    select_detection_columns,
    RecognizerResult
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler("pii_test/pii_s3.log")],
)
logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)

S3_BUCKET = "nic-ogdp-datasets"
S3_DATASET_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"
S3_RESULTS_PREFIX = "pii-results"
S3_METADATA_KEY = "metadata/CHANGEME/dublin_core_metadata.parquet"  # TODO: set correct path

DB_PATH = "transformation/metadata.db"

# Add to pii_utils.py
FIELD_NAME_PATTERNS = [
    re.compile(r"(?i)name\s+of\s+farmer\s*[\n:]\s*([A-Z][A-Z\s]{2,40})", re.MULTILINE),
    re.compile(r"(?i)farmer\s+name\s*[\n:]\s*([A-Z][A-Z\s]{2,40})", re.MULTILINE),
    re.compile(r"(?i)father[/\w]*\s+name\s*[\n:]\s*([A-Z][A-Z\s]{2,40})", re.MULTILINE),
    re.compile(r"(?i)guardian\s+name\s*[\n:]\s*([A-Z][A-Z\s]{2,40})", re.MULTILINE),
]

def extract_structured_names(text):
    """Extract names from known KCC/PM-Kisan field label patterns."""
    results = []
    for pat in FIELD_NAME_PATTERNS:
        for m in pat.finditer(text or ""):
            name = m.group(1).strip()
            if len(name) >= 3:
                results.append(RecognizerResult(
                    entity_type="PERSON",
                    start=m.start(1),
                    end=m.end(1),
                    score=0.95,
                    analysis_explanation=None,
                ))
    return results

def get_s3_client():
    return boto3.client("s3")


def read_dublin_core_metadata():
    """Read dublin_core_metadata from DuckDB."""
    try:
        conn = duckdb.connect(DB_PATH)
        df = conn.execute('SELECT "Identifier[UUID]" as uuid, batch FROM dublin_core_metadata').fetch_df()
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

        conn.execute("ALTER TABLE dublin_core_metadata ADD COLUMN IF NOT EXISTS pii_test_timestamp TIMESTAMP")

        # Update flags
        for _, row in df.iterrows():
            uuid = row['uuid']
            pii_tested = row['pii_tested']
            pii_detected = row['pii_detected']
            pii_test_timestamp = row['pii_test_timestamp']  
            conn.execute(
                f'UPDATE dublin_core_metadata SET pii_tested={pii_tested}, pii_detected={pii_detected}, pii_test_timestamp=\'{pii_test_timestamp}\' WHERE "Identifier[UUID]"=\'{uuid}\'')

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


def upload_dublin_core_metadata(s3_client):
    """Export dublin_core_metadata from DuckDB and upload to S3 as parquet."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        conn = duckdb.connect(DB_PATH)
        conn.execute(f"COPY (SELECT * FROM dublin_core_metadata) TO '{tmp_path}' (FORMAT PARQUET)")
        conn.close()
        s3_client.upload_file(tmp_path, S3_BUCKET, S3_METADATA_KEY)
        logging.info(f"Uploaded dublin_core_metadata to s3://{S3_BUCKET}/{S3_METADATA_KEY}")
    except Exception as e:
        logging.error(f"Failed to upload dublin_core_metadata: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Global analyzer, initialized once per worker process
_analyzer = None
_indic_recognizer = None
_max_rows = 250


def _init_worker(use_gpu, max_rows):
    global _analyzer, _indic_recognizer, _max_rows
    device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
    _analyzer, _indic_recognizer = build_analyzer(
        include_transformer_recognizer=True, device=device
    )
    _max_rows = max_rows
    logging.info(f"Worker {os.getpid()} initialized (device={device})")


def scan_local_file(path):
    """Process a local CSV file. Returns a result dict."""
    global _analyzer, _indic_recognizer, _max_rows

    uuid = os.path.splitext(os.path.basename(path))[0]
    result = {
        "uuid": uuid,
        "batch": None,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "error": None,
    }

    try:
        df = pd.read_csv(path)
        columns = select_detection_columns(df)
        if not columns:
            return result

        rows_limit = min(_max_rows, len(df))
        pii_types_found = set()
        detections = []

        cell_info = []
        cell_text = {}
        for row_i in range(rows_limit):
            row = df.iloc[row_i]
            for col in columns:
                text = str(row.get(col) or "").strip()
                if not text:
                    continue
                cell_info.append((row_i, col, text, detect_language(text)))
                cell_text[(row_i, col)] = text

        try:
            cache = batch_analyze_cells(cell_info, _analyzer, _indic_recognizer)
        except Exception as exc:
            logging.warning(f"Batch analysis failed for {uuid}: {exc}")
            cache = {}

        # Merge structured field extractions into cache per cell
        for row_i, col, text in [(r, c, t) for r, c, t, _ in cell_info]:
            structured = extract_structured_names(text)
            if structured:
                cache.setdefault((row_i, col), []).extend(structured)

        for (row_i, col), analyzer_results in cache.items():
            text = cell_text[(row_i, col)]
            for r in analyzer_results:
                if not keep_result(r, text):
                    continue
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

        for (row_i, col), text in cell_text.items():
            for label, snippet, _, _ in regex_pii_matches(text):
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

        detections = filter_detections(detections)
        result["rows_scanned"] = rows_limit
        result["pii_found"] = len(detections) > 0
        result["pii_types"] = list(pii_types_found)
        result["entity_count"] = len(detections)
        result["detections"] = detections
    except Exception as e:
        result["error"] = str(e)

    return result


def scan_file(args):
    """Process one CSV file from S3. Returns a result dict."""
    uuid, batch = args
    global _analyzer, _indic_recognizer, _max_rows

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

        # Single-pass collection of all non-empty cells with their language.
        cell_info = []
        cell_text = {}
        for row_i in range(rows_limit):
            row = df.iloc[row_i]
            for col in columns:
                text = str(row.get(col) or "").strip()
                if not text:
                    continue
                cell_info.append((row_i, col, text, detect_language(text)))
                cell_text[(row_i, col)] = text

        # Batched IndicNER + spaCy/Presidio across all cells in this file.
        try:
            cache = batch_analyze_cells(cell_info, _analyzer, _indic_recognizer)
        except Exception as exc:
            logging.warning(f"Batch analysis failed for {uuid}: {exc}")
            cache = {}

        for (row_i, col), analyzer_results in cache.items():
            text = cell_text[(row_i, col)]
            for r in analyzer_results:
                if not keep_result(r, text):
                    continue
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

        # Regex pass remains per-cell (it's negligible cost and not GPU-bound).
        for (row_i, col), text in cell_text.items():
            for label, snippet, _, _ in regex_pii_matches(text):
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

        detections = filter_detections(detections)
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
    global _analyzer, _indic_recognizer, _max_rows
    parser = argparse.ArgumentParser(description="Run PII detection on S3 datasets.")
    parser.add_argument("--batch", type=int, default=None, help="Process only this batch")
    parser.add_argument("--iterate", type=int, nargs="?", const=-1, default=None, metavar="N",
                        help="After --batch finishes, continue through subsequent batches. Optionally limit to N batches total (including the starting batch).")
    parser.add_argument("--max-rows", type=int, default=250, help="Max rows to scan per CSV")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU, use CPU only")
    parser.add_argument("--worker-count", type=int, default= 1, help="Number of workers for multiprocessing (optional, default: sequential)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of datasets to process (optional)")
    parser.add_argument("--path", type=str, default=None, help="Run PII detection on a local CSV file (skips S3/DuckDB)")
    args = parser.parse_args()

    use_gpu = not args.no_gpu and torch.cuda.is_available()

    if args.path:
        device = "cuda" if use_gpu else "cpu"

        if os.path.isdir(args.path):
            csv_files = []
            for dirpath, _, filenames in os.walk(args.path):
                for fname in filenames:
                    if fname.lower().endswith(".csv"):
                        csv_files.append(os.path.join(dirpath, fname))

            if not csv_files:
                logging.info(f"No CSV files found under {args.path}")
                return

            if args.limit is not None and args.limit > 0:
                csv_files = csv_files[:args.limit]

            logging.info(f"Found {len(csv_files)} CSV file(s) under {args.path}")

            use_multiprocessing = args.worker_count > 1
            if use_multiprocessing:
                if __name__ == '__main__':
                    mp.set_start_method('spawn', force=True)
                pool = mp.Pool(
                    processes=args.worker_count,
                    initializer=_init_worker,
                    initargs=(use_gpu, args.max_rows),
                )
                results = pool.map(scan_local_file, csv_files)
                pool.close()
                pool.join()
            else:
                _max_rows = args.max_rows
                _analyzer, _indic_recognizer = build_analyzer(
                    include_transformer_recognizer=True, device=device
                )
                logging.info(f"Initialized analyzer (device={device}) | Max rows: {args.max_rows}")
                results = [scan_local_file(f) for f in csv_files]

            pii_count = 0
            error_count = 0
            for path, result in zip(csv_files, results):
                if result["error"]:
                    logging.warning(f"Error on {path}: {result['error']}")
                    error_count += 1
                    continue

                logging.info(
                    f"File: {path} | Rows: {result['rows_scanned']} | "
                    f"PII found: {result['pii_found']} | Types: {result['pii_types']} | "
                    f"Entities: {result['entity_count']}"
                )
                if result["pii_found"]:
                    pii_count += 1

                if result["detections"]:
                    det_df = pd.DataFrame(result["detections"])
                    out_path = os.path.splitext(path)[0] + "_pii_detections.csv"
                    det_df.to_csv(out_path, index=False)
                    logging.info(f"Saved {len(result['detections'])} detections to {out_path}")

            processed = len(results) - error_count
            logging.info("=" * 50)
            logging.info(f"Done. Processed: {processed} | PII found: {pii_count} | Errors: {error_count}")
            logging.info("=" * 50)
        else:
            _max_rows = args.max_rows
            _analyzer, _indic_recognizer = build_analyzer(
                include_transformer_recognizer=True, device=device
            )
            logging.info(f"Initialized analyzer (device={device}) | Max rows: {args.max_rows}")
            logging.info(f"Scanning local file: {args.path}")

            result = scan_local_file(args.path)

            if result["error"]:
                logging.error(f"Error: {result['error']}")
                return

            logging.info("=" * 50)
            logging.info(f"File: {args.path}")
            logging.info(f"Rows scanned: {result['rows_scanned']}")
            logging.info(f"PII found: {result['pii_found']}")
            logging.info(f"PII types: {result['pii_types']}")
            logging.info(f"Entity count: {result['entity_count']}")
            logging.info("=" * 50)

            if result["detections"]:
                det_df = pd.DataFrame(result["detections"])
                out_path = os.path.splitext(args.path)[0] + "_pii_detections.csv"
                det_df.to_csv(out_path, index=False)
                logging.info(f"Saved {len(result['detections'])} detections to {out_path}")
        return

    use_multiprocessing = args.worker_count is not None and args.worker_count > 0

    if use_multiprocessing:
        logging.info(f"Workers: {args.worker_count} | GPU: {use_gpu} | Max rows: {args.max_rows}")
    else:
        logging.info(f"Sequential processing (no multiprocessing) | GPU: {use_gpu} | Max rows: {args.max_rows}")

    s3_client = get_s3_client()

    # Initialize analyzer once (reused across batches when iterating)
    if not use_multiprocessing:
        device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        _analyzer, _indic_recognizer = build_analyzer(
            include_transformer_recognizer=True, device=device
        )
        _max_rows = args.max_rows
        logging.info(f"Initialized analyzer (device={device})")

    dublin_df = read_dublin_core_metadata()
    logging.info(f"Total records: {len(dublin_df)}")

    # Determine which batches to run
    all_batch_nums = sorted(dublin_df["batch"].dropna().unique().astype(int).tolist())
    if args.batch is not None and args.iterate is not None:
        if args.batch not in all_batch_nums:
            logging.error(f"Batch {args.batch} not found in data. Available: {all_batch_nums}")
            return
        batches_to_run = all_batch_nums[all_batch_nums.index(args.batch):]
        if args.iterate > 0:
            batches_to_run = batches_to_run[:args.iterate]
    else:
        batches_to_run = [args.batch]

    for batch_num in batches_to_run:
        logging.info(f"{'=' * 50}")
        logging.info(f"Starting batch {batch_num}")

        pending = get_pending_uuids(dublin_df, batch=batch_num)
        if not pending:
            logging.info(f"No pending files for batch {batch_num}, skipping.")
            continue

        if args.limit is not None and args.limit > 0:
            pending = pending[:args.limit]
            logging.info(f"Limited to {args.limit} datasets")

        logging.info(f"Processing {len(pending)} files...")

        if use_multiprocessing:
            if __name__ == '__main__':
                mp.set_start_method('spawn', force=True)
            pool = mp.Pool(
                processes=args.worker_count,
                initializer=_init_worker,
                initargs=(use_gpu, args.max_rows),
            )
            results = pool.map(scan_file, pending)
            pool.close()
            pool.join()
        else:
            results = [scan_file(item) for item in pending]

        pii_count = 0
        error_count = 0
        all_detections = {}
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
                "pii_test_timestamp": datetime.now(timezone.utc).isoformat(),
            })

            if pii_found:
                pii_count += 1
                logging.info(
                    f"PII found: {uuid} | types: {result['pii_types']} | "
                    f"entities: {result['entity_count']}"
                )

            if result["detections"]:
                all_detections.setdefault(batch, []).extend(result["detections"])

        if updates_for_db:
            updates_df = pd.DataFrame(updates_for_db)
            update_dublin_core_metadata(updates_df)

        for batch, detections in all_detections.items():
            save_detection_results(s3_client, detections, batch)

        upload_dublin_core_metadata(s3_client)

        processed = len(results) - error_count
        logging.info("=" * 50)
        logging.info(f"Batch {batch_num} done. Processed: {processed} | PII found: {pii_count} | Errors: {error_count}")
        logging.info("=" * 50)


if __name__ == "__main__":
    main()
