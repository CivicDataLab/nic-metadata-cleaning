#!/usr/bin/env python3
r"""Derive `Temporal Coverage` for dublin_core_metadata from dataset titles.

This table keeps a single Temporal Coverage column, so a range has to be
encoded into one value. It already does that as

    start:2018;end:2019

and that shape is kept. Every reader of this column extracts with
`start:(\d{4})` / `end:(\d{4})` -- hvd_scoring/hvd_score.py, transformation/
utils/hvd_score_collections.py -- so widening the endpoints to full dates

    start:2018-04-01;end:2019-03-31

adds day precision without changing a single downstream call site: those
regexes still read 2018 and 2019 off the front of each endpoint. Every row is
re-derived, because the existing year-only values are both imprecise and, on
the fiscal-year patterns, wrong (FY 2018-19 is stored as start:2017;end:2019).

Titles, not the Year/Month/Financial_Year/Quarter columns, are the input: those
were extracted from a truncated Temporal_Raw and disagree with the title on the
ranged patterns ("for Jan 2013" for a title reading "Jan 2013 to Mar 2013").

Fiscal years are Apr-Mar: FY 2018-19 is 2018-04-01 .. 2019-03-31, and a month
named inside one resolves to the calendar year that month actually falls in
(January-2019-20 is January 2020). "upto <month>" is cumulative from the fiscal
year's April; "for <month>" is that month alone.

Two-stage by design: the derivation lands in a staging table carrying the
matched pattern, so it can be sampled per pattern before anything is written,
and the write itself is a single join UPDATE rather than 200k statements.

    python transformation/temporal/temporal_coverage_metadata.py            # stage + report
    python transformation/temporal/temporal_coverage_metadata.py --apply    # stage + write
"""

from __future__ import annotations

import argparse
import calendar
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = str(Path(__file__).resolve().parents[1] / "metadata.db")
TABLE = "dublin_core_metadata"
KEY = "nid"
STAGE = "temporal_derived_metadata"

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MON = ("(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        "jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_YR = r"(?:1[89]|20)\d{2}"
# \d{4} first: alternation is leftmost-first, and matching "2009-2010" as
# tail "20" made _fy_end() read it as FY 2009-2020.
_FY = rf"({_YR})\s*[-–/]\s*(\d{{4}}|\d{{2}})(?!\d)"

MIN_YEAR, MAX_YEAR = 1800, 2035


def _fy_end(start: int, tail: str) -> int:
    """'2018-19' -> 2019, '2011-2012' -> 2012, '1999-00' -> 2000."""
    if len(tail) == 4:
        return int(tail)
    end = (start // 100) * 100 + int(tail)
    if end < start:
        end += 100          # century rollover: 1999-00
    return end


def _eom(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _cal_year(month: int, fy_start: int, fy_end: int) -> int:
    """Which calendar year a month named inside an Apr-Mar fiscal year sits in."""
    return fy_start if month >= 4 else fy_end


def _plausible(*years: int) -> bool:
    return all(MIN_YEAR <= y <= MAX_YEAR for y in years)


# --- patterns, first match wins ---------------------------------------------
# Ordered most specific first: a title matching "April to December during
# 2016-17" also matches the bare-fiscal-year rule, and only the first reading
# is right.

_P_QUARTER = re.compile(
    rf"quarter\s*[1-4]\s*:?\s*({_MON})\s*({_YR})\s*(?:to|-|–)\s*({_MON})\s*({_YR})")
_P_MON_Y_RANGE = re.compile(
    rf"({_MON})\s*[-,\s]\s*({_YR})\s*(?:to|through|–)\s*({_MON})\s*[-,\s]\s*({_YR})")
_P_MON_RANGE_FY = re.compile(
    rf"({_MON})\s*(?:to|-|–)\s*({_MON})\s+(?:during|of|in|for)?\s*{_FY}")
_P_FY_PAIR_MONTHS = re.compile(
    rf"{_FY}\s*(?:&|and|to|vs\.?|,)\s*{_FY}.*?\(\s*({_MON})\s*(?:to|-|–)\s*({_MON})\s*\)")
_P_FY_PAIR = re.compile(rf"{_FY}\s*(?:&|and|to|vs\.?|,)\s*{_FY}")
_P_UPTO_MON_FY = re.compile(rf"up\s?to\s+({_MON})\s*[-,\s]\s*{_FY}")
_P_FOR_MON_FY = re.compile(rf"({_MON})\s*[-,\s]\s*{_FY}")
_P_UPTO_MON_Y = re.compile(rf"up\s?to\s+({_MON})\s*[-,\s]\s*({_YR})")
_P_MON_Y = re.compile(rf"({_MON})\s*[-,\s]\s*({_YR})")
_P_FY = re.compile(_FY)
_P_Y_RANGE = re.compile(rf"({_YR})\s*(?:to|and|&|-|–)\s*({_YR})")
_P_Y = re.compile(_YR)


def parse_title(title: str):
    """(start_date, end_date, pattern) or (None, None, None)."""
    if not title:
        return None, None, None
    t = re.sub(r"\s+", " ", str(title)).strip().lower()

    m = _P_QUARTER.search(t)
    if m:
        m1, y1, m2, y2 = MONTHS[m.group(1)], int(m.group(2)), MONTHS[m.group(3)], int(m.group(4))
        if _plausible(y1, y2):
            return date(y1, m1, 1), _eom(y2, m2), "quarter_month_range"

    m = _P_MON_Y_RANGE.search(t)
    if m:
        m1, y1, m2, y2 = MONTHS[m.group(1)], int(m.group(2)), MONTHS[m.group(3)], int(m.group(4))
        if _plausible(y1, y2):
            return date(y1, m1, 1), _eom(y2, m2), "month_year_range"

    m = _P_MON_RANGE_FY.search(t)
    if m:
        m1, m2 = MONTHS[m.group(1)], MONTHS[m.group(2)]
        fs, fe = int(m.group(3)), _fy_end(int(m.group(3)), m.group(4))
        if _plausible(fs, fe):
            return (date(_cal_year(m1, fs, fe), m1, 1),
                    _eom(_cal_year(m2, fs, fe), m2), "month_range_in_fy")

    # Two fiscal years compared over a sub-year window, e.g.
    # "... for the year 2016-17 and 2015-16 (April to December)".
    m = _P_FY_PAIR_MONTHS.search(t)
    if m:
        a_s, a_e = int(m.group(1)), _fy_end(int(m.group(1)), m.group(2))
        b_s, b_e = int(m.group(3)), _fy_end(int(m.group(3)), m.group(4))
        m1, m2 = MONTHS[m.group(5)], MONTHS[m.group(6)]
        lo_s, lo_e = min((a_s, a_e), (b_s, b_e))
        hi_s, hi_e = max((a_s, a_e), (b_s, b_e))
        if _plausible(a_s, a_e, b_s, b_e):
            return (date(_cal_year(m1, lo_s, lo_e), m1, 1),
                    _eom(_cal_year(m2, hi_s, hi_e), m2), "fy_pair_month_window")

    m = _P_FY_PAIR.search(t)
    if m:
        a_s, a_e = int(m.group(1)), _fy_end(int(m.group(1)), m.group(2))
        b_s, b_e = int(m.group(3)), _fy_end(int(m.group(3)), m.group(4))
        if _plausible(a_s, a_e, b_s, b_e):
            # Titles list the pair in either order ("2018-19 & 2017-18",
            # "2012-2013 to 2011-2012"), so the span is the union, not g1..g2.
            return date(min(a_s, b_s), 4, 1), date(max(a_e, b_e), 3, 31), "fy_pair"

    m = _P_UPTO_MON_FY.search(t)
    if m:
        mo = MONTHS[m.group(1)]
        fs, fe = int(m.group(2)), _fy_end(int(m.group(2)), m.group(3))
        if _plausible(fs, fe):
            # Cumulative: the fiscal year to date, not the month alone.
            return date(fs, 4, 1), _eom(_cal_year(mo, fs, fe), mo), "upto_month_fy"

    m = _P_FOR_MON_FY.search(t)
    if m:
        mo = MONTHS[m.group(1)]
        fs, fe = int(m.group(2)), _fy_end(int(m.group(2)), m.group(3))
        if _plausible(fs, fe):
            y = _cal_year(mo, fs, fe)
            return date(y, mo, 1), _eom(y, mo), "for_month_fy"

    m = _P_UPTO_MON_Y.search(t)
    if m:
        mo, y = MONTHS[m.group(1)], int(m.group(2))
        if _plausible(y):
            # Cumulative from the April that opened the fiscal year this month
            # falls in, matching the "upto <month>-<FY>" reading.
            return date(y if mo >= 4 else y - 1, 4, 1), _eom(y, mo), "upto_month_year"

    m = _P_MON_Y.search(t)
    if m:
        mo, y = MONTHS[m.group(1)], int(m.group(2))
        if _plausible(y):
            return date(y, mo, 1), _eom(y, mo), "month_year"

    m = _P_FY.search(t)
    if m:
        fs, fe = int(m.group(1)), _fy_end(int(m.group(1)), m.group(2))
        if _plausible(fs, fe):
            return date(fs, 4, 1), date(fe, 3, 31), "fiscal_year"

    m = _P_Y_RANGE.search(t)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        if _plausible(y1, y2):
            return date(min(y1, y2), 1, 1), date(max(y1, y2), 12, 31), "year_range"

    m = _P_Y.search(t)
    if m:
        y = int(m.group(0))
        if _plausible(y):
            return date(y, 1, 1), date(y, 12, 31), "year"

    return None, None, None


def build(con, limit=None):
    sql = f'SELECT {KEY}, "Title" FROM "{TABLE}"'
    if limit:
        sql += f" LIMIT {limit}"
    rows = con.execute(sql).fetchall()
    out = []
    for nid, title in rows:
        s, e, pat = parse_title(title)
        if s and e and s > e:
            s, e, pat = e, s, pat + "|reversed"
        out.append((nid, title, pat,
                    s.isoformat() if s else None,
                    e.isoformat() if e else None,
                    f"start:{s.isoformat()};end:{e.isoformat()}" if s and e else None))
    return out


FILE_STAGE = "temporal_derived_files"


def merge_file_results(con):
    """Fold in the content-scan results, which live in their own table.

    temporal_coverage_from_files.py takes ~25 minutes over 300 GB of AHS
    schedules. Staging it separately means re-deriving titles -- cheap, and done
    every time the parser changes -- never costs that run.
    """
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}
    if FILE_STAGE not in tables:
        return 0
    con.execute(f"""
        UPDATE {STAGE} AS d SET
            matched_pattern = 'file_contents',
            start_date = f.start_date,
            end_date = f.end_date,
            coverage = f.coverage
        FROM {FILE_STAGE} AS f
        WHERE d.{KEY} = f.{KEY} AND d.coverage IS NULL
    """)
    return con.execute(f"SELECT count(*) FROM {FILE_STAGE}").fetchone()[0]


def stage(con, rows):
    """Bulk-load the derivation; executemany here is 200k round-trips and hangs."""
    frame = pd.DataFrame(
        rows, columns=[KEY, "title", "matched_pattern",
                       "start_date", "end_date", "coverage"])
    frame["start_date"] = pd.to_datetime(frame["start_date"]).dt.date
    frame["end_date"] = pd.to_datetime(frame["end_date"]).dt.date
    con.register("_staged", frame)
    con.execute(f"DROP TABLE IF EXISTS {STAGE}")
    con.execute(f"CREATE TABLE {STAGE} AS SELECT * FROM _staged")
    con.unregister("_staged")


def apply_update(con):
    con.execute(f"""
        UPDATE "{TABLE}" AS t
        SET "Temporal Coverage" = d.coverage
        FROM {STAGE} AS d
        WHERE t.{KEY} = d.{KEY} AND d.coverage IS NOT NULL
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reuse-stage", action="store_true",
                    help="apply the existing staging table without re-deriving")
    ap.add_argument("--apply", action="store_true",
                    help="write the staged intervals onto Temporal Coverage")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=False)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables()").fetchall()}
    if args.reuse_stage and STAGE in tables:
        print(f"reusing existing {STAGE}")
        tot = con.execute(f"SELECT count(*) FROM {STAGE}").fetchone()[0]
        rows = None
    else:
        rows = build(con, args.limit)
        stage(con, rows)
        n = merge_file_results(con)
        if n:
            print(f"merged {n} rows from {FILE_STAGE}")
        tot = len(rows)
    hit = con.execute(
        f"SELECT count(coverage) FROM {STAGE}").fetchone()[0]
    print(f"{TABLE}: {tot} rows, {hit} derived ({hit * 100 / tot:.2f}%), {tot - hit} unresolved")
    print("\nby pattern:")
    for pat, n in con.execute(
            f"SELECT coalesce(matched_pattern,'(none)'), count(*) c FROM {STAGE} "
            "GROUP BY 1 ORDER BY c DESC").fetchall():
        print(f"  {n:7d}  {pat}")
    bad = con.execute(
        f"SELECT count(*) FROM {STAGE} WHERE start_date > end_date").fetchone()[0]
    print(f"\ninverted after sort: {bad}")

    if args.apply:
        apply_update(con)
        con.execute("CHECKPOINT")
        print("\napplied.")
        print(con.execute(f'''SELECT count(*) total,
            count(*) FILTER (WHERE "Temporal Coverage" LIKE 'start:____-__-__;end:____-__-__') dated,
            count(*) FILTER (WHERE "Temporal Coverage" IS NULL
                             OR trim("Temporal Coverage")='') blank
            FROM "{TABLE}"''').fetchall())
    con.close()


if __name__ == "__main__":
    main()
