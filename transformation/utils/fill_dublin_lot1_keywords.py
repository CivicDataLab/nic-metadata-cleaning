"""
Fill dublin_core_metadata keywords from Sheet1 of
"generic and sponsored keywords for lot 1(2).xlsx", matched on nid.

  column D "hvd keywords"        -> "Subject[keyword]" on every row
  column E "hvd spons keywords"  -> "Subject[sponsored_keyword]" on the rows
                                    whose nid is listed in column B "HVD nids"

Column A holds every lot 1 nid; column B repeats the nid on the HVD rows and is
blank elsewhere. Column E is filled on every sheet row, but sponsored keywords
apply only to the nids in column B: Subject[sponsored_keyword] on the other rows
is not touched and keeps what the table already has.

Values are trimmed and otherwise written as the sheet has them (", "-separated).
Re-running overwrites with the same values.

Usage:
  python fill_dublin_lot1_keywords.py --dry-run
  python fill_dublin_lot1_keywords.py
"""
import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
WORKBOOK = str(Path.home() / "Downloads" / "generic and sponsored keywords for lot 1(2).xlsx")
TABLE = "dublin_core_metadata"
KEYWORD = "Subject[keyword]"
SPONSORED = "Subject[sponsored_keyword]"


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
    # nids come out of Excel as floats in some saves ("88904.0")
    con.execute(f"""
        CREATE TEMP TABLE kw AS
        SELECT regexp_replace(trim(nid), '\\.0+$', '')                        AS nid,
               regexp_replace(trim(coalesce("HVD nids", '')), '\\.0+$', '')  AS hvd_nid,
               trim(coalesce("hvd keywords", ''))                            AS keywords,
               trim(coalesce("hvd spons keywords", ''))                      AS sponsored
        FROM read_xlsx('{args.workbook}', sheet = 'Sheet1', all_varchar = true, header = true)
        WHERE trim(coalesce(nid, '')) <> ''""")
    sheet, distinct, hvd, off_row, no_kw, no_spons = con.execute("""
        SELECT count(*), count(DISTINCT nid), count(*) FILTER (WHERE hvd_nid <> ''),
               count(*) FILTER (WHERE hvd_nid <> '' AND hvd_nid <> nid),
               count(*) FILTER (WHERE keywords = ''),
               count(*) FILTER (WHERE hvd_nid <> '' AND sponsored = '')
        FROM kw""").fetchone()
    assert sheet == distinct, f"sheet nids are not unique ({sheet} rows, {distinct} nids)"
    assert off_row == 0, f"{off_row} HVD nids sit on another nid's row"
    assert no_kw == 0, f"{no_kw} sheet rows have no keywords"
    assert no_spons == 0, f"{no_spons} HVD rows have no sponsored keywords"

    rows, = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()
    matched, = con.execute(f"SELECT count(*) FROM {TABLE} t JOIN kw USING (nid)").fetchone()
    missing, = con.execute(f"SELECT count(*) FROM kw WHERE nid NOT IN (SELECT nid FROM {TABLE} WHERE nid IS NOT NULL)").fetchone()
    kw_change, spons_change = con.execute(f"""
        SELECT count(*) FILTER (WHERE t."{KEYWORD}" IS DISTINCT FROM kw.keywords),
               count(*) FILTER (WHERE kw.hvd_nid <> '' AND t."{SPONSORED}" IS DISTINCT FROM kw.sponsored)
        FROM {TABLE} t JOIN kw USING (nid)""").fetchone()
    print(f"Sheet1: {sheet} nids, {hvd} of them HVD. Table: {rows} rows, {matched} matched on nid.")
    print(f"{KEYWORD}: {kw_change} rows change. {SPONSORED}: {spons_change} of the {hvd} HVD rows change.")
    assert missing == 0, f"{missing} sheet nids are not in the table"
    assert matched == rows, f"{rows - matched} table rows are not in the sheet"
    if args.dry_run:
        print("Dry run: nothing written.")
        return

    # the rows outside column B must come out exactly as they went in
    untouched = f"""SELECT count(*), bit_xor(hash(nid, "{SPONSORED}")) FROM {TABLE}
                    WHERE nid NOT IN (SELECT nid FROM kw WHERE hvd_nid <> '')"""
    before = con.execute(untouched).fetchone()
    con.execute("BEGIN")
    con.execute(f'UPDATE {TABLE} AS t SET "{KEYWORD}" = kw.keywords FROM kw WHERE t.nid = kw.nid')
    con.execute(f"""UPDATE {TABLE} AS t SET "{SPONSORED}" = kw.sponsored FROM kw
                    WHERE t.nid = kw.nid AND kw.hvd_nid <> ''""")
    total, kw_ok, spons_ok = con.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE t."{KEYWORD}" = kw.keywords),
               count(*) FILTER (WHERE kw.hvd_nid <> '' AND t."{SPONSORED}" = kw.sponsored)
        FROM {TABLE} t LEFT JOIN kw USING (nid)""").fetchone()
    if (total, kw_ok, spons_ok) != (rows, sheet, hvd) or con.execute(untouched).fetchone() != before:
        con.execute("ROLLBACK")
        raise SystemExit(f"Rolled back: {kw_ok} of {sheet} keyword rows and {spons_ok} of {hvd} "
                         f"sponsored rows match the sheet, {total} rows (was {rows}).")
    con.execute("COMMIT")
    print(f"Wrote {TABLE}.{KEYWORD} on {kw_ok} rows and {SPONSORED} on {spons_ok} rows "
          f"({rows - hvd} rows outside column B left as they were).")


if __name__ == "__main__":
    main()
