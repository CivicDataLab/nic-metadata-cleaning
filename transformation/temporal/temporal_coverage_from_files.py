#!/usr/bin/env python3
r"""Content fallback for the dublin_core_metadata rows whose title has no date.

temporal_coverage_metadata.py derives Temporal Coverage from the title and gets
99.3% of the table. The rest are titles like "Annual Health Survey : Mortality
Schedule of the district Bareilly (Uttar Pradesh)" -- a real dataset with a real
period, just not one stated in its name. Those files are on disk, so the period
is read out of the data itself.

The obvious implementation -- reuse Temporal_script.process_file -- is the wrong
shape here. These are Annual Health Survey household schedules: 130-270 MB CSVs
apiece, and that reader pulls each one fully into a DataFrame. 1,373 of them on
a 7.8 GB box thrashes swap and runs for hours. So the scan is pushed into
DuckDB, which streams:

  1. read the header row with the csv module -- one line, no sniffing -- and
     try Temporal_script's header parser on the column names. The aggregate
     tables here announce their period there and never need a body read;
  2. otherwise ask DuckDB for min/max of the temporal-looking columns, which it
     computes out-of-core over a file it never has to materialise.

Person-level columns are excluded from step 2. The AHS files' headers include
date_of_birth, year_of_birth and year_of_marriage -- respondent attributes, not
the dataset's period. Bounding those yields a birth-year range and writes
confidently wrong metadata, the same trap the sibling table hit with count
columns.

The AHS schedules get their own path (step 0). Their real dataset-level marker
is the `year` column, which holds survey round labels rather than years, so the
rounds present in each file are detected by grep -- one early-exiting pass
instead of parsing a 273 MB CSV -- and dated from the survey's published
fieldwork windows:

    Baseline / Round 1        Jul 2010 - Mar 2011
    First Updation / Round 2  Oct 2011 - Apr 2012
    Second Updation / Round 3 Nov 2012 - May 2013

(https://ghdx.healthdata.org/record/india-annual-health-survey-2010-2011,
 https://www.icpsr.umich.edu/web/DSDR/studies/38097). The span runs from the
earliest round the file actually contains to the latest, so a file carrying
only the baseline is not credited with three years of coverage.

Only rows still NULL in the staging table are touched. Results land in their own
table, temporal_derived_files, as well as in the staging table: this run costs
~25 minutes over 300 GB, and re-deriving titles (cheap, and repeated every time
that parser changes) must never throw it away. temporal_coverage_metadata.py
folds temporal_derived_files back in after every restage.

    python transformation/temporal/temporal_coverage_from_files.py
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import re
import subprocess
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
STAGE = "temporal_derived_metadata"
KEY = "nid"
FILE_STAGE = "temporal_derived_files"
# The corpus behind dublin_core_metadata; a handful of these uuids land in the
# sibling table's corpus instead.
DOWNLOAD_DIRS = ["data/first_batch_downloads", "data/final_batch_downloads"]

MIN_YEAR, MAX_YEAR = 1800, 2035


def _load_temporal_script():
    spec = importlib.util.spec_from_file_location("_ts", HERE / "Temporal_script.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def index_files(root):
    idx = {}
    for d in DOWNLOAD_DIRS:
        p = Path(root) / d
        if not p.is_dir():
            continue
        for name in os.listdir(p):
            idx.setdefault(os.path.splitext(name)[0], str(p / name))
    return idx


# Respondent attributes. A 273 MB household schedule has date_of_birth and
# year_of_marriage columns; their min/max is a birth-year range, not a coverage
# period, and writing it would be worse than writing nothing.
_PERSON_LEVEL = re.compile(
    r"(?i)(birth|marriage|marri|death|died|age|dob|admission|discharge|visit)")


def _columns(path):
    """Header row only, straight off disk -- no sniffing, no body read."""
    with open(path, newline="", errors="replace") as fh:
        cols = next(csv.reader(fh))
    src = (f"read_csv('{path}', header=true, all_varchar=true, "
           f"sample_size=2048, ignore_errors=true, union_by_name=false)")
    return cols, src


def _bounds_from_column(scan, src, col):
    """min/max of one column, streamed. Values are parsed by extract_years."""
    q = col.replace('"', '""')
    row = scan.execute(
        f'SELECT min("{q}"), max("{q}") FROM {src} WHERE "{q}" IS NOT NULL'
    ).fetchone()
    return row if row else (None, None)


# Fieldwork windows for the three AHS rounds, keyed by the label that appears in
# the files' `year` column.
AHS_ROUNDS = {
    "Baseline": (date(2010, 7, 1), date(2011, 3, 31)),
    "First Updation Round": (date(2011, 10, 1), date(2012, 4, 30)),
    "Second Updation Round": (date(2012, 11, 1), date(2013, 5, 31)),
}


# One pass, stopping as soon as all three labels have been seen. grep -qF per
# label costs three passes on a file that lacks the early ones -- a second-
# updation-only schedule reads 200 MB twice before failing -- and grep -oaE reads
# the whole file *and* emits a match line per row, which is far worse again.
_AHS_AWK = (
    '/Baseline/{a=1} /First Updation Round/{b=1} /Second Updation Round/{c=1} '
    'a&&b&&c{print "a b c"; exit} '
    'END{if(!(a&&b&&c)) print (a?"a":"-"), (b?"b":"-"), (c?"c":"-")}'
)
_AWK_KEY = {"a": "Baseline", "b": "First Updation Round", "c": "Second Updation Round"}


def ahs_rounds(path):
    """Which AHS rounds a file contains. (from, to) or None."""
    try:
        out = subprocess.run(["awk", _AHS_AWK, path], capture_output=True,
                             text=True, errors="replace").stdout
    except Exception:
        return None
    present = [_AWK_KEY[t] for t in out.split() if t in _AWK_KEY]
    if not present:
        return None
    spans = [AHS_ROUNDS[l] for l in present]
    return min(s for s, _ in spans), max(e for _, e in spans)



def scan_file(ts, scan, path, is_ahs=False):
    """(from_date, to_date) or (None, None). Never materialises the file."""
    if is_ahs:
        got = ahs_rounds(path)
        return got if got else (None, None)

    try:
        cols, src = _columns(path)
    except Exception:
        return None, None
    if not cols:
        return None, None

    # 1. The header row alone. compute_from_headers wants a frame whose columns
    #    are the header strings; an empty one carries the names it needs.
    try:
        import polars as pl
        f, t = ts.compute_from_headers(pl.DataFrame({c: [] for c in cols}))
        if f:
            return f, t
    except Exception:
        pass

    # 2. A real date column, bounded by DuckDB rather than by pandas.
    for col in cols:
        if not ts._header_is_temporal(col) or _PERSON_LEVEL.search(str(col)):
            continue
        try:
            lo, hi = _bounds_from_column(scan, src, col)
        except Exception:
            continue
        iv_lo = ts.extract_date_interval(lo) if lo is not None else None
        iv_hi = ts.extract_date_interval(hi) if hi is not None else None
        if iv_lo and iv_hi:
            f, t = min(iv_lo[0], iv_hi[0]), max(iv_lo[1], iv_hi[1])
            if MIN_YEAR <= f.year <= MAX_YEAR and MIN_YEAR <= t.year <= MAX_YEAR:
                return f, t
    return None, None


def _already_done(db):
    con = duckdb.connect(db, read_only=False)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
        if FILE_STAGE not in tables:
            return set()
        return {r[0] for r in con.execute(f"SELECT {KEY} FROM {FILE_STAGE}").fetchall()}
    finally:
        con.close()


def _persist(db, found):
    """Upsert the results so far into FILE_STAGE, then release the DB lock."""
    if not found:
        return
    frame = pd.DataFrame(found, columns=[KEY, "start_date", "end_date", "coverage"])
    # nid arrives as a Python object column; without the cast the DELETE below
    # compares BIGINT against VARCHAR and DuckDB refuses.
    frame[KEY] = frame[KEY].astype("int64")
    con = duckdb.connect(db, read_only=False)
    try:
        con.register("_files", frame)
        con.execute(f"""CREATE TABLE IF NOT EXISTS {FILE_STAGE} (
            {KEY} BIGINT, start_date DATE, end_date DATE, coverage VARCHAR)""")
        con.execute(f"DELETE FROM {FILE_STAGE} WHERE {KEY} IN (SELECT {KEY} FROM _files)")
        con.execute(f"INSERT INTO {FILE_STAGE} SELECT * FROM _files")
        con.unregister("_files")
        con.execute("CHECKPOINT")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--root", default=str(HERE.parents[1]))
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel AHS scans; the awks are latency bound")
    ap.add_argument("--memory-limit", default="2GB",
                    help="cap for the scanning connection, kept well under RAM")
    args = ap.parse_args()

    ts = _load_temporal_script()
    con = duckdb.connect(args.db, read_only=False)
    todo = con.execute(f"""
        SELECT d.nid, m."Identifier[UUID]", m."Title" FROM {STAGE} d
        JOIN dublin_core_metadata m USING(nid)
        WHERE d.coverage IS NULL AND m."Identifier[UUID]" IS NOT NULL
    """).fetchall()
    con.close()

    idx = index_files(args.root)
    work = [(nid, idx[uu], "annual health survey" in (t or "").lower())
            for nid, uu, t in todo if uu in idx]
    done = _already_done(args.db)
    if done:
        work = [w for w in work if w[0] not in done]
        print(f"resuming: {len(done)} already in {FILE_STAGE}", flush=True)
    print(f"{len(todo)} rows unresolved, {len(work)} left to scan", flush=True)

    # A separate in-memory connection so the file scan never holds the
    # metadata.db lock for the length of the run.
    scan = duckdb.connect(":memory:")
    scan.execute(f"SET memory_limit='{args.memory_limit}'")
    scan.execute("SET threads=4")

    found = []

    def record(nid, f, t):
        if f and t:
            if f > t:
                f, t = t, f
            found.append((nid, f, t, f"start:{f.isoformat()};end:{t.isoformat()}"))

    # Non-AHS files go through the DuckDB connection, which is not thread-safe,
    # and are cheap anyway -- a header read.
    plain = [(nid, path) for nid, path, is_ahs in work if not is_ahs]
    for i, (nid, path) in enumerate(plain, 1):
        record(nid, *scan_file(ts, scan, path, False))
        if i % 100 == 0:
            _persist(args.db, found)
            print(f"  header pass {i}/{len(plain)}, {len(found)} dated", flush=True)
    scan.close()
    _persist(args.db, found)
    print(f"header pass done: {len(plain)} files, {len(found)} dated", flush=True)

    # The AHS awks are I/O-latency bound, not bandwidth bound (this disk has been
    # seen at 77 MB/s and was delivering 4 MB/s sequentially), and each awk holds
    # ~2 MB, so a small pool overlaps the waits without the memory thrash that
    # made an all-cores pandas fan-out unusable here.
    ahs = [(nid, path) for nid, path, is_ahs in work if is_ahs]
    print(f"AHS pass: {len(ahs)} files on {args.workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ahs_rounds, path): nid for nid, path in ahs}
        for i, fut in enumerate(as_completed(futs), 1):
            got = fut.result()
            if got:
                record(futs[fut], *got)
            if i % 100 == 0:
                # Flush as we go: an interrupted run used to lose everything.
                _persist(args.db, found)
                print(f"  AHS {i}/{len(ahs)}, {len(found)} dated total", flush=True)

    print(f"{len(found)} of {len(work)} files yielded a period", flush=True)
    if not found:
        return

    _persist(args.db, found)
    con = duckdb.connect(args.db, read_only=False)
    con.execute(f"""
        UPDATE {STAGE} AS d SET
            matched_pattern = 'file_contents',
            start_date = f.start_date,
            end_date = f.end_date,
            coverage = f.coverage
        FROM {FILE_STAGE} AS f
        WHERE d.nid = f.nid AND d.coverage IS NULL
    """)
    con.execute("CHECKPOINT")
    print("staged. still unresolved:",
          con.execute(f"SELECT count(*) FROM {STAGE} WHERE coverage IS NULL").fetchone()[0])
    con.close()


if __name__ == "__main__":
    main()
