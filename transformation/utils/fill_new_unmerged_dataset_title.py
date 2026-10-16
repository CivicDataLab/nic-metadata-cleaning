#!/usr/bin/env python3
"""
Fill new_unmerged_dataset_title on the three Dublin Core lots.

  dublin_core_metadata (lot 1), dublin_core_remaining (lot 2), dublin_core_lot3 (lot 3)

The column is the dataset's own title, cleaned. It is the Title as it is, except
on the rows listed in data/new_unmerged_dataset_title_changes.csv (one row per
changed dataset: lot, Identifier[UUID], Title, the new title and why):

  short title        the Title has three words or fewer (counted on whitespace,
                     so file names like Statistics_April_2021 count as one) and
                     the dataset is in no collection: a descriptive title
                     written from the catalog, department and description
  collection format  the dataset's collection has such a member: every member of
                     that collection gets a title in one shared pattern
  spelling           a misspelt word corrected, nothing else touched

Title and new_title (the merged dataset's name) are not changed. The column is
added if a table does not have it yet. Re-running rewrites it from Title and
the CSV, so a row whose change is taken out of the CSV goes back to its Title.

Each table is filled in one transaction and checked before the commit: every
row filled, every CSV row matched on UUID with the Title it was written for,
every other row equal to its Title, no other column changed. No snapshot is
written.

Usage:
  python3 fill_new_unmerged_dataset_title.py --dry-run
  python3 fill_new_unmerged_dataset_title.py
"""

import argparse
import os
import sys

import duckdb

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(REPO, "transformation", "metadata.db")
CHANGES = os.path.join(REPO, "data", "new_unmerged_dataset_title_changes.csv")
COL = "new_unmerged_dataset_title"
LOTS = {"1": "dublin_core_metadata", "2": "dublin_core_remaining", "3": "dublin_core_lot3"}
UUID, TITLE = '"Identifier[UUID]"', '"Title"'


def fill(con, lot: str, table: str, dry_run: bool) -> None:
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    listed, matched, stale, no_uuid = con.execute(f"""
        SELECT (SELECT count(*) FROM changes WHERE lot = ?),
               count(*) FILTER (WHERE c.uuid IS NOT NULL),
               count(*) FILTER (WHERE c.uuid IS NOT NULL AND c.title IS DISTINCT FROM t.{TITLE}),
               count(*) FILTER (WHERE t.{UUID} IS NULL)
        FROM {table} t LEFT JOIN changes c ON c.lot = ? AND c.uuid = t.{UUID}""", [lot, lot]).fetchone()
    unmatched = con.execute(f"""SELECT count(*) FROM changes c WHERE c.lot = ?
        AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{UUID} = c.uuid)""", [lot]).fetchone()[0]
    print(f"{table}: {n} rows; {listed} changes listed, {matched} rows matched "
          f"({n - matched} keep their Title)")
    if stale or unmatched or no_uuid:
        sys.exit(f"  {stale} listed rows have a different Title now, {unmatched} match no row, "
                 f"{no_uuid} table rows have no UUID - nothing written")
    if dry_run:
        return
    if COL not in cols:
        # DuckDB cannot UPDATE a table altered in the same transaction: add, then fill.
        con.execute(f"ALTER TABLE {table} ADD COLUMN {COL} VARCHAR")
        before = con.execute(f"SELECT bit_xor(hash(t)) FROM (SELECT * EXCLUDE ({COL}) FROM {table}) t").fetchone()[0]
        print(f"  column {COL} added")
    else:
        before = con.execute(f"SELECT bit_xor(hash(t)) FROM (SELECT * EXCLUDE ({COL}) FROM {table}) t").fetchone()[0]
    con.execute("BEGIN")
    try:
        con.execute(f"UPDATE {table} SET {COL} = {TITLE}")
        con.execute(f"""UPDATE {table} t SET {COL} = c.new_title FROM changes c
                        WHERE c.lot = ? AND c.uuid = t.{UUID}""", [lot])
        filled, changed, wrong = con.execute(f"""
            SELECT count(t.{COL}), count(*) FILTER (WHERE t.{COL} IS DISTINCT FROM t.{TITLE}),
                   count(*) FILTER (WHERE t.{COL} IS DISTINCT FROM coalesce(c.new_title, t.{TITLE}))
            FROM {table} t LEFT JOIN changes c ON c.lot = ? AND c.uuid = t.{UUID}""", [lot]).fetchone()
        after = con.execute(f"SELECT bit_xor(hash(t)) FROM (SELECT * EXCLUDE ({COL}) FROM {table}) t").fetchone()[0]
        assert filled == n, (filled, n)
        assert wrong == 0 and changed == matched, (wrong, changed, matched)
        assert after == before, "another column changed"
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    print(f"  {COL}: {filled} rows filled, {changed} differ from Title; other columns unchanged")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--changes", default=CHANGES)
    ap.add_argument("--dry-run", action="store_true", help="check the CSV against the tables, write nothing")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    con.execute(f"""CREATE TEMP TABLE changes AS
        SELECT CAST(lot AS VARCHAR) AS lot, "Identifier[UUID]" AS uuid, "Title" AS title,
               {COL} AS new_title, change
        FROM read_csv('{args.changes}', all_varchar=true, header=true, quote='"', escape='"',
                      strict_mode=false, null_padding=true)""")
    bad = con.execute("""SELECT count(*) FROM changes WHERE lot NOT IN ('1', '2', '3') OR uuid IS NULL
        OR trim(coalesce(new_title, '')) = '' OR new_title = title""").fetchone()[0]
    dupes = con.execute("SELECT count(*) FROM (SELECT lot, uuid FROM changes GROUP BY 1, 2 HAVING count(*) > 1)").fetchone()[0]
    print(f"{os.path.basename(args.changes)}: {con.execute('SELECT count(*) FROM changes').fetchone()[0]} rows -",
          dict(con.execute("SELECT change, count(*) FROM changes GROUP BY 1 ORDER BY 2 DESC").fetchall()))
    if bad or dupes:
        sys.exit(f"{bad} rows without lot / UUID / a new title that differs, {dupes} UUIDs listed twice - nothing written")
    for lot, table in LOTS.items():
        fill(con, lot, table, args.dry_run)
    if not args.dry_run:
        con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
