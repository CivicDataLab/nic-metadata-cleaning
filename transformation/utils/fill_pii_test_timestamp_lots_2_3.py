"""
Fill pii_tested, pii_detected and pii_test_timestamp on dublin_core_remaining
(lot 2) and dublin_core_lot3 (lot 3) from
~/Downloads/pii_test_timestamps_lots_2_3.csv
(nid, uuid, lot, pii_tested, pii_detected, pii_test_timestamp).

Matched on nid + Identifier[UUID] within the CSV's lot: nid 95489 (same uuid)
sits in both lots with a different timestamp in each, so the lot decides which
one a table gets. A column is added as VARCHAR if the table lacks it, like
dublin_core_metadata's, and the CSV's text (True / False, 2026-10-08T06:47:37)
is written as is. Rows the CSV does not list are left NULL. Re-running
overwrites with the same values.

The DCAT objects and combined tables are copies: afterwards run
  build_dcat_mapping.py --profile remaining
  build_dcat_mapping.py --profile lot3 --materialize
  utils/export_all_lots.py ; utils/export_all_lots.py --dcat

Usage:
  python fill_pii_test_timestamp_lots_2_3.py --dry-run
  python fill_pii_test_timestamp_lots_2_3.py
"""
import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CSV = str(Path.home() / "Downloads" / "pii_test_timestamps_lots_2_3.csv")
COLUMNS = ["pii_tested", "pii_detected", "pii_test_timestamp"]
TABLES = {"2": "dublin_core_remaining", "3": "dublin_core_lot3"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--csv", default=CSV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        con = duckdb.connect(args.db, read_only=args.dry_run)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {args.db} (is it open in DBeaver?): {str(e).splitlines()[0]}")
    con.execute(f"""
        CREATE TEMP TABLE ts AS
        SELECT trim(nid) AS nid, trim(uuid) AS uuid, trim(lot) AS lot,
               {", ".join(f"trim({c}) AS {c}" for c in COLUMNS)}
        FROM read_csv('{args.csv}', all_varchar = true)""")
    dups = con.execute("SELECT count(*) FROM (SELECT 1 FROM ts GROUP BY nid, uuid, lot HAVING count(*) > 1)").fetchone()[0]
    if dups:
        raise SystemExit(f"{dups} nid/uuid/lot keys repeat in the CSV - not writing")
    other = con.execute(f"SELECT count(*) FROM ts WHERE lot NOT IN {tuple(TABLES)}").fetchone()[0]
    if other:
        raise SystemExit(f"{other} CSV rows have a lot other than {', '.join(TABLES)} - not writing")

    for lot, table in TABLES.items():
        have = {r[0] for r in con.execute(f"""SELECT column_name FROM information_schema.columns
                                               WHERE table_name = '{table}'""").fetchall()}
        missing = [c for c in COLUMNS if c not in have]
        match = f"""ts.lot = '{lot}' AND ts.nid = CAST(t.nid AS VARCHAR)
                    AND ts.uuid = t."Identifier[UUID]" """
        csv_rows, unmatched = con.execute(f"""
            SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM {table} t WHERE {match}))
            FROM ts WHERE lot = '{lot}'""").fetchone()
        rows, hit = con.execute(f"""
            SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ts WHERE {match}))
            FROM {table} t""").fetchone()
        print(f"Lot {lot} -> {table}: {csv_rows} CSV rows, {unmatched} not in the table; "
              f"{hit} of {rows} table rows are in the CSV, {rows - hit} stay NULL"
              + (f"; adds {', '.join(missing)}" if missing else ""))
        if args.dry_run:
            continue
        for c in missing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {c} VARCHAR")
        con.execute(f"""UPDATE {table} t SET {", ".join(f"{c} = ts.{c}" for c in COLUMNS)}
                        FROM ts WHERE {match}""")
        filled = con.execute(f"SELECT {', '.join(f'count({c})' for c in COLUMNS)} FROM {table}").fetchone()
        print("  now filled: " + ", ".join(f"{c} {n}" for c, n in zip(COLUMNS, filled)))
    if not args.dry_run:
        con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
