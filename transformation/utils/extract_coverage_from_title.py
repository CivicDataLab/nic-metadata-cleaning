"""
Extract SPATIAL and TEMPORAL coverage from each dataset Title in the
`remaining-raw-datasets` table and write them back onto the same table.

Both extractions share a single call to parse_title_components(), which yields
(district, state, time_period) for a title.

Spatial coverage
    Written to a new column  "spatial_coverage"  as  "[District, ]State, India".
    Titles with no recognised location fall back to plain "India" (every dataset
    here is Indian). Coverage is expected to be sparse — most agriculture titles
    are commodity/national and carry no state or district.

Temporal coverage
    Written back into the existing  data_time_period_from / data_time_period_to
    columns, in the ISO timestamp form already stored there
    (YYYY-MM-DDT00:00:00 / ...T23:59:59). Only rows whose title yields a date are
    updated; unparseable rows are left exactly as they are (never nulled).

    Rules:
      * Fiscal-year range "2015-16" / "2005-2009" / "2005-09"
            from = <Y1>-04-01T00:00:00 , to = <endYear>-03-31T23:59:59
        The end year is rebuilt to a full 4-digit year with century rollover:
            "2015-16" -> 2016 , "2009-10" -> 2010 , "1999-00" -> 2000.
      * Open-ended single year, i.e. title says "from <YYYY>" / "since <YYYY>"
            from = <Y>-01-01T00:00:00 , to = NULL  (don't invent an end)
      * Plain single calendar year, e.g. "during 2010"
            from = <Y>-01-01T00:00:00 , to = <Y>-12-31T23:59:59

By default this runs against the Ministry of Agriculture rows only
(--ministry-like '%agri%'); pass --all to process every row.

Usage:
    python extract_coverage_from_title.py --dry-run   # parse + coverage, no write
    python extract_coverage_from_title.py             # back up DB, then write
    python extract_coverage_from_title.py --all       # all ministries
"""

import argparse
import re
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # title_components.py (sibling)
sys.path.insert(0, str(HERE.parent))   # dataset_merge.py (parent)

from title_components import parse_title_components  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "remaining-raw-datasets"

# ── temporal patterns ────────────────────────────────────────────────────────
# year range: 2015-16, 2005-2009, 2005-09 (hyphen or en-dash), anchored on a
# 4-digit start year so we don't match arbitrary 2-digit pairs.
_RANGE_RE = re.compile(r"\b((?:18|19|20)\d{2})\s*[-–]\s*(\d{2,4})\b")
# "from YYYY" / "since YYYY" -> open-ended, only a start date
_OPEN_START_RE = re.compile(r"\b(?:from|since)\s+((?:18|19|20)\d{2})\b", re.I)
# any bare 4-digit year
_YEAR_RE = re.compile(r"\b((?:18|19|20)\d{2})\b")


def _full_end_year(y1: int, y2_raw: str) -> int:
    """Expand a range end token to a full 4-digit year with century rollover.

    "2015" + "16" -> 2016 ; "2009" + "10" -> 2010 ; "1999" + "00" -> 2000 ;
    a 4-digit end token is used as-is.
    """
    if len(y2_raw) == 4:
        return int(y2_raw)
    end = (y1 // 100) * 100 + int(y2_raw)
    if end <= y1:
        end += 100
    return end


def _iso_from(year: int) -> str:
    return f"{year:04d}-04-01T00:00:00"


def extract_temporal(time_period: str, title: str):
    """Return (from_iso, to_iso) or (None, None) if no date is found.

    Searches the parser's time_period first, then falls back to the full title
    so parenthesised ranges like "(2005-09)" are still recovered.
    """
    for text in (time_period, title):
        if not text:
            continue

        m = _RANGE_RE.search(text)
        if m:
            y1 = int(m.group(1))
            end = _full_end_year(y1, m.group(2))
            return (f"{y1:04d}-04-01T00:00:00", f"{end:04d}-03-31T23:59:59")

    # single year — prefer the parser's time_period, else the title
    for text in (time_period, title):
        if not text:
            continue
        ym = _YEAR_RE.search(text)
        if not ym:
            continue
        year = int(ym.group(1))
        # open-ended "from/since YYYY" -> start only, no invented end
        if _OPEN_START_RE.search(title or ""):
            return (f"{year:04d}-01-01T00:00:00", None)
        return (f"{year:04d}-01-01T00:00:00", f"{year:04d}-12-31T23:59:59")

    return (None, None)


# ── spatial ──────────────────────────────────────────────────────────────────
def build_spatial(district, state) -> str:
    # drop empties and a literal "India" the parser sometimes returns as a
    # "state" for "... in India" — the national fallback is appended below.
    parts = [p.title() for p in (district, state)
             if p and p.strip().lower() != "india"]
    parts.append("India")
    return ", ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--ministry-like", default="%agri%",
                    help="lower(ministry_department) LIKE filter (default '%%agri%%')")
    ap.add_argument("--all", action="store_true",
                    help="process every row, ignore --ministry-like")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + print coverage/samples, do not write")
    args = ap.parse_args()

    where = "TRUE" if args.all else "lower(ministry_department) LIKE ?"
    params = [] if args.all else [args.ministry_like]

    con = duckdb.connect(args.db, read_only=args.dry_run)
    rows = con.execute(
        f'SELECT nid, title FROM "{TABLE}" WHERE nid IS NOT NULL AND {where}',
        params,
    ).fetchall()
    print(f"Read {len(rows)} rows from {TABLE} "
          f"({'ALL ministries' if args.all else 'ministry LIKE ' + args.ministry_like})")

    records = []          # (nid, spatial, from_iso, to_iso)
    for nid, title in rows:
        comp = parse_title_components(title or "")
        spatial = build_spatial(comp["district"], comp["state"])
        f_iso, t_iso = extract_temporal(comp["time_period"], title or "")
        records.append((nid, spatial, f_iso, t_iso))

    n_state = sum(1 for r in records if r[1] != "India")
    n_from = sum(1 for r in records if r[2] is not None)
    n_to = sum(1 for r in records if r[3] is not None)
    print(f"  spatial with a state/district: {n_state:>6}   "
          f"temporal from: {n_from:>6}   to: {n_to:>6}")

    if args.dry_run:
        print("\n-- sample (first 25 with a temporal or non-India spatial) --")
        shown = 0
        for (nid, sp, f_iso, t_iso), (_, title) in zip(records, rows):
            if f_iso is None and sp == "India":
                continue
            print(f"  {nid} | {sp} | {f_iso} .. {t_iso} | {title[:70]}")
            shown += 1
            if shown >= 25:
                break
        con.close()
        return

    con.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN IF NOT EXISTS "spatial_coverage" VARCHAR')

    import pandas as pd
    upd = pd.DataFrame(records, columns=["nid", "spatial_coverage",
                                         "from_iso", "to_iso"])
    con.register("cov_updates", upd)

    # spatial: set for every processed row
    con.execute(f"""
        UPDATE "{TABLE}" AS d
        SET spatial_coverage = u.spatial_coverage
        FROM cov_updates AS u
        WHERE d.nid = u.nid
    """)

    # temporal: only rows that yielded a date; never null an existing value.
    con.execute(f"""
        UPDATE "{TABLE}" AS d
        SET data_time_period_from = u.from_iso
        FROM cov_updates AS u
        WHERE d.nid = u.nid AND u.from_iso IS NOT NULL
    """)
    con.execute(f"""
        UPDATE "{TABLE}" AS d
        SET data_time_period_to = u.to_iso
        FROM cov_updates AS u
        WHERE d.nid = u.nid AND u.to_iso IS NOT NULL
    """)
    con.unregister("cov_updates")
    print(f"Wrote spatial_coverage for {len(records)} rows; "
          f"temporal from={n_from}, to={n_to}")
    con.close()


if __name__ == "__main__":
    main()
