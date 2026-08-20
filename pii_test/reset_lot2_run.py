"""
Reset the LOT 2 scan so it can be re-run with the improved filters.

Destructive: clears pii_detections_lot2 and the pii_tested/pii_detected/
pii_flag_reason flags on remain_raw_metadata. The pre-reset state is kept in
pii_detections_lot2_baseline and remain_raw_metadata_pii_baseline, which this
script creates first if they do not already exist, so a before/after
comparison stays possible (see evaluate_filters.py --compare-baseline).

Nothing happens without --confirm.

Usage:
    python pii_test/reset_lot2_run.py                     # dry run: report only
    python pii_test/reset_lot2_run.py --confirm           # reset everything
    python pii_test/reset_lot2_run.py --ministry ministry-of-education --confirm
"""

import argparse
import logging
from datetime import date

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

DB_PATH = "transformation/metadata.db"
METADATA_TABLE = "remain_raw_metadata"
DETECTIONS_TABLE = "pii_detections_lot2"
DETECTIONS_BASELINE = "pii_detections_lot2_baseline"
METADATA_BASELINE = "remain_raw_metadata_pii_baseline"


def ensure_baselines(conn):
    """Snapshot the current results before anything is cleared.

    The named baselines are written once and never overwritten, so they stay
    anchored to the original run. On every reset after the first, the table
    about to be deleted is *also* copied to a dated snapshot -- otherwise the
    second round of filter work destroys its own "before" numbers and
    --compare-baseline silently reports against the wrong round.
    """
    tables = {t[0] for t in conn.execute("SHOW TABLES").fetchall()}
    if DETECTIONS_TABLE in tables:
        if DETECTIONS_BASELINE not in tables:
            conn.execute(
                f"CREATE TABLE {DETECTIONS_BASELINE} AS SELECT * FROM {DETECTIONS_TABLE}")
            n = conn.execute(f"SELECT COUNT(*) FROM {DETECTIONS_BASELINE}").fetchone()[0]
            logging.info(f"Created {DETECTIONS_BASELINE} ({n:,} rows)")
        else:
            snapshot = f"{DETECTIONS_TABLE}_{date.today():%Y%m%d}"
            n = conn.execute(f"SELECT COUNT(*) FROM {DETECTIONS_TABLE}").fetchone()[0]
            if n and snapshot not in tables:
                conn.execute(f"CREATE TABLE {snapshot} AS SELECT * FROM {DETECTIONS_TABLE}")
                logging.info(f"{DETECTIONS_BASELINE} already exists; saved the current "
                             f"table to {snapshot} ({n:,} rows) instead of discarding it")
    if METADATA_BASELINE not in tables:
        conn.execute(f"""
            CREATE TABLE {METADATA_BASELINE} AS
            SELECT uuid, ministry_folder, pii_tested, pii_detected, pii_test_timestamp
            FROM {METADATA_TABLE} WHERE pii_tested = TRUE
        """)
        n = conn.execute(f"SELECT COUNT(*) FROM {METADATA_BASELINE}").fetchone()[0]
        logging.info(f"Created {METADATA_BASELINE} ({n:,} rows)")


def main():
    parser = argparse.ArgumentParser(description="Reset the LOT 2 scan state.")
    parser.add_argument("--ministry", help="Reset only this ministry folder")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually perform the reset. Without it, this only reports.")
    args = parser.parse_args()

    conn = duckdb.connect(DB_PATH)
    try:
        where, params = ("WHERE ministry_folder = ?", [args.ministry]) if args.ministry else ("", [])
        tested = conn.execute(
            f"SELECT COUNT(*) FROM {METADATA_TABLE} WHERE pii_tested = TRUE"
            + (f" AND ministry_folder = ?" if args.ministry else ""), params).fetchone()[0]
        det_where, det_params = ("WHERE ministry = ?", [args.ministry]) if args.ministry else ("", [])
        detections = conn.execute(
            f"SELECT COUNT(*) FROM {DETECTIONS_TABLE} {det_where}", det_params).fetchone()[0]

        scope = args.ministry or "ALL ministries"
        logging.info(f"Scope: {scope}")
        logging.info(f"  datasets marked tested: {tested:,}")
        logging.info(f"  detection rows:         {detections:,}")

        if not args.confirm:
            logging.info("Dry run -- nothing changed. Re-run with --confirm to reset.")
            return

        ensure_baselines(conn)

        # These are added lazily by run_pii_s3.read_remain_raw_metadata, so on
        # a table that has never been scanned (or was scanned before
        # pii_flag_reason existed) the UPDATE below would fail on a missing
        # column.
        for column, sql_type in (("pii_tested", "BOOLEAN"), ("pii_detected", "BOOLEAN"),
                                 ("pii_test_timestamp", "TIMESTAMP"),
                                 ("ministry_folder", "VARCHAR"),
                                 ("pii_flag_reason", "VARCHAR")):
            conn.execute(
                f"ALTER TABLE {METADATA_TABLE} ADD COLUMN IF NOT EXISTS {column} {sql_type}")

        conn.execute(f"DELETE FROM {DETECTIONS_TABLE} {det_where}", det_params)
        conn.execute(f"""
            UPDATE {METADATA_TABLE}
            SET pii_tested = NULL, pii_detected = NULL,
                pii_test_timestamp = NULL, pii_flag_reason = NULL
            {where}
        """, params)
        logging.info(f"Reset {tested:,} dataset flag(s) and deleted {detections:,} detection row(s)")
        logging.info(f"Re-run with: python pii_test/run_pii_s3.py --lot2"
                     + (f" --ministry {args.ministry}" if args.ministry else ""))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
