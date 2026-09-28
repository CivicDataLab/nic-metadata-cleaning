"""
Generate redacted versions of CSV files where PII was detected.

Two sources of truth, and they are not the same thing:

  S3 (default)  every file with pii_detected=True in the tracking table is
                downloaded, redacted whole and uploaded to redacted-datasets.
                That flag is the raw detector's, so files the tiers later
                cleared as false positives are redacted too.
  --run-dir     only the columns a pii_classify_pipeline.py run ended up
                calling `present` are redacted, in the local files it scanned.
                This is the path that respects the tiers.

Usage:
    python generate_redacted.py                 # redact all flagged files (S3)
    python generate_redacted.py --batch 1       # redact batch 1 only
    python generate_redacted.py --lot2 --ministry ministry-of-tourism
    python generate_redacted.py --run-dir OUT --scan-dir SCAN_DIR \\
        --out-dir OUT/redacted --workers 3

pii_classify_pipeline.py --redact calls the --run-dir path directly, so both
tiers and the redaction run in one command. Use this script on its own to
redact a run that already finished -- KCC, whose verdicts carry a
hand-applied override that re-running the pipeline would drop.
"""

import argparse
import csv
import logging
import multiprocessing as mp
import os
import shutil
import sys
import tempfile

import boto3
import duckdb
import pandas as pd
import torch
from botocore.exceptions import ClientError
from presidio_anonymizer import AnonymizerEngine

from pii_filters import filter_detections
from pii_utils import (
    LOT2_S3_ROOT_PREFIX,
    RecognizerResult,
    analyze_multi_language,
    build_analyzer,
    column_cardinality_ratio,
    detect_language,
    keep_result,
    regex_pii_matches,
    regex_matches_to_results,
    resolve_overlaps,
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


# --------------------------------------------------------------- redaction --
# Redaction runs the same passes the scan does -- analyzer, PM-Kisan field
# labels, regex recognizers, then pii_filters -- so it removes what the scan
# called personal data and nothing else. Presidio on its own reads "प्रधान
# मंत्री किसान सम्मान" as a PERSON, and a KCC answer comes back with the
# scheme it names replaced by <PERSON>. The filters are where that knowledge
# lives, so redaction has to go through them too.
#
# The S3 runs also redact only the rows they scanned (--max-rows, default
# 250). That cap belongs to detection, where a sample is enough to judge a
# file; a redacted copy cut off at the same row still ships every name below
# it, so the local redaction further down redacts every row instead.

CELL_CONTEXT_CHARS = 64          # run_pii_s3.CELL_CONTEXT_CHARS
_structured_names = None


def _load_structured_names():
    """run_pii_s3's PM-Kisan field-label extractor, without its logging setup.

    That module reconfigures the root logger at import (force=True, into
    pii_s3.log), which would silently redirect this script's own output, so
    the handlers are put back afterwards.
    """
    global _structured_names
    if _structured_names is None:
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        try:
            from run_pii_s3 import extract_structured_names
        finally:
            root.handlers[:] = handlers
            root.setLevel(level)
        _structured_names = extract_structured_names
    return _structured_names


def cell_spans(text):
    """Every PII span in one cell as (result, source), overlaps resolved."""
    language = detect_language(text)
    langs = [language] if language == "en" else [language, "en"]
    try:
        results = analyze_multi_language(_analyzer, text, langs)
    except Exception:                                           # noqa: BLE001
        results = []
    merged = resolve_overlaps(list(results) + _load_structured_names()(text))
    spans = [(r, "presidio") for r in merged if keep_result(r, text)]
    return spans + [(r, "regex")
                    for r in regex_matches_to_results(regex_pii_matches(text))]


def redact_dataframe(df, columns, max_rows=None, label="", apply_filters=True):
    """Redact `columns` of `df` in place. Returns the number of cells changed.

    One column at a time, because pii_filters' second pass reads a whole
    column -- how often a value repeats, how distinct the column is -- and
    per cell it would reach different answers than the scan did.
    max_rows=None redacts every row.
    """
    rows = len(df) if max_rows is None else min(max_rows, len(df))
    changed = 0
    for col in columns:
        if col not in df.columns:
            continue
        position = df.columns.get_loc(col)
        cells, padding, detections = {}, {}, []
        for row_i in range(rows):
            value = df.iat[row_i, position]
            raw = "" if pd.isna(value) else str(value)
            text = raw.strip()
            if not text:
                continue
            cells[row_i] = text
            # The scan analyses the stripped cell, so the spans are offsets
            # into that; the padding goes back on so a redacted cell differs
            # from the original only where a span was cut out.
            padding[row_i] = (raw[:len(raw) - len(raw.lstrip())],
                              raw[len(raw.rstrip()):])
            try:
                spans = cell_spans(text)
            except Exception as exc:                            # noqa: BLE001
                logging.warning(f"Analysis failed for {label} col={col} "
                                f"row={row_i}: {exc}")
                continue
            for r, source in spans:
                detections.append({
                    "column": col, "row_index": row_i,
                    "entity_type": r.entity_type,
                    "entity_text": text[r.start:r.end],
                    "score": r.score, "source": source,
                    # start/end are this script's own: pii_filters passes
                    # unknown keys through, and the anonymizer needs them
                    # back to cut the span out of the cell.
                    "start": r.start, "end": r.end,
                    "cell_len": len(text),
                    "left_context": text[max(0, r.start - CELL_CONTEXT_CHARS):r.start],
                })

        if apply_filters:
            detections = filter_detections(
                detections, {col: column_cardinality_ratio(df[col], rows)})

        by_row = {}
        for detection in detections:
            by_row.setdefault(detection["row_index"], []).append(detection)
        for row_i, found in by_row.items():
            text = cells[row_i]
            results = [RecognizerResult(d["entity_type"], d["start"], d["end"],
                                        d["score"]) for d in found]
            try:
                redacted = _anonymizer.anonymize(text=text,
                                                 analyzer_results=results).text
            except Exception as exc:                            # noqa: BLE001
                logging.warning(f"Redaction failed for {label} col={col} "
                                f"row={row_i}: {exc}")
                continue
            if redacted != text:
                lead, trail = padding[row_i]
                df.iat[row_i, position] = lead + redacted + trail
                changed += 1
    return changed


def _redact_s3_csv(s3_client, uuid, s3_key, redacted_key):
    """Download one CSV from S3, redact PII in place, and upload the redacted
    copy to redacted_key. Shared by LOT 1's batch-wise redact_file and LOT 2's
    per-ministry redact_file_lot2."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        s3_client.download_file(S3_BUCKET, s3_key, tmp_path)

        df = pd.read_csv(tmp_path)
        columns = select_detection_columns(df)
        if columns:
            redact_dataframe(df, columns, max_rows=_max_rows, label=uuid)

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


# ---------------------------------------------------------- local corpus ----
# The tiers classify every (file, column) pair, and only the columns they end
# up calling `present` hold personal data. Redacting a whole flagged file --
# what the S3 path above does, off the pii_detected boolean -- throws that
# work away: a column the tiers cleared should reach the public copy intact.

REDACT_CLASSES = ("present",)
DETECTION_NAME = "pii_detections.csv"        # pii_classify.FOLDER_DETECTIONS_NAME
DETECTION_SUFFIX = "_pii_detections.csv"
LOG_NAME = "redaction_log.csv"


def inside(path, parent):
    path, parent = os.path.abspath(path), os.path.abspath(parent)
    return os.path.commonpath([path, parent]) == parent


def scan_root(paths):
    """The folder a --csv run's uuids are relative to (see pii_classify.load_csv)."""
    return os.path.commonpath(
        [os.path.abspath(p if os.path.isdir(p) else os.path.dirname(p) or ".")
         for p in paths])


def targets_from_rows(rows, classes=REDACT_CLASSES, scan_dir=None):
    """(source file, relative path, columns) per file with a column in `classes`.

    `rows` are pii_column_class-shaped. `uuid` is the scanned file's path
    relative to the scan folder -- which is also where its redacted copy goes
    -- and `source_file` is where it sits on disk. A --csv run records that;
    for rows read from the DB, pass scan_dir and it is rebuilt from the uuid.
    """
    wanted = {}
    for row in rows:
        if row.get("pii_class") not in classes:
            continue
        uuid = str(row["uuid"])
        source = row.get("source_file") or (
            os.path.join(scan_dir, uuid) if scan_dir else None)
        if not source:
            raise ValueError(f"{uuid} has no source_file; pass --scan-dir")
        wanted.setdefault((source, uuid), []).append(row["column"])
    return [(source, uuid, columns)
            for (source, uuid), columns in sorted(wanted.items())]


def targets_from_class_csv(path, classes=REDACT_CLASSES, scan_dir=None):
    """targets_from_rows over a finished run's column_class.csv."""
    with open(path, newline="", encoding="utf-8") as handle:
        return targets_from_rows(list(csv.DictReader(handle)), classes, scan_dir)


def _redact_local(task):
    """Pool worker: redact one local CSV into its destination."""
    source, dest, columns = task
    result = {"source": source, "dest": dest, "columns": "; ".join(columns),
              "cells_redacted": 0, "error": None}
    if os.path.splitext(source)[1].lower() != ".csv":
        result["error"] = "redaction reads CSV only"
        return result
    try:
        # dtype=str with keep_default_na off leaves every cell the analyzer
        # does not touch byte-identical; pandas' own inference would write 7
        # back as 7.0 and blank out a literal "NA".
        df = pd.read_csv(source, dtype=str, keep_default_na=False,
                         on_bad_lines="skip")
        result["cells_redacted"] = redact_dataframe(df, columns, _max_rows, source)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        df.to_csv(dest, index=False)
    except Exception as exc:                                    # noqa: BLE001
        result["error"] = str(exc)
    return result


def redact_local(targets, out_dir, use_gpu=True, workers=1, max_rows=None,
                 progress=None):
    """Write a redacted copy of each target under out_dir, keeping its path."""
    tasks = [(source, os.path.join(out_dir, uuid.replace("/", os.sep)), columns)
             for source, uuid, columns in targets]
    results = []
    if workers > 1:
        pool = mp.Pool(workers, initializer=_init_worker,
                       initargs=(use_gpu, max_rows))
        try:
            for result in pool.imap(_redact_local, tasks):
                results.append(result)
                if progress:
                    progress(len(results), len(tasks), result)
        finally:
            pool.close()
            pool.join()
    else:
        _init_worker(use_gpu, max_rows)
        for task in tasks:
            results.append(_redact_local(task))
            if progress:
                progress(len(results), len(tasks), results[-1])
    return results


def copy_unredacted(root, out_dir, redacted):
    """Copy the scanned files that needed no redaction, so out_dir holds the
    whole corpus rather than only its rewritten files. The scan's own
    detection CSVs stay behind -- they quote the personal data by design."""
    copied = 0
    for dirpath, _, filenames in sorted(os.walk(root)):
        for name in sorted(filenames):
            if name == DETECTION_NAME or name.endswith(DETECTION_SUFFIX):
                continue
            source = os.path.join(dirpath, name)
            rel = os.path.relpath(source, root)
            if rel.replace(os.sep, "/") in redacted:
                continue
            dest = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            shutil.copy2(source, dest)
            copied += 1
    return copied


def write_redaction_log(path, results):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["source", "dest", "columns", "cells_redacted", "error"])
        writer.writeheader()
        writer.writerows(results)


def redact_to_dir(targets, out_dir, use_gpu=True, workers=1, max_rows=None,
                  copy_clean_root=None):
    """Redact the targets into out_dir, log the run and report what happened."""
    os.makedirs(out_dir, exist_ok=True)

    def progress(done, total, result):
        mark = result["error"] or f"{result['cells_redacted']} cell(s)"
        print(f"[{done}/{total}] {os.path.basename(result['source'])[:50]:<50} "
              f"{mark}", file=sys.stderr, flush=True)

    results = redact_local(targets, out_dir, use_gpu, workers, max_rows, progress)
    write_redaction_log(os.path.join(out_dir, LOG_NAME), results)
    if copy_clean_root:
        copied = copy_unredacted(copy_clean_root, out_dir,
                                 {uuid for _, uuid, _ in targets})
        print(f"copied {copied} file(s) that needed no redaction", file=sys.stderr)
    failed = [r for r in results if r["error"]]
    cells = sum(r["cells_redacted"] for r in results)
    print(f"redacted {len(results) - len(failed)} file(s), {cells} cell(s) -> "
          f"{out_dir}" + (f" | {len(failed)} failed, see {LOG_NAME}" if failed else ""),
          file=sys.stderr)
    return results


def redact_from_run(args):
    """--run-dir: redact the local files a finished pipeline run left `present`."""
    if not args.out_dir:
        raise SystemExit("--run-dir needs --out-dir")
    column_class = (args.run_dir if os.path.isfile(args.run_dir)
                    else os.path.join(args.run_dir, "column_class.csv"))
    if not os.path.exists(column_class):
        raise SystemExit(f"{column_class} not found -- run pii_classify_pipeline.py first")
    if args.copy_clean and not args.scan_dir:
        raise SystemExit("--copy-clean needs --scan-dir, the folder to copy from")
    if args.scan_dir and inside(args.out_dir, args.scan_dir):
        raise SystemExit(f"--out-dir {args.out_dir} is inside the scanned folder "
                         f"{args.scan_dir}; a rescan would read the redacted copies as data")

    classes = tuple(c.strip() for c in args.classes.split(",") if c.strip())
    targets = targets_from_class_csv(column_class, classes, args.scan_dir)
    if not targets:
        print(f"no column classified {'/'.join(classes)} in {column_class}; "
              f"nothing to redact")
        return 0
    print(f"redacting {sum(len(c) for _, _, c in targets)} column(s) in "
          f"{len(targets)} file(s)", file=sys.stderr)
    use_gpu = not args.no_gpu and torch.cuda.is_available()
    redact_to_dir(targets, args.out_dir, use_gpu, args.workers,
                  args.max_rows or None,
                  copy_clean_root=args.scan_dir if args.copy_clean else None)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=int, default=None, help="Process only this batch")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="Max rows to redact per CSV (0 = every row; default: "
                             "250 on S3, every row with --run-dir)")
    parser.add_argument("--no-gpu", action="store_true", help="Disable GPU")
    parser.add_argument("--lot2", action="store_true",
                        help="Run LOT 2: redact files flagged in remain_raw_metadata (per-ministry S3 "
                             "folders) instead of the batch-wise tracking parquet.")
    parser.add_argument("--ministry", type=str, default=None,
                        help="LOT 2 only: restrict to a single ministry folder (e.g. ministry-of-tourism)")
    local = parser.add_argument_group(
        "local folder", "redact the files a pii_classify_pipeline.py run classified, "
        "instead of everything S3 has flagged")
    local.add_argument("--run-dir", metavar="DIR",
                       help="that run's --out-dir (or its column_class.csv)")
    local.add_argument("--out-dir", metavar="DIR",
                       help="--run-dir only: where the redacted copies go, each keeping "
                            "its path inside the scanned folder")
    local.add_argument("--scan-dir", metavar="DIR",
                       help="--run-dir only: the scanned folder, for --copy-clean and "
                            "for rows with no source_file")
    local.add_argument("--classes", default=",".join(REDACT_CLASSES), metavar="LIST",
                       help="--run-dir only: which column classes to redact "
                            "(default: %(default)s)")
    local.add_argument("--copy-clean", action="store_true",
                       help="--run-dir only: also copy the files that needed no "
                            "redaction, so --out-dir is a full copy of the folder")
    local.add_argument("--workers", type=int, default=1, metavar="N",
                       help="--run-dir only: redaction processes (default: 1)")
    args = parser.parse_args()

    if args.run_dir:
        return redact_from_run(args)
    if args.max_rows is None:
        args.max_rows = 250

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
    sys.exit(main() or 0)
