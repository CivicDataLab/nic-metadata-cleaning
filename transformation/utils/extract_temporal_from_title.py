"""
Extract temporal components (year / fiscal year, month, quarter) from each
dataset Title in the `collection` table and write them back as columns on the
same table.

Columns added (idempotent — ADD COLUMN IF NOT EXISTS):
    Temporal_Raw  VARCHAR  the matched temporal substring (recoverable fallback)
    Year          INTEGER  a single calendar year (e.g. 2013) when no range
    Fiscal_Year   VARCHAR  a year-range (e.g. 2015-16, 2009-2010) when present
    Month         VARCHAR  the (start) month, full name (e.g. April)
    Quarter       INTEGER  the quarter number when "Quarter N" is present

The temporal substring is located with parse_title_components() (the same
parser dataset_vertical_merge.py uses), then decomposed into structured fields.

NOTE: the `collection` table is (re)created by transformation/import_csv.py
(DROP + CREATE TABLE ... AS SELECT). If you re-import that table, re-run this
script afterwards — same caveat as import_spatial_coverage.py.

Usage:
    python extract_temporal_from_title.py            # apply to the DB
    python extract_temporal_from_title.py --dry-run  # parse + sample, no write
"""

import argparse
import re
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # title_components.py (sibling)
sys.path.insert(0, str(HERE.parent))     # dataset_merge.py (parent)

from title_components import parse_title_components  # noqa: E402
from dataset_merge import MONTH_RE                   # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "collection"

# Only mergeable datasets get temporal columns. Anything flagged
# "non-mergeable" in merge_method is skipped (left NULL). Hyphen/space-tolerant.
MERGEABLE_SQL = "COALESCE(lower(merge_method), '') NOT LIKE '%non%merge%'"

# ── month normalisation ──────────────────────────────────────────────────────
_FULL_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
# abbrev (lower, first 3) -> full name
_MONTH_LOOKUP = {m[:3].lower(): m for m in _FULL_MONTHS}

_MONTH_FINDER = re.compile(MONTH_RE, re.I)
# year-range: 2015-16, 2009-2010 (hyphen or en-dash)
_RANGE_FINDER = re.compile(r"\b((?:18|19|20)\d{2})\s*[-–]\s*(\d{2,4})\b")
# any 4-digit year
_YEAR_FINDER = re.compile(r"\b(?:18|19|20)\d{2}\b")
_QUARTER_FINDER = re.compile(r"\bQuarter\s+(\d+)", re.I)
# year range expressed with an en-dash or "to" anywhere in the title, e.g.
# "2008–2010", "1971 to 2012", "1981–85 to 2007–2012". title_components only
# keeps the trailing bare year for these, so we recover the range here.
_TITLE_RANGE_FINDER = re.compile(
    r"\b((?:18|19|20)\d{2})\s*(?:[-–]|to)\s*((?:18|19|20)?\d{2,4})\b", re.I
)


def _normalize_month(tok: str) -> str:
    return _MONTH_LOOKUP.get(tok[:3].lower(), tok.title())


def _normalize_range(y1: str, y2: str) -> str:
    """Render a range as 'YYYY-YY' / 'YYYY-YYYY' from captured parts."""
    return f"{y1}-{y2}"


def decompose(time_period: str) -> dict:
    """Decompose a temporal substring into year/fiscal_year/month/quarter."""
    out = {"Year": None, "Fiscal_Year": None, "Month": None, "Quarter": None}
    if not time_period:
        return out

    tp = time_period

    # quarter
    qm = _QUARTER_FINDER.search(tp)
    if qm:
        out["Quarter"] = int(qm.group(1))

    # month (start month if a range)
    mm = _MONTH_FINDER.search(tp)
    if mm:
        out["Month"] = _normalize_month(mm.group(0))

    # year vs fiscal year
    ranges = _RANGE_FINDER.findall(tp)
    if ranges:
        y1, y2 = ranges[0]
        out["Fiscal_Year"] = _normalize_range(y1, y2)
    else:
        # collect bare single years
        years = _YEAR_FINDER.findall(tp)
        uniq = sorted(set(years))
        if len(uniq) >= 2 and " to " in tp:
            # "April 2009 to March 2010" -> fiscal year expressed as months
            out["Fiscal_Year"] = _normalize_range(uniq[0], uniq[-1])
        elif len(uniq) == 1:
            out["Year"] = int(uniq[0])
        elif len(uniq) >= 2:
            # disjoint single years (e.g. "for 2014 & 2013") without a range
            # form — keep the earliest as Year; raw column preserves the rest.
            out["Year"] = int(uniq[0])

    return out


def extract(title: str) -> dict:
    tp = parse_title_components(title or "")["time_period"]
    row = decompose(tp)
    row["Temporal_Raw"] = tp

    # Recover en-dash / "to" year ranges that title_components reduced to a
    # bare trailing year (e.g. "2008–2010" -> tp "2010"). Only upgrade rows the
    # parser already anchored to a single Year, so title noise can't introduce
    # spurious ranges where there was no temporal phrase at all.
    if row["Year"] is not None and row["Fiscal_Year"] is None and title:
        m = _TITLE_RANGE_FINDER.search(title)
        if m:
            row["Fiscal_Year"] = _normalize_range(m.group(1), m.group(2))
            row["Year"] = None
            row["Temporal_Raw"] = m.group(0)

    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + print samples/coverage, do not write")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)

    rows = con.execute(
        f'SELECT nid, Title FROM "{TABLE}" '
        f"WHERE nid IS NOT NULL AND {MERGEABLE_SQL}"
    ).fetchall()
    print(f"Read {len(rows)} mergeable rows from {TABLE} "
          f"(non-mergeable rows skipped)")

    records = []
    for nid, title in rows:
        r = extract(title)
        records.append((
            nid, r["Temporal_Raw"], r["Year"],
            r["Fiscal_Year"], r["Month"], r["Quarter"],
        ))

    # coverage summary
    def _cov(idx):
        return sum(1 for r in records if r[idx] is not None)
    print(f"  Temporal_Raw: {_cov(1):>7}   Year: {_cov(2):>7}   "
          f"Fiscal_Year: {_cov(3):>7}   Month: {_cov(4):>7}   "
          f"Quarter: {_cov(5):>7}")

    if args.dry_run:
        print("\n-- sample (first 20 with a temporal match) --")
        shown = 0
        for nid, title in rows:
            r = extract(title)
            if r["Temporal_Raw"] is None:
                continue
            print(f"  {nid} | Y={r['Year']} FY={r['Fiscal_Year']} "
                  f"M={r['Month']} Q={r['Quarter']} | {title[:80]}")
            shown += 1
            if shown >= 20:
                break
        con.close()
        return

    # add columns (idempotent)
    for col, typ in [
        ("Temporal_Raw", "VARCHAR"), ("Year", "INTEGER"),
        ("Fiscal_Year", "VARCHAR"), ("Month", "VARCHAR"),
        ("Quarter", "INTEGER"),
    ]:
        con.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN IF NOT EXISTS "{col}" {typ}')

    import pandas as pd
    upd = pd.DataFrame(records, columns=[
        "nid", "Temporal_Raw", "Year", "Fiscal_Year", "Month", "Quarter",
    ])
    upd["Year"] = upd["Year"].astype("Int64")
    upd["Quarter"] = upd["Quarter"].astype("Int64")

    con.register("temporal_updates", upd)
    con.execute(f"""
        UPDATE "{TABLE}" AS d
        SET "Temporal_Raw" = u."Temporal_Raw",
            "Year"         = u."Year",
            "Fiscal_Year"  = u."Fiscal_Year",
            "Month"        = u."Month",
            "Quarter"      = u."Quarter"
        FROM temporal_updates AS u
        WHERE d.nid = u.nid AND {MERGEABLE_SQL.replace("merge_method", 'd.merge_method')}
    """)
    con.unregister("temporal_updates")
    print(f"Updated temporal columns on {TABLE} for {len(records)} rows")
    con.close()


if __name__ == "__main__":
    main()
