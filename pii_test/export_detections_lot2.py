"""
Export LOT 2 PII detections from the pii_detections_lot2 table.

The table is the source of truth. By default this writes the full consolidated
set as both CSV and parquet; pass --ministry or --uuid to slice it.

Usage:
    # Consolidated CSV + parquet of everything (default)
    python pii_test/export_detections_lot2.py

    # One ministry, one uuid
    python pii_test/export_detections_lot2.py --ministry ministry-of-finance
    python pii_test/export_detections_lot2.py --uuid 00a348f6-dfd7-4e03-95b0-91e975272883

    # Narrow further, choose format, push to S3
    python pii_test/export_detections_lot2.py --ministry ministry-of-education \
        --entity-type PERSON --min-score 0.9 --format csv --upload

    # See what's available / just count
    python pii_test/export_detections_lot2.py --list-ministries
    python pii_test/export_detections_lot2.py --ministry ministry-of-finance --count-only
"""

import argparse
import logging
import os
import tempfile

import boto3
import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

DB_PATH = "transformation/metadata.db"
S3_BUCKET = "nic-ogdp-datasets"
DETECTIONS_TABLE = "pii_detections_lot2"
# Consolidated (unfiltered) exports overwrite this pair; filtered exports get
# a name derived from the filter so they never clobber the full set.
S3_CONSOLIDATED_BASE_KEY = "pii-results-lot2/pii_detections"
S3_LOT2_RESULTS_PREFIX = "pii-results-lot2"
S3_SLICE_PREFIX = "pii-results-lot2/slices"


def build_where(args):
    """Build a WHERE clause plus its bind parameters from the filter args."""
    clauses, params = [], []
    if args.ministry:
        clauses.append("ministry = ?")
        params.append(args.ministry)
    if args.uuid:
        clauses.append("uuid = ?")
        params.append(args.uuid)
    if args.entity_type:
        clauses.append("entity_type = ?")
        params.append(args.entity_type)
    if args.source:
        clauses.append("source = ?")
        params.append(args.source)
    if args.min_score is not None:
        clauses.append("score >= ?")
        params.append(args.min_score)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def upload_key(args, name, fmt):
    """S3 key for an export.

    Unfiltered exports refresh the canonical consolidated pair. A plain
    --ministry export refreshes that ministry's own file, matching where
    run_pii_s3.py --lot2 writes it. Anything more specific lands under
    slices/ so it can never overwrite either.
    """
    if name is None:
        return f"{S3_CONSOLIDATED_BASE_KEY}.{fmt}"
    only_ministry = args.ministry and not any(
        (args.uuid, args.entity_type, args.source, args.min_score is not None))
    if only_ministry and fmt == "csv":
        return f"{S3_LOT2_RESULTS_PREFIX}/{args.ministry}/pii_detections.csv"
    return f"{S3_SLICE_PREFIX}/{name}.{fmt}"


def slug(args):
    """Name for a filtered export; None when nothing is filtered."""
    parts = []
    if args.ministry:
        parts.append(args.ministry)
    if args.uuid:
        parts.append(args.uuid)
    if args.entity_type:
        parts.append(args.entity_type.lower())
    if args.source:
        parts.append(args.source)
    if args.min_score is not None:
        parts.append(f"score{args.min_score}".replace(".", "_"))
    return "_".join(parts) if parts else None


def main():
    parser = argparse.ArgumentParser(
        description="Export LOT 2 PII detections, optionally filtered by ministry or uuid.")
    parser.add_argument("--ministry", help="Filter to one ministry folder")
    parser.add_argument("--uuid", help="Filter to one dataset uuid")
    parser.add_argument("--entity-type", help="Filter to one entity type (PERSON, PHONE_NUMBER, ...)")
    parser.add_argument("--source", choices=["presidio", "regex"], help="Filter by detection source")
    parser.add_argument("--min-score", type=float, help="Keep detections scoring at least this")
    parser.add_argument("--format", choices=["csv", "parquet", "both"], default=None,
                        help="Output format. Default: both for the full consolidated export, "
                             "csv for a filtered slice.")
    parser.add_argument("--out", help="Output path/prefix. Default: ./pii_detections[_<filter>]")
    parser.add_argument("--upload", action="store_true", help="Also upload the export to S3")
    parser.add_argument("--count-only", action="store_true", help="Report matching rows, write nothing")
    parser.add_argument("--list-ministries", action="store_true",
                        help="List ministries present in the table with their row counts, then exit")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH} (run from the repo root)")

    conn = duckdb.connect(DB_PATH, read_only=True)

    tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
    if DETECTIONS_TABLE not in tables:
        raise SystemExit(f"Table {DETECTIONS_TABLE} does not exist yet — run run_pii_s3.py --lot2 first")

    if args.list_ministries:
        rows = conn.execute(f"""
            SELECT ministry, COUNT(*) AS detections, COUNT(DISTINCT uuid) AS datasets
            FROM {DETECTIONS_TABLE} GROUP BY ministry ORDER BY detections DESC
        """).fetchall()
        logging.info(f"{'ministry':<80} {'detections':>12} {'datasets':>10}")
        for ministry, detections, datasets in rows:
            logging.info(f"{ministry:<80} {detections:>12} {datasets:>10}")
        conn.close()
        return

    where, params = build_where(args)
    count = conn.execute(f"SELECT COUNT(*) FROM {DETECTIONS_TABLE}{where}", params).fetchone()[0]

    if args.count_only:
        logging.info(f"{count} matching detection(s)")
        conn.close()
        return

    if count == 0:
        logging.warning("No detections matched — nothing written.")
        conn.close()
        return

    name = slug(args)
    out_base = args.out or (f"pii_detections_{name}" if name else "pii_detections")

    # A slice of one ministry/uuid is for reading, so CSV alone; the full
    # export doubles as the canonical artifact, so it gets parquet too.
    fmt_choice = args.format or ("csv" if name else "both")
    formats = ["csv", "parquet"] if fmt_choice == "both" else [fmt_choice]

    # COPY and CREATE VIEW can't take bind parameters, but a relation can —
    # so the filter stays parameterised rather than formatted into the SQL.
    rel = conn.sql(
        f"SELECT * FROM {DETECTIONS_TABLE}{where} ORDER BY ministry, uuid", params=params
    )

    s3_client = boto3.client("s3") if args.upload else None

    for fmt in formats:
        out_path = f"{out_base}.{fmt}"
        if fmt == "csv":
            rel.write_csv(out_path, header=True)
        else:
            rel.write_parquet(out_path)
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        logging.info(f"Wrote {count} detections to {out_path} ({size_mb:.1f} MB)")

        if s3_client is not None:
            s3_client.upload_file(out_path, S3_BUCKET, upload_key(args, name, fmt))
            logging.info(f"Uploaded to s3://{S3_BUCKET}/{upload_key(args, name, fmt)}")

    conn.close()


if __name__ == "__main__":
    main()
