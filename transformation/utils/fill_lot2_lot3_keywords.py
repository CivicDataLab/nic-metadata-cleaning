"""
Load Subject[keyword] and Subject[sponsored_keyword] for lot 2 and lot 3 from
the keyword workbooks of 2026-10-14, matched on nid.

  lot 2  ~/Downloads/dublin_core_Lot2 keywords.xlsx, sheet Sheet1 (the
         "Sponsored keywords for 11601 out of 117721 ..." export; banner in
         row 1, headers in row 2): Subject[keyword] and
         Subject[sponsored_keyword] -> dublin_core_remaining
  lot 3  ~/Downloads/keywords_LOT3_.xlsx, sheet Sheet4: keywords ->
         Subject[keyword]; sponsored keywords -> Subject[sponsored_keyword] on
         the rows with an "HVD nid" (the sheet shows 0 on the others)
         -> dublin_core_lot3

Both sheets cover every row of their lot, so sponsored keywords are replaced
outright: a row the sheet gives none is set NULL. Cleaned_Data / Sheet2
(lot 2) and checkfor / Sheet1 (lot 3) are working sheets and are not read.
Subject[sponsored_keyword] is added to dublin_core_lot3 (VARCHAR) if missing.
Values are trimmed and otherwise written as the sheets have them.

Usage:
  python fill_lot2_lot3_keywords.py --dry-run
  python fill_lot2_lot3_keywords.py
"""
import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
DOWNLOADS = Path.home() / "Downloads"
LOT2_BOOK = str(DOWNLOADS / "dublin_core_Lot2 keywords.xlsx")
LOT3_BOOK = str(DOWNLOADS / "keywords_LOT3_.xlsx")
KW, SP = "Subject[keyword]", "Subject[sponsored_keyword]"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    con.execute("SET memory_limit = '2GB'; SET threads = 2; LOAD excel")
    # Lot 2 Sheet1: row 1 is a banner, row 2 the headers; D/E are the two
    # keyword columns and L is nid (checked against the row-2 headers below).
    head = con.execute(f"""SELECT D, E, L FROM read_xlsx('{LOT2_BOOK}', sheet = 'Sheet1',
                           all_varchar = true, header = false, range = 'A2:L2')""").fetchone()
    if head != (KW, SP, "nid"):
        raise SystemExit(f"lot 2 Sheet1 row 2 has {head} in D/E/L, expected {(KW, SP, 'nid')}")
    con.execute(f"""
        CREATE TEMP TABLE kw2 AS
        SELECT trim(L) AS nid, nullif(trim(D), '') AS kw, nullif(trim(E), '') AS sp
        FROM read_xlsx('{LOT2_BOOK}', sheet = 'Sheet1', all_varchar = true, header = false,
                       range = 'A3:L200000')
        WHERE trim(coalesce(L, '')) <> ''""")
    con.execute(f"""
        CREATE TEMP TABLE kw3 AS
        SELECT trim(nid) AS nid, nullif(trim(keywords), '') AS kw,
               CASE WHEN trim(coalesce("HVD nid", '')) <> ''
                    THEN nullif(nullif(trim("sponsored keywords"), ''), '0') END AS sp
        FROM read_xlsx('{LOT3_BOOK}', sheet = 'Sheet4', all_varchar = true, header = true)
        WHERE trim(coalesce(nid, '')) <> ''""")

    for src, table in (("kw2", "dublin_core_remaining"), ("kw3", "dublin_core_lot3")):
        dups = con.execute(f"SELECT count(*) - count(DISTINCT nid) FROM {src}").fetchone()[0]
        if dups:
            raise SystemExit(f"{src}: {dups} repeated nids in the sheet - not writing")
        has_sp = con.execute(f"""SELECT count(*) FROM information_schema.columns
                                 WHERE table_name = '{table}' AND column_name = '{SP}'""").fetchone()[0]
        n, kw, sp, unmatched, rows, hit = con.execute(f"""
            SELECT count(*), count(kw), count(sp),
                   count(*) FILTER (WHERE nid NOT IN (SELECT CAST(nid AS VARCHAR) FROM {table} WHERE nid IS NOT NULL)),
                   (SELECT count(*) FROM {table}),
                   (SELECT count(*) FROM {table} WHERE CAST(nid AS VARCHAR) IN (SELECT nid FROM {src}))
            FROM {src}""").fetchone()
        print(f"{table}: sheet {n} rows ({kw} keywords, {sp} sponsored), {unmatched} not in the table; "
              f"{hit} of {rows} table rows matched" + ("" if has_sp else f"; adds {SP}"))
        if args.dry_run:
            continue
        if not has_sp:
            con.execute(f'ALTER TABLE {table} ADD COLUMN "{SP}" VARCHAR')
        con.execute(f"""UPDATE {table} t SET "{KW}" = s.kw, "{SP}" = s.sp
                        FROM {src} s WHERE s.nid = CAST(t.nid AS VARCHAR)""")
        print("  now filled: " + ", ".join(f"{c} {v}" for c, v in zip(
            (KW, SP), con.execute(f'SELECT count("{KW}"), count("{SP}") FROM {table}').fetchone())))
    if not args.dry_run:
        con.execute("CHECKPOINT")
    con.close()


if __name__ == "__main__":
    main()
