"""
Re-scan a sample of already-scanned LOT 2 datasets and write the results to CSV.

This is the measurement run for the round-2 filter work: it exercises the real
scan path (``run_pii_s3._scan_s3_csv``) end to end, so it sees the effect of
the word-level NER aggregation that ``evaluate_filters.py`` structurally
cannot -- that replays stored spans, which are already fragmented.

**Writes nothing but CSV.** No DuckDB updates, no S3 uploads, no table resets.
The existing pii_detections_lot2 rows stay in place and are used as the
"before" side of the comparison.

Two files come out:

``<out>_detections.csv``  one row per surviving detection
``<out>_datasets.csv``    one row per dataset, with the before/after counts
                          and the dataset-level flag and its reason

Usage:
    python pii_test/rescan_sample.py --limit 1000
    python pii_test/rescan_sample.py --limit 200 --order scan   # first N in scan order
    python pii_test/rescan_sample.py --limit 1000 --out /tmp/round2
"""

import argparse
import csv
import logging
import os
import sys
import time

import boto3
import duckdb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_pii_s3 as R  # noqa: E402
from pii_utils import LOT2_S3_ROOT_PREFIX  # noqa: E402

DB_PATH = "transformation/metadata.db"
METADATA_TABLE = "remain_raw_metadata"
DETECTIONS_TABLE = "pii_detections_lot2"
LOG_PATH = "pii_test/rescan_sample.log"
DEFAULT_OUT = "pii_test/rescan_sample"

DETECTION_FIELDS = ("uuid", "ministry", "column", "row_index",
                    "entity_type", "entity_text", "score", "source")
DATASET_FIELDS = (
    "uuid", "ministry", "rows_scanned", "columns_scanned", "columns_skipped",
    "entities_before", "entities_after", "flag_before", "flag_after",
    "flag_reason_before", "flag_reason_after", "degraded", "error",
)

# Sampling orders. "hash" is the deterministic spread this repo already uses
# for label templates: the same sample comes back on every re-run, and it
# covers every ministry rather than whichever one sorts first. "scan" is the
# literal head of the run order, which on this corpus is ~90% one ministry.
ORDERS = {"hash": "hash(uuid)", "scan": "ministry_folder, uuid"}


def select_sample(conn, limit, order):
    """The datasets to re-scan, plus their stored before-state."""
    return conn.execute(f"""
        WITH sample AS (
            SELECT uuid, ministry_folder, pii_detected, pii_flag_reason
            FROM {METADATA_TABLE}
            WHERE pii_tested = TRUE AND ministry_folder IS NOT NULL
            ORDER BY {ORDERS[order]}
            LIMIT ?
        ),
        before AS (
            SELECT uuid, COUNT(*) AS n FROM {DETECTIONS_TABLE} GROUP BY uuid
        )
        SELECT s.uuid, s.ministry_folder, COALESCE(b.n, 0),
               s.pii_detected, s.pii_flag_reason
        FROM sample s LEFT JOIN before b USING (uuid)
    """, [limit]).fetchall()


def summarise(rows, detections_by_type, before_total, before_flagged):
    after_total = sum(r["entities_after"] for r in rows)
    after_flagged = sum(1 for r in rows if r["flag_after"])
    errors = sum(1 for r in rows if r["error"])

    def change(before, after):
        return f"{100 * (after - before) / before:+.1f}%" if before else "n/a"

    logging.info("=" * 72)
    logging.info(f"Datasets re-scanned    {len(rows):>10,}   ({errors} error(s))")
    logging.info(f"Detections   before    {before_total:>10,}")
    logging.info(f"             after     {after_total:>10,}   "
                 f"{change(before_total, after_total)}")
    logging.info(f"Flagged      before    {before_flagged:>10,}")
    logging.info(f"             after     {after_flagged:>10,}   "
                 f"{change(before_flagged, after_flagged)}")
    logging.info("=" * 72)
    logging.info("Surviving detections by entity type:")
    for entity_type, n in sorted(detections_by_type.items(), key=lambda kv: -kv[1]):
        logging.info(f"  {n:>8,}  {entity_type}")


def report_survivors(survivors, limit):
    if not (limit and survivors):
        return
    logging.info("")
    logging.info(f"Top {limit} surviving (column, text) pairs -- "
                 f"the target list for the next vocabulary pass:")
    for (column, text), n in sorted(survivors.items(), key=lambda kv: -kv[1])[:limit]:
        logging.info(f"  {n:>6,}  {column!r:38} {text!r}")


def report_flag_changes(rows, limit=15):
    gained = [r for r in rows if r["flag_after"] and not r["flag_before"]]
    lost = [r for r in rows if r["flag_before"] and not r["flag_after"]]
    logging.info("")
    logging.info(f"Flag changes: {len(lost)} un-flagged, {len(gained)} newly flagged")
    for label, group in (("newly flagged", gained), ("un-flagged", lost)):
        for r in group[:limit]:
            logging.info(f"  {label:<14} {r['uuid']}  {r['flag_reason_after']}")
        if len(group) > limit:
            logging.info(f"  ... and {len(group) - limit} more {label}")


def main():
    parser = argparse.ArgumentParser(
        description="Re-scan a sample of LOT 2 datasets to CSV. Writes no database rows.")
    parser.add_argument("--limit", type=int, default=1000,
                        help="How many datasets to re-scan")
    parser.add_argument("--order", choices=sorted(ORDERS), default="hash",
                        help="hash: deterministic spread across ministries (default). "
                             "scan: the literal head of the original run order.")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="Output prefix; _detections.csv and _datasets.csv are appended")
    parser.add_argument("--max-rows", type=int, default=250,
                        help="Max rows to scan per CSV (must match the real run to compare)")
    parser.add_argument("--ner-batch-size", type=int, default=64)
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--survivors", type=int, default=30,
                        help="How many surviving (column, text) pairs to list (0 to skip)")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH} (run from the repo root)")

    R.configure_logging(LOG_PATH)
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

    import torch
    device = "cpu" if args.no_gpu or not torch.cuda.is_available() else "cuda"

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        sample = select_sample(conn, args.limit, args.order)
    finally:
        conn.close()
    if not sample:
        raise SystemExit("No scanned datasets matched the sample query")

    logging.info(f"Re-scanning {len(sample):,} dataset(s), order={args.order}, "
                 f"device={device}, max_rows={args.max_rows}")

    R._analyzer, R._gpu_ner = R.build_analyzer(
        include_transformer_recognizer=True, device=device)
    R._max_rows = args.max_rows
    R._ner_batch_size = args.ner_batch_size

    s3 = boto3.client("s3")
    detections_path = f"{args.out}_detections.csv"
    datasets_path = f"{args.out}_datasets.csv"
    os.makedirs(os.path.dirname(detections_path) or ".", exist_ok=True)

    rows, survivors, by_type = [], {}, {}
    before_total = sum(r[2] for r in sample)
    before_flagged = sum(1 for r in sample if r[3])
    started = time.time()

    # Detections stream to disk as they are produced, so a failure partway
    # through a 1,000-dataset run still leaves usable output.
    with open(detections_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DETECTION_FIELDS, extrasaction="ignore")
        writer.writeheader()

        for i, (uuid, ministry, n_before, flag_before, reason_before) in enumerate(sample, 1):
            s3_key = f"{LOT2_S3_ROOT_PREFIX}{ministry}/{uuid}.csv"
            record = {
                "uuid": uuid, "ministry": ministry, "rows_scanned": 0,
                "columns_scanned": 0, "columns_skipped": 0,
                "entities_before": n_before, "entities_after": 0,
                "flag_before": bool(flag_before), "flag_after": False,
                "flag_reason_before": reason_before, "flag_reason_after": None,
                "degraded": False, "error": None,
            }
            try:
                result = R._scan_s3_csv(s3, uuid, s3_key)
            except Exception as exc:
                record["error"] = str(exc)
                logging.warning(f"{uuid}: {exc}")
            else:
                record.update({
                    "rows_scanned": result["rows_scanned"],
                    "columns_scanned": len(result["columns_scanned"]),
                    "columns_skipped": len(result["columns_skipped"]),
                    "entities_after": result["entity_count"],
                    "flag_after": bool(result["pii_found"]),
                    "flag_reason_after": result["pii_flag_reason"],
                    "degraded": bool(result["degraded"]),
                })
                for detection in result["detections"]:
                    writer.writerow({**detection, "ministry": ministry})
                    key = (detection["column"], detection["entity_text"])
                    survivors[key] = survivors.get(key, 0) + 1
                    by_type[detection["entity_type"]] = \
                        by_type.get(detection["entity_type"], 0) + 1
            rows.append(record)

            if i % 25 == 0 or i == len(sample):
                fh.flush()
                rate = (time.time() - started) / i
                logging.info(f"  {i}/{len(sample)} datasets "
                             f"({rate:.2f}s each, ~{rate * (len(sample) - i) / 60:.0f} min left)")

    with open(datasets_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DATASET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summarise(rows, by_type, before_total, before_flagged)
    report_survivors(survivors, args.survivors)
    report_flag_changes(rows)
    logging.info("")
    logging.info(f"Wrote {datasets_path} and {detections_path}")


if __name__ == "__main__":
    main()
