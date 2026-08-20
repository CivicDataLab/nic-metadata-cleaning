import argparse
import logging
from datetime import datetime, timezone
import multiprocessing as mp
import os
import tempfile
from pii_filters import evaluate_dataset_flag, filter_detections
import boto3
import duckdb
import pandas as pd
import torch
from botocore.exceptions import ClientError
import re
from pii_utils import (
    KEEP,
    LOT2_S3_ROOT_PREFIX,
    batch_analyze_cells,
    build_analyzer,
    column_cardinality_ratio,
    detect_language,
    is_phone_entity,
    keep_result,
    list_ministry_csv_keys,
    list_ministry_folders,
    regex_pii_matches,
    select_detection_columns,
    RecognizerResult
)

LOT1_LOG_PATH = "pii_test/pii_s3.log"
LOT2_LOG_PATH = "pii_test/pii_s3_lot2.log"


def configure_logging(log_path):
    """(Re)point the root logger at log_path. Called at import (LOT 1 default)
    and again in main()/_init_worker() when --lot2 is passed, since spawned
    worker processes re-run this module's top level and need the same path."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_path)],
        force=True,
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)


configure_logging(LOT1_LOG_PATH)

S3_BUCKET = "nic-ogdp-datasets"
S3_DATASET_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"
S3_RESULTS_PREFIX = "pii-results"
S3_METADATA_KEY = "/metadata/ducklake/main/remaining-raw-datasets/"  # TODO: set correct path

# LOT 2: per-ministry S3 folders (see pii_utils.list_ministry_folders), tracked
# in the local remain_raw_metadata table instead of dublin_core_metadata/batch.
S3_LOT2_RESULTS_PREFIX = "pii-results-lot2"
LOT2_LOCAL_TABLE = "remain_raw_metadata"
LOT2_DETECTIONS_TABLE = "pii_detections_lot2"
LOT2_METADATA_SNAPSHOT_KEY = "pii-results-lot2/remain_raw_metadata_snapshot.parquet"
# One consolidated detections file covering every ministry, rebuilt from the
# pii_detections_lot2 table after each ministry finishes. Per-ministry slices
# come from export_detections_lot2.py rather than separate stored files.
LOT2_DETECTIONS_BASE_KEY = "pii-results-lot2/pii_detections"

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

def log_column_selection(uuid, columns, skipped):
    """Record which columns were scanned and why the rest were not.

    A column that is never scanned cannot produce a detection, so silent
    skipping looks identical to "scanned and clean" in the output. The
    per-column detail goes to DEBUG (it would be tens of lines per dataset at
    90k datasets); the INFO line keeps the shape of the decision visible.
    """
    logging.info(
        "%s: scanning %d/%d column(s)%s",
        uuid, len(columns), len(columns) + len(skipped),
        f" -> {columns}" if columns else " (none)",
    )
    for col, reason in skipped:
        logging.debug("%s: skipped column %r (%s)", uuid, col, reason)


def get_s3_client():
    return boto3.client("s3")


def read_csv_robust(path):
    """Read a CSV, falling back for non-UTF-8 exports (0xa0 etc. are common
    in Windows-1252 files on data.gov.in)."""
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", encoding_errors="replace")


def read_dublin_core_metadata():
    """Read dublin_core_metadata from DuckDB."""
    try:
        conn = duckdb.connect(DB_PATH)
        df = conn.execute('SELECT "Identifier[UUID]" as uuid, batch, pii_tested FROM dublin_core_metadata').fetch_df()
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
            conn.execute(
                'UPDATE dublin_core_metadata SET pii_tested=?, pii_detected=?, pii_test_timestamp=? WHERE "Identifier[UUID]"=?',
                [row['pii_tested'], row['pii_detected'], row['pii_test_timestamp'], row['uuid']])

        conn.close()
        logging.info(f"Updated {len(df)} records in dublin_core_metadata")
    except Exception as e:
        logging.error(f"Failed to update dublin_core_metadata: {e}")
        raise


def get_pending_uuids(dublin_df, batch=None):
    """Get list of (uuid, batch) tuples not yet tested for PII."""
    if batch is not None:
        pending = dublin_df[dublin_df["batch"] == batch]
    else:
        pending = dublin_df

    pending = pending[pending["pii_tested"] != True]

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


def read_remain_raw_metadata():
    """Read uuid + pii_tested from remain_raw_metadata, adding LOT 2 tracking
    columns (pii_tested/pii_detected/pii_test_timestamp/ministry_folder) if
    this is the first LOT 2 run against this table."""
    try:
        conn = duckdb.connect(DB_PATH)
        conn.execute(f"ALTER TABLE {LOT2_LOCAL_TABLE} ADD COLUMN IF NOT EXISTS pii_tested BOOLEAN")
        conn.execute(f"ALTER TABLE {LOT2_LOCAL_TABLE} ADD COLUMN IF NOT EXISTS pii_detected BOOLEAN")
        conn.execute(f"ALTER TABLE {LOT2_LOCAL_TABLE} ADD COLUMN IF NOT EXISTS pii_test_timestamp TIMESTAMP")
        conn.execute(f"ALTER TABLE {LOT2_LOCAL_TABLE} ADD COLUMN IF NOT EXISTS ministry_folder VARCHAR")
        # Why the dataset was (or was not) flagged -- see evaluate_dataset_flag.
        conn.execute(f"ALTER TABLE {LOT2_LOCAL_TABLE} ADD COLUMN IF NOT EXISTS pii_flag_reason VARCHAR")
        df = conn.execute(f'SELECT uuid, pii_tested FROM {LOT2_LOCAL_TABLE}').fetch_df()
        conn.close()
        logging.info(f"Read {len(df)} records from {LOT2_LOCAL_TABLE}")
        return df
    except Exception as e:
        logging.error(f"Failed to read {LOT2_LOCAL_TABLE}: {e}")
        raise


def update_remain_raw_metadata(df):
    """Update remain_raw_metadata with pii_tested/pii_detected/ministry_folder flags (LOT 2)."""
    try:
        conn = duckdb.connect(DB_PATH)
        for _, row in df.iterrows():
            conn.execute(
                f'UPDATE {LOT2_LOCAL_TABLE} SET pii_tested=?, pii_detected=?, '
                f'pii_test_timestamp=?, ministry_folder=?, pii_flag_reason=? WHERE uuid=?',
                [row["pii_tested"], row["pii_detected"], row["pii_test_timestamp"],
                 row["ministry_folder"], row["pii_flag_reason"], row["uuid"]])
        conn.close()
        logging.info(f"Updated {len(df)} records in {LOT2_LOCAL_TABLE}")
    except Exception as e:
        logging.error(f"Failed to update {LOT2_LOCAL_TABLE}: {e}")
        raise


def save_lot2_detection_results(s3_client, detections, ministry):
    """Append LOT 2 detections to the pii_detections_lot2 table, then refresh
    the single consolidated CSV + parquet on S3.

    The table is the source of truth; the S3 files are a full export of it, so
    they stay consistent even if a run is interrupted and resumed. Per-ministry
    and per-uuid slices are produced on demand by export_detections_lot2.py.
    """
    if not detections:
        return

    det_df = pd.DataFrame(detections)
    det_df.insert(1, "ministry", ministry)

    conn = duckdb.connect(DB_PATH)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {LOT2_DETECTIONS_TABLE} (
            uuid VARCHAR, ministry VARCHAR, "column" VARCHAR, row_index INTEGER,
            entity_type VARCHAR, entity_text VARCHAR, score DOUBLE, source VARCHAR
        )
    """)
    conn.register("det_df", det_df)
    conn.execute(f"""
        INSERT INTO {LOT2_DETECTIONS_TABLE}
        SELECT uuid, ministry, "column", row_index, entity_type, entity_text, score, source
        FROM det_df
    """)
    logging.info(f"Inserted {len(detections)} detections into {LOT2_DETECTIONS_TABLE} ({ministry})")

    # One CSV per ministry, for looking at a single ministry's detections
    # without pulling the full consolidated file.
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        conn.execute(
            f"COPY (SELECT * FROM {LOT2_DETECTIONS_TABLE} WHERE ministry = ? ORDER BY uuid) "
            f"TO '{tmp_path}' (FORMAT CSV, HEADER)",
            [ministry],
        )
        ministry_key = f"{S3_LOT2_RESULTS_PREFIX}/{ministry}/pii_detections.csv"
        s3_client.upload_file(tmp_path, S3_BUCKET, ministry_key)
        logging.info(f"Saved {ministry} detections to s3://{S3_BUCKET}/{ministry_key}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Rebuild the consolidated export from the full table. DuckDB's COPY
    # streams this straight to disk, which matters once the table is >1M rows.
    total = conn.execute(f"SELECT COUNT(*) FROM {LOT2_DETECTIONS_TABLE}").fetchone()[0]
    for suffix, copy_opts in ((".csv", "(FORMAT CSV, HEADER)"), (".parquet", "(FORMAT PARQUET)")):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            conn.execute(
                f"COPY (SELECT * FROM {LOT2_DETECTIONS_TABLE} ORDER BY ministry, uuid) "
                f"TO '{tmp_path}' {copy_opts}"
            )
            s3_client.upload_file(tmp_path, S3_BUCKET, f"{LOT2_DETECTIONS_BASE_KEY}{suffix}")
            logging.info(
                f"Refreshed consolidated export ({total} rows) at "
                f"s3://{S3_BUCKET}/{LOT2_DETECTIONS_BASE_KEY}{suffix}"
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    conn.close()


def upload_remain_raw_metadata_snapshot(s3_client):
    """Export remain_raw_metadata from DuckDB and upload a snapshot to S3 (LOT 2)."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        conn = duckdb.connect(DB_PATH)
        conn.execute(f"COPY (SELECT * FROM {LOT2_LOCAL_TABLE}) TO '{tmp_path}' (FORMAT PARQUET)")
        conn.close()
        s3_client.upload_file(tmp_path, S3_BUCKET, LOT2_METADATA_SNAPSHOT_KEY)
        logging.info(f"Uploaded {LOT2_LOCAL_TABLE} snapshot to s3://{S3_BUCKET}/{LOT2_METADATA_SNAPSHOT_KEY}")
    except Exception as e:
        logging.error(f"Failed to upload {LOT2_LOCAL_TABLE} snapshot: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Global analyzer, initialized once per worker process
_analyzer = None
_gpu_ner = None
_max_rows = 9999
_ner_batch_size = 64


def _init_worker(use_gpu, max_rows, ner_batch_size, log_path=LOT1_LOG_PATH):
    global _analyzer, _gpu_ner, _max_rows, _ner_batch_size
    configure_logging(log_path)
    device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
    _analyzer, _gpu_ner = build_analyzer(
        include_transformer_recognizer=True, device=device
    )
    _max_rows = max_rows
    _ner_batch_size = ner_batch_size
    logging.info(f"Worker {os.getpid()} initialized (device={device})")


def scan_local_file(path):
    """Process a local CSV file. Returns a result dict."""
    global _analyzer, _gpu_ner, _max_rows, _ner_batch_size

    uuid = os.path.splitext(os.path.basename(path))[0]
    result = {
        "uuid": uuid,
        "batch": None,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "degraded": False,
        "pii_flag_reason": None,
        "columns_scanned": [],
        "columns_skipped": [],
        "error": None,
    }

    try:
        df = read_csv_robust(path)
        columns, skipped_columns = select_detection_columns(df, return_skipped=True)
        log_column_selection(uuid, columns, skipped_columns)
        result["columns_scanned"] = columns
        result["columns_skipped"] = skipped_columns
        if not columns:
            return result

        rows_limit = min(_max_rows, len(df))
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
            cache = batch_analyze_cells(
                cell_info, _analyzer, _gpu_ner, ner_batch_size=_ner_batch_size
            )
        except Exception as exc:
            logging.error(f"Batch analysis failed for {uuid}: {exc}")
            cache = {}
            result["degraded"] = True

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
        cardinality = {col: column_cardinality_ratio(df[col], rows_limit) for col in columns}
        pii_found, flag_reason = evaluate_dataset_flag(detections, cardinality)

        result["rows_scanned"] = rows_limit
        result["pii_found"] = pii_found
        result["pii_flag_reason"] = flag_reason
        # Derive types from the post-filter detections so the summary never
        # lists an entity type whose hits were all filtered out.
        result["pii_types"] = sorted({d["entity_type"] for d in detections})
        result["entity_count"] = len(detections)
        result["detections"] = detections
    except Exception as e:
        result["error"] = str(e)

    return result


def _scan_s3_csv(s3_client, uuid, s3_key):
    """Download one CSV from S3 and run the shared PII scan over it.

    Returns the scan-result fields (rows_scanned/pii_found/pii_types/
    entity_count/detections) shared by every S3-backed caller (LOT 1's
    batch-wise scan_file and LOT 2's per-ministry scan_file_lot2).
    """
    global _analyzer, _gpu_ner, _max_rows, _ner_batch_size

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        s3_client.download_file(S3_BUCKET, s3_key, tmp_path)

        df = read_csv_robust(tmp_path)
        columns, skipped_columns = select_detection_columns(df, return_skipped=True)
        log_column_selection(uuid, columns, skipped_columns)
        if not columns:
            return {"rows_scanned": 0, "pii_found": False,
                    "pii_flag_reason": "no scannable columns", "pii_types": [],
                    "entity_count": 0, "detections": [], "degraded": False,
                    "columns_scanned": [], "columns_skipped": skipped_columns}

        rows_limit = min(_max_rows, len(df))
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

        # Batched GPU NER + CPU spaCy/Presidio across all cells in this file.
        # batch_analyze_cells preserves whatever each pass produced, so a
        # failure here means the file was scanned in a degraded mode rather
        # than not scanned at all -- which the result records explicitly.
        degraded = False
        try:
            cache = batch_analyze_cells(
                cell_info, _analyzer, _gpu_ner, ner_batch_size=_ner_batch_size
            )
        except Exception as exc:
            logging.error(f"Batch analysis failed for {uuid}: {exc}")
            cache = {}
            degraded = True

        for (row_i, col), analyzer_results in cache.items():
            text = cell_text[(row_i, col)]
            for r in analyzer_results:
                if not keep_result(r, text):
                    continue
                snippet = text[r.start:r.end]
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

        # Every surviving detection is still recorded; the flag is a stricter,
        # separate question -- one PERSON hit in a repeated-value column is
        # not evidence that this dataset carries personal data.
        cardinality = {col: column_cardinality_ratio(df[col], rows_limit) for col in columns}
        pii_found, flag_reason = evaluate_dataset_flag(detections, cardinality)

        return {
            "rows_scanned": rows_limit,
            "pii_found": pii_found,
            "pii_flag_reason": flag_reason,
            # Derive types from the post-filter detections so the summary
            # never lists an entity type whose hits were all filtered out.
            "pii_types": sorted({d["entity_type"] for d in detections}),
            "entity_count": len(detections),
            "detections": detections,
            "degraded": degraded,
            "columns_scanned": columns,
            "columns_skipped": skipped_columns,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def scan_file(args):
    """Process one CSV file from S3, batch-wise (LOT 1). Returns a result dict."""
    uuid, batch = args
    s3_key = f"{S3_DATASET_PREFIX}/batch_{batch}/{uuid}.csv"
    result = {
        "uuid": uuid,
        "batch": batch,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "degraded": False,
        "pii_flag_reason": None,
        "columns_scanned": [],
        "columns_skipped": [],
        "error": None,
    }
    try:
        result.update(_scan_s3_csv(boto3.client("s3"), uuid, s3_key))
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404" or error_code == "NoSuchKey":
            result["error"] = f"File not found: {s3_key}"
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


def scan_file_lot2(args):
    """Process one CSV file from a per-ministry S3 folder (LOT 2). Returns a result dict."""
    uuid, ministry, s3_key = args
    result = {
        "uuid": uuid,
        "ministry": ministry,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "degraded": False,
        "pii_flag_reason": None,
        "columns_scanned": [],
        "columns_skipped": [],
        "error": None,
    }
    try:
        result.update(_scan_s3_csv(boto3.client("s3"), uuid, s3_key))
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404" or error_code == "NoSuchKey":
            result["error"] = f"File not found: {s3_key}"
        else:
            result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


# --- Main ---

def run_lot2(args, use_gpu):
    """LOT 2 driver: iterate per-ministry S3 folders directly (no batch numbers),
    tracking progress in remain_raw_metadata and writing detections to
    pii-results-lot2/<ministry>/ + the local pii_detections_lot2 table."""
    global _analyzer, _gpu_ner, _max_rows, _ner_batch_size

    use_multiprocessing = args.worker_count is not None and args.worker_count > 1
    logging.info(f"LOT 2 | Workers: {args.worker_count} | GPU: {use_gpu} | Max rows: {args.max_rows}")

    s3_client = get_s3_client()

    pool = None
    if use_multiprocessing:
        mp.set_start_method('spawn', force=True)
        pool = mp.Pool(
            processes=args.worker_count,
            initializer=_init_worker,
            initargs=(use_gpu, args.max_rows, args.ner_batch_size, LOT2_LOG_PATH),
        )
    else:
        device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        _analyzer, _gpu_ner = build_analyzer(
            include_transformer_recognizer=True, device=device
        )
        _max_rows = args.max_rows
        _ner_batch_size = args.ner_batch_size
        logging.info(f"Initialized analyzer (device={device})")

    tracked_df = read_remain_raw_metadata()
    tested_uuids = set(tracked_df.loc[tracked_df["pii_tested"] == True, "uuid"])
    logging.info(f"{LOT2_LOCAL_TABLE}: {len(tracked_df)} total, {len(tested_uuids)} already tested")

    ministries = list_ministry_folders(s3_client, S3_BUCKET, root_prefix=LOT2_S3_ROOT_PREFIX)
    if args.ministry is not None:
        if args.ministry not in ministries:
            logging.error(f"Ministry '{args.ministry}' not found. Available: {ministries}")
            return
        ministries = [args.ministry]

    logging.info(f"Ministries to process: {len(ministries)} -> {ministries}")

    for ministry in ministries:
        logging.info("=" * 50)
        logging.info(f"Starting ministry: {ministry}")

        csv_items = list_ministry_csv_keys(s3_client, S3_BUCKET, ministry, root_prefix=LOT2_S3_ROOT_PREFIX)
        pending = [(uuid, ministry, key) for uuid, key in csv_items if uuid not in tested_uuids]

        if not pending:
            logging.info(f"No pending files for {ministry}, skipping.")
            continue

        if args.limit is not None and args.limit > 0:
            pending = pending[:args.limit]
            logging.info(f"Limited to {args.limit} datasets")

        logging.info(f"Processing {len(pending)} files...")

        if use_multiprocessing:
            results = pool.map(scan_file_lot2, pending)
        else:
            results = [scan_file_lot2(item) for item in pending]

        pii_count = 0
        error_count = 0
        degraded_count = 0
        all_detections = []
        updates_for_db = []

        for result in results:
            uuid = result["uuid"]

            if result["error"]:
                logging.warning(f"Error on {uuid}: {result['error']}")
                error_count += 1
                continue

            if result.get("degraded"):
                degraded_count += 1

            pii_found = result["pii_found"]
            updates_for_db.append({
                "uuid": uuid,
                "pii_tested": True,
                "pii_detected": pii_found,
                "pii_test_timestamp": datetime.now(timezone.utc).isoformat(),
                "ministry_folder": ministry,
                "pii_flag_reason": result.get("pii_flag_reason"),
            })
            tested_uuids.add(uuid)

            if pii_found:
                pii_count += 1
                logging.info(
                    f"PII found: {uuid} | types: {result['pii_types']} | "
                    f"entities: {result['entity_count']} | "
                    f"reason: {result.get('pii_flag_reason')}"
                )
            elif result["entity_count"]:
                # Detections exist but did not corroborate a dataset-level
                # flag. Worth seeing: this is where the new rule changes the
                # answer versus "any hit flags".
                logging.info(
                    f"Detections not flagged: {uuid} | entities: {result['entity_count']} | "
                    f"reason: {result.get('pii_flag_reason')}"
                )

            if result["detections"]:
                all_detections.extend(result["detections"])

        if updates_for_db:
            update_remain_raw_metadata(pd.DataFrame(updates_for_db))

        save_lot2_detection_results(s3_client, all_detections, ministry)
        upload_remain_raw_metadata_snapshot(s3_client)

        processed = len(results) - error_count
        logging.info("=" * 50)
        logging.info(
            f"Ministry {ministry} done. Processed: {processed} | PII found: {pii_count} | "
            f"Errors: {error_count} | Degraded scans: {degraded_count}")
        logging.info("=" * 50)

    if pool is not None:
        pool.close()
        pool.join()


def main():
    global _analyzer, _gpu_ner, _max_rows, _ner_batch_size
    parser = argparse.ArgumentParser(description="Run PII detection on S3 datasets.")
    parser.add_argument("--batch", type=int, default=None, help="Process only this batch")
    parser.add_argument("--iterate", type=int, nargs="?", const=-1, default=None, metavar="N",
                        help="After --batch finishes, continue through subsequent batches. Optionally limit to N batches total (including the starting batch).")
    parser.add_argument("--max-rows", type=int, default=250, help="Max rows to scan per CSV")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU, use CPU only")
    parser.add_argument("--ner-batch-size", type=int, default=64,
                        help="Batch size for the GPU NER models (raise if nvidia-smi shows low utilization)")
    parser.add_argument("--worker-count", type=int, default=1,
                        help="Worker processes; 1 = single process (recommended on one GPU). "
                             "Each extra worker loads its own copy of the models.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of datasets to process (optional)")
    parser.add_argument("--path", type=str, default=None, help="Run PII detection on a local CSV file (skips S3/DuckDB)")
    parser.add_argument("--lot2", action="store_true",
                        help="Run LOT 2: scan datasets directly from the per-ministry S3 folders under "
                             "downloaded-datasets/ (skipping downloaded-datasets-mohfw/ and ogdp-sample-datasets/), "
                             "tracked in remain_raw_metadata instead of the batch-wise dublin_core_metadata flow.")
    parser.add_argument("--ministry", type=str, default=None,
                        help="LOT 2 only: restrict to a single ministry folder (e.g. ministry-of-tourism)")
    args = parser.parse_args()

    use_gpu = not args.no_gpu and torch.cuda.is_available()

    if args.lot2:
        configure_logging(LOT2_LOG_PATH)
        run_lot2(args, use_gpu)
        return

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
                mp.set_start_method('spawn', force=True)
                pool = mp.Pool(
                    processes=args.worker_count,
                    initializer=_init_worker,
                    initargs=(use_gpu, args.max_rows, args.ner_batch_size),
                )
                results = pool.map(scan_local_file, csv_files)
                pool.close()
                pool.join()
            else:
                _max_rows = args.max_rows
                _ner_batch_size = args.ner_batch_size
                _analyzer, _gpu_ner = build_analyzer(
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
            _ner_batch_size = args.ner_batch_size
            _analyzer, _gpu_ner = build_analyzer(
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

    use_multiprocessing = args.worker_count is not None and args.worker_count > 1

    if use_multiprocessing:
        logging.info(f"Workers: {args.worker_count} | GPU: {use_gpu} | Max rows: {args.max_rows}")
    else:
        logging.info(f"Single process | GPU: {use_gpu} | Max rows: {args.max_rows}")

    s3_client = get_s3_client()

    # Initialize models once (reused across all batches when iterating)
    pool = None
    if use_multiprocessing:
        mp.set_start_method('spawn', force=True)
        pool = mp.Pool(
            processes=args.worker_count,
            initializer=_init_worker,
            initargs=(use_gpu, args.max_rows, args.ner_batch_size),
        )
    else:
        device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        _analyzer, _gpu_ner = build_analyzer(
            include_transformer_recognizer=True, device=device
        )
        _max_rows = args.max_rows
        _ner_batch_size = args.ner_batch_size
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
            results = pool.map(scan_file, pending)
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

    if pool is not None:
        pool.close()
        pool.join()


if __name__ == "__main__":
    main()
