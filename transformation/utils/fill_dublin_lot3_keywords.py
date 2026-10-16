"""
Fill dublin_core_lot3."Subject[keyword]" from Sheet1 of keywords_LOT3.xlsx.

Sheet1 columns A:C are nid, New Title, Keywords (the sheet is declared 16,384
columns wide, so only A:C is read - the whole width would take minutes). Keywords
are written exactly as the sheet has them: ';'-separated, like lot 2's
Subject[keyword]; a few rows use ',' or mix the two and are left as given.

Matched on nid. A nid held by two table rows (88731) gives both the same keywords;
the row with no nid stays NULL. The other sheets of the workbook (corrected
keywords, "checkfor") are not used. Re-running overwrites with the same values.

Usage:
  python fill_dublin_lot3_keywords.py --dry-run
  python fill_dublin_lot3_keywords.py
"""
import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
WORKBOOK = str(Path.home() / "Downloads" / "keywords_LOT3.xlsx")
TABLE = "dublin_core_lot3"
COLUMN = "Subject[keyword]"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--workbook", default=WORKBOOK)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        con = duckdb.connect(args.db, read_only=args.dry_run)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {args.db} (is it open in DBeaver?): {str(e).splitlines()[0]}")
    con.execute("LOAD excel")
    con.execute(f"""
        CREATE TEMP TABLE kw AS
        SELECT trim(nid) AS nid, trim(Keywords) AS keywords
        FROM read_xlsx('{args.workbook}', sheet = 'Sheet1', range = 'A1:C40000',
                       all_varchar = true, header = true, stop_at_empty = true)
        WHERE trim(coalesce(nid, '')) <> '' AND trim(coalesce(Keywords, '')) <> ''""")
    sheet, distinct = con.execute("SELECT count(*), count(DISTINCT nid) FROM kw").fetchone()
    assert sheet == distinct, f"sheet nids are not unique ({sheet} rows, {distinct} nids)"
    rows, with_nid, before = con.execute(
        f'SELECT count(*), count(nid), count("{COLUMN}") FROM {TABLE}').fetchone()
    matched, = con.execute(f"SELECT count(*) FROM {TABLE} t JOIN kw USING (nid)").fetchone()
    missing, = con.execute(f"SELECT count(*) FROM kw WHERE nid NOT IN (SELECT nid FROM {TABLE} WHERE nid IS NOT NULL)").fetchone()
    print(f"Sheet1: {sheet} keyword rows. Table: {rows} rows ({with_nid} with a nid), {before} already have keywords.")
    print(f"Table rows matched on nid: {matched}. Sheet nids not in the table: {missing}.")
    assert missing == 0, "some sheet nids are not in the table"
    if args.dry_run:
        print("Dry run: nothing written.")
        return

    con.execute("BEGIN")
    con.execute(f'UPDATE {TABLE} AS t SET "{COLUMN}" = kw.keywords FROM kw WHERE t.nid = kw.nid')
    after, = con.execute(f'SELECT count("{COLUMN}") FROM {TABLE}').fetchone()
    total, = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()
    if after != matched or total != rows:
        con.execute("ROLLBACK")
        raise SystemExit(f"Rolled back: {after} rows have keywords (expected {matched}), {total} rows (was {rows}).")
    con.execute("COMMIT")
    print(f"Wrote {TABLE}.{COLUMN} on {after} of {total} rows ({total - after} left NULL).")


if __name__ == "__main__":
    main()
