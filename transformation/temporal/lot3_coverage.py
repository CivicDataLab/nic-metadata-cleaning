#!/usr/bin/env python3
r"""Temporal + spatial coverage for dublin_core_lot3, re-derived for EVERY row.

lot3 arrived with data_time_period_from/to (and a Temporal Coverage built from
them) on ~23.5k of 29.6k rows, but those values are not trustworthy: "SHB 2018"
is stored as 2018-01-01..2019-12-31, "Punjab from 1986 to 2022" carries a 2023
upload date, and some are not dates at all ("0020-01-01"). So nothing existing
is taken on faith -- every row is re-derived from its file and title, and the
old value is only compared against (temporal_check).

This is a driver around the sibling scripts, not a re-implementation:

  * Temporal_script   extract_date_interval, extract_years, remove_garbage_rows,
                      and its precedence: a date column in the data, else the
                      column headers, else the title. Slash dates are read
                      day-first (see date_interval).
  * Spatial_script    extract_from_df / build_gazetteer / resolve_one, unchanged.
  * temporal_coverage_from_files  _PERSON_LEVEL (date_of_birth is not coverage).

What lot3 needs that those scripts do not do:

  1. JSON. 4.8k of the 20.8k files are JSON arrays of records (52 GB -- the
     Karnataka crop surveys), which neither reader handles.
  2. Whole-file bounds. Both scripts read the head of a file (5-10k rows). The
     big files here are sorted -- by date, or by district -- so the head gives
     the earliest dates only, or one district of a State-wide file. The head is
     used to *choose* the date / geo columns; their values are then counted over
     the whole file.
  3. Date-column choice. find_date_column takes the single best-parsing column
     and then rejects it if its header is not temporal, so a count column that
     happens to look like years hides a real "Year" column. Here only columns
     with a temporal header are candidates, headers are camelCase-split first
     ("CropSurveyDate"), plurals count ("Years"), and person-level / row-
     attribute columns (birth, formation, appointment, construction, validity)
     are skipped. Every candidate is counted during the scan and the choice is
     made at resolve time, so _NON_PERIOD can be tuned without re-reading 53 GB.
  4. Publisher fallback for space. 98.5% of lot3 is State-jurisdiction, and the
     publishing State is in Publisher[state_department]. It is used only when
     neither the file nor the title names a State: it fills "unknown" rows at
     State level, settles district names the gazetteer found ambiguous, and
     picks the publisher's State when a shared place name climbed to several.
     Such rows carry spatial_source "publisher" / "<source>+publisher".
  5. Title markers and typos. Handbook edition suffixes ("... 2015-16 : SHB
     2017") are dropped when the title has another date; slash dates are
     day-first; a file whose whole period lies in the future while its title
     names an earlier one ("till 03.03.2031" under "as on 04/03/2021") takes the
     title's date.

Two phases, as in Spatial_script:

    python lot3_coverage.py --scan           # read every file -> JSONL cache
    python lot3_coverage.py                  # resolve -> data/lot3_coverage_stage.csv
    python lot3_coverage.py --apply          # ... and write dublin_core_lot3

Columns written (--apply):
  data_time_period_from / _to  ISO, T00:00:00 / T23:59:59 (existing convention)
  Temporal Coverage            "<from date>/<to date>"      (existing convention)
  temporal_source              content_column | content_headers | title |
                               original_unverified | none
  temporal_check               the old from/to against the new one:
                               match | corrected | filled | unverified | empty
  spatial_coverage, spatial_states, spatial_districts, spatial_subdistricts,
  spatial_level, spatial_source                (as in dublin_core_remaining)
  Spatial Coverage             = spatial_coverage
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import duckdb
import pandas as pd
import polars as pl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Spatial_script needs two modules that are both called dataset_merge:
# title_components wants dataset_merging/dataset_merge.py (STATE_ALT, MONTH_RE),
# while Spatial_script's closed State list is transformation/dataset_merge.py's
# state_ut -- the dataset_merging one also lists aliases ("Orissa",
# "Pondicherry") that would each count as a separate State. Bind title_components
# to the first, then swap the second in before Spatial_script imports it.
_load("dataset_merge", HERE.parent / "dataset_merging" / "dataset_merge.py")
_load("title_components", HERE.parent / "dataset_merging" / "title_components.py")
_load("dataset_merge", HERE.parent / "dataset_merge.py")

sys.path.insert(0, str(HERE))
import Spatial_script as sp                                       # noqa: E402
import Temporal_script as ts                                      # noqa: E402
from temporal_coverage_from_files import _PERSON_LEVEL            # noqa: E402

# =========================================================
# CONFIG
# =========================================================

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_lot3"
UUID_COL = "Identifier[UUID]"

# lot3_downloads holds 20,781 of the table's files; lot3_s3_downloads holds
# 8,070 more, none of which are in the first folder.
DATA_DIRS = [ROOT / "data" / "lot3_downloads", ROOT / "data" / "lot3_s3_downloads"]
CACHE_PATH = ROOT / "data" / "lot3_coverage_cache.jsonl"
STAGE_CSV = ROOT / "data" / "lot3_coverage_stage.csv"
BACKUP_DIR = ROOT / "data" / "backups"
ORIG_SNAPSHOT = BACKUP_DIR / "lot3_coverage_original.parquet"

VALID_EXT = (".csv", ".json", ".xls", ".xlsx", ".xlsm", ".xlsb")
SAMPLE_ROWS = 5000          # rows used to pick the date / geo columns
DISTINCT_CAP = 200_000      # distinct values counted per column in the full pass
WORKERS = 4

MIN_YEAR, MAX_YEAR = ts.MIN_YEAR, ts.MAX_YEAR
RUN_DATE = date.today()

# Spatial_script scans titles with every alias, two-letter ones included, so
# "Total Goats (up to 1 year) in Punjab" reads as Punjab + Uttar Pradesh. Its
# header scan already drops aliases under four letters for the same reason
# (STRICT_STATE_LOOKUP); titles get the same treatment here.
sp._TITLE_STATE_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(s) for s in sorted(
            list(sp.CANON_STATES)
            + [a for a in sp.STATE_ALIASES if len(sp._norm(a)) >= 4],
            key=len, reverse=True)
    ) + r")\b",
    re.I,
)

# =========================================================
# DATES
# =========================================================

# Temporal_script reads d/d/yyyy month-first ("9/24/2021"), which misreads the
# day-first dates Indian portals write: "on 07/12/2021" is 7 December. Slash
# dates are read day-first unless the values themselves prove month-first (a
# middle field over 12); the unambiguous ones are swapped either way.
_SLASH_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/((?:18|19|20)\d{2})(?!\d)")


def slash_style(values):
    dmy = mdy = 0
    for v in values:
        for m in _SLASH_DATE.finditer(str(v)):
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12 >= b:
                dmy += 1
            elif b > 12 >= a:
                mdy += 1
    return "mdy" if mdy > dmy else "dmy"


# "Pension Rs.2000 Head/Month" is an amount, not the year 2000.
_CURRENCY = re.compile(r"(?i)(?:\brs\.?|\binr|₹)\s*\d[\d,]*(?:\.\d+)?")


def date_interval(val, style="dmy"):
    s = _CURRENCY.sub(" ", str(val))
    if style == "dmy":
        s = _SLASH_DATE.sub(r"\1-\2-\3", s)     # Temporal_script's d-m-y rule
    return ts.extract_date_interval(s)


# Names the readers invent for blank header cells. A KSBCL sheet with 2,000
# empty trailing columns becomes "_duplicated_0" .. "_duplicated_1999", which
# read as the years 1800-2035.
_AUTO_HEADER = re.compile(r"^(_duplicated_\d+|Unnamed: \d+(_level_\d+)?|column_\d+)?$")


def headers_interval(columns):
    """Temporal_script.compute_from_headers, day-first, invented names skipped."""
    columns = [c for c in columns if not _AUTO_HEADER.match(str(c).strip())]
    style = slash_style(columns)
    ivs = [iv for iv in (date_interval(c, style) for c in columns) if iv]
    if not ivs:
        return None, None
    return min(i[0] for i in ivs), max(i[1] for i in ivs)

# =========================================================
# DATE COLUMN CHOICE
# =========================================================

# Temporal_script._TEMPORAL_HEADER, plus plurals ("Years", "Dates"), run over the
# camelCase-split header so "CropSurveyDate" reads as "Crop Survey Date".
_TEMPORAL_HEADER = re.compile(
    r"(?i)(^|[^a-z])(years?|yr|dates?|months?|period|quarter|fy|financial\s*year|"
    r"as\s*on|as\s*at|time|week|day)([^a-z]|$)"
)
# A date that describes each row's subject, not the period the data covers: when
# a sanctuary was formed ("Year of Formation": 1940 in a 2016-17 handbook table),
# a school recognised, a notary appointed, an advocate enrolled, a dam built, a
# power station commissioned, a licence runs out. Applied at resolve time, so
# tuning it needs no re-scan.
_NON_PERIOD = re.compile(
    r"(?i)(establish|estd|founded|formation|formed|incorporat|inception|recogni|"
    r"appoint|enrol|approval|construct|commission|operation|expir|valid|renewal|"
    r"built)"
)


def is_time_header(col):
    """The header names a time field (Temporal_script's test, widened)."""
    raw = str(col)
    if ts._PERIOD_IN_HEADER.search(raw):
        return False
    return bool(_TEMPORAL_HEADER.search(sp.normalize_header(raw)))


def is_period_header(col):
    """...and that time is the dataset's period, not a row attribute."""
    h = sp.normalize_header(str(col))
    return is_time_header(col) and not (_PERSON_LEVEL.search(h)
                                        or _NON_PERIOD.search(h))


def date_candidates(df):
    """Every time-named column whose values mostly parse as years, in order.

    Temporal_script keeps only the best one; all are kept here (and counted over
    the whole file) so the choice among them can be revised without a re-scan.
    """
    out = []
    for col in df.columns:
        if not is_time_header(col):
            continue
        try:
            values = [v for v in df[col].drop_nulls().to_list()[:2000]
                      if ts.is_valid_value(v)]
        except Exception:
            continue
        if not values:
            continue
        ratio = sum(1 for v in values if ts.extract_years(v)) / len(values)
        if ratio > 0.5:
            out.append((col, ratio))
    return out


def choose_date_column(rec):
    """The best-parsing period column among the scanned candidates, or None."""
    best = None
    for cand in rec.get("date_cols", []):
        if not is_period_header(cand["col"]):
            continue
        if best is None or cand["ratio"] > best["ratio"]:
            best = cand
    return best


def interval_from_counter(counter):
    """(from, to, year_hist, parsed_rows) over value -> row-count."""
    starts, ends = [], []
    hist = Counter()
    parsed = 0
    style = slash_style(counter)
    for val, n in counter.items():
        if not ts.is_valid_value(val):
            continue
        iv = date_interval(val, style)
        if not iv:
            continue
        starts.append(iv[0])
        ends.append(iv[1])
        hist[iv[0].year] += n
        parsed += n
    if not starts:
        return None, None, {}, 0
    return min(starts), max(ends), dict(hist), parsed

# =========================================================
# READERS
# =========================================================


def _frame(columns, rows):
    """All-Utf8 polars frame; empty strings become nulls like a CSV read."""
    data = {c: [] for c in columns}
    for row in rows:
        for c, v in zip(columns, row):
            data[c].append(None if v is None or v == "" else str(v))
    return pl.DataFrame(data, schema={c: pl.Utf8 for c in columns})


def _json_prefix(text):
    """The complete records at the front of a truncated JSON array."""
    dec = json.JSONDecoder()
    i = text.find("[") + 1
    out = []
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            return out
        out.append(obj)


def open_json(path):
    """(columns, sample_frame, row_iter_factory) for a JSON array of records."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except ValueError:
        # some downloads were cut off mid-record; keep every complete one
        data = _json_prefix(raw.decode("utf-8", errors="replace"))
        if not data:
            raise
    del raw
    if isinstance(data, dict):
        # data.gov.in API shape, or a {"status": "FAIL"} stub from the download
        for key in ("records", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise ValueError(f"json object without records: {list(data)[:5]}")
    if not isinstance(data, list):
        raise ValueError("json is not an array")
    data = [r for r in data if isinstance(r, dict)]
    cols = []
    seen = set()
    for rec in data[:SAMPLE_ROWS]:
        for k in rec:
            if k not in seen:
                seen.add(k)
                cols.append(k)

    def cell(v):
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v

    sample = _frame(cols, ([cell(r.get(c)) for c in cols] for r in data[:SAMPLE_ROWS]))

    def rows(wanted):
        for r in data:
            yield [cell(r.get(cols[i])) for i in wanted]

    return cols, sample, rows, len(data) > SAMPLE_ROWS


def _csv_head(path):
    """Spatial_script.read_sample's CSV branch, for CSV text named ".xls"
    (read_sample picks its reader from the extension)."""
    with open(path, "rb") as fh:
        blob = fh.read(sp.CSV_READ_BYTES)
    if os.path.getsize(path) > sp.CSV_READ_BYTES and blob.rfind(b"\n") > 0:
        blob = blob[:blob.rfind(b"\n")]
    for enc in ("utf8", "utf8-lossy"):
        try:
            return pl.read_csv(BytesIO(blob), encoding=enc, n_rows=sp.MAX_ROWS,
                               infer_schema_length=0, ignore_errors=True,
                               truncate_ragged_lines=True, has_header=True)
        except Exception:
            continue
    raise ValueError("unreadable csv")


def open_csv(path):
    ext = path.lower().rsplit(".", 1)[-1]
    sample = _csv_head(path) if ext.startswith("xl") else sp.read_sample(path)
    cols = list(sample.columns)
    truncated = (os.path.getsize(path) > sp.CSV_READ_BYTES
                 or sample.height >= sp.MAX_ROWS)

    def rows(wanted):
        csv.field_size_limit(1 << 30)
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh)
            next(reader, None)                       # header
            for row in reader:
                yield [row[i] if i < len(row) else None for i in wanted]

    return cols, sample, rows, truncated


def open_excel(path):
    df = sp.read_sample(path)          # handles xls/xlsx/html-as-xls, MAX_ROWS
    cols = list(df.columns)

    def rows(wanted):
        for row in df.select([cols[i] for i in wanted]).iter_rows():
            yield list(row)

    return cols, df, rows, False


def open_any(path):
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "json":
        return open_json(path)
    if ext in ("xls", "xlsx", "xlsm", "xlsb"):
        try:
            return open_excel(path)
        except ValueError:
            pass        # most lot3 ".xls" files are CSV text; read them as such
    return open_csv(path)

# =========================================================
# PHASE 1: ONE FILE
# =========================================================


def geo_from_counters(columns, geo_cols, counters):
    """extract_from_df's value logic, over whole-file row counts."""
    states, districts, subdistricts = Counter(), Counter(), Counter()
    national = False

    for col in columns:                          # wide layout: a column per State
        for st in sp.canon_states_multi(col, strict=True):
            states[st] += 1

    for col in geo_cols.get("state", []):
        for val, n in counters.get(col, Counter()).items():
            if sp._norm(val) in ("india", "all india"):
                national = True
            for st in sp.canon_states_multi(val):
                states[st] += n

    for col in geo_cols.get("district", []):
        for val, n in counters.get(col, Counter()).items():
            st = sp.canon_state(val)
            if st:
                states[st] += n
                continue
            place = sp.clean_place(val)
            if place:
                districts[place] += n

    for col in geo_cols.get("subdistrict", []):
        for val, n in counters.get(col, Counter()).items():
            place = sp.clean_place(val)
            if place:
                subdistricts[place] += n

    def top(c):
        return [v for v, _ in c.most_common(sp.MAX_DISTINCT)]

    return top(states), top(districts), top(subdistricts), national


def scan_file(path):
    uuid = os.path.splitext(os.path.basename(path))[0]
    rec = {"uuid": uuid, "dir": Path(path).parent.name}
    try:
        cols, sample, rows, truncated = open_any(path)
    except Exception as exc:
        rec["error"] = str(exc)[:200]
        return rec
    if sample is None or sample.is_empty():
        rec["error"] = "empty"
        return rec

    cols = [str(c) for c in cols]
    rec["truncated"] = bool(truncated)

    # ---- choose columns on the head (Temporal_script drops total rows first)
    clean = ts.remove_garbage_rows(sample)
    if clean is None or clean.is_empty():
        clean = sample
    candidates = date_candidates(clean)

    geo = sp.extract_from_df(sample)
    geo_cols = geo.get("geo_cols", {})

    # ---- count their values over the whole file (or the head, if it is all)
    wanted = [c for c, _ in candidates]
    for kind in ("state", "district", "subdistrict"):
        for c in geo_cols.get(kind, []):
            if c not in wanted:
                wanted.append(c)

    counters = {c: Counter() for c in wanted}
    if wanted:
        idx = [cols.index(c) for c in wanted]
        source = rows(idx) if truncated else (
            [row[i] for i in idx] for row in sample.iter_rows())
        n_rows = 0
        try:
            for row in source:
                n_rows += 1
                for c, v in zip(wanted, row):
                    if v is None:
                        continue
                    v = str(v).strip()
                    if not v:
                        continue
                    ctr = counters[c]
                    if v in ctr or len(ctr) < DISTINCT_CAP:
                        ctr[v] += 1
        except Exception as exc:
            # full pass failed part-way: keep what the head gave instead
            rec["full_pass_error"] = str(exc)[:200]
            counters = {c: Counter() for c in wanted}
            for row in sample.select(wanted).iter_rows():
                for c, v in zip(wanted, row):
                    if v is not None and str(v).strip():
                        counters[c][str(v).strip()] += 1
        rec["rows_counted"] = n_rows

    # ---- temporal: every candidate column's bounds, plus the header names;
    #      which of them wins is decided in resolve
    rec["date_cols"] = []
    for col, ratio in candidates:
        f, t, hist, parsed = interval_from_counter(counters[col])
        rec["date_cols"].append({
            "col": col,
            "ratio": round(ratio, 4),
            "from": f.isoformat() if f else None,
            "to": t.isoformat() if t else None,
            "year_hist": {str(k): v for k, v in sorted(hist.items())},
            "rows_parsed": parsed,
            "rows_total": sum(counters[col].values()),
        })
    rec["columns"] = cols[:3000]

    # ---- spatial (d2s / s2d pairs stay from the head: they feed the gazetteer)
    states, districts, subs, national = geo_from_counters(cols, geo_cols, counters)
    rec.update({
        "states": states,
        "districts": districts,
        "subdistricts": subs,
        "national": national or geo.get("national", False),
        "d2s": geo.get("d2s", []),
        "s2d": geo.get("s2d", []),
        "geo_cols": geo_cols,
    })
    return rec

# =========================================================
# PHASE 1: DRIVER
# =========================================================


def list_files():
    out = {}
    for d in DATA_DIRS:
        if not d.is_dir():
            continue
        with os.scandir(d) as it:
            for e in it:
                if e.name.lower().endswith(VALID_EXT):
                    out.setdefault(os.path.splitext(e.name)[0], e.path)
    return out


def load_cache():
    recs = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("uuid"):
                    recs[r["uuid"]] = r
    return recs


def run_scan(args, uuids):
    files = list_files()
    todo = {u: p for u, p in files.items() if u in uuids}
    print(f"files on disk: {len(files)}, belonging to {TABLE}: {len(todo)}")
    done = set() if args.refresh else set(load_cache())
    todo = [p for u, p in todo.items() if u not in done]
    # biggest first, so the long JSON reads do not all land at the tail
    todo.sort(key=lambda p: -os.path.getsize(p))
    if args.limit:
        todo = todo[: args.limit]
    print(f"cached: {len(done)}, to scan: {len(todo)} on {args.workers} workers",
          flush=True)
    if not todo:
        return

    started = time.time()
    ok = err = 0
    with open(CACHE_PATH, "w" if args.refresh else "a", encoding="utf8") as out, \
            ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(scan_file, p): p for p in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                rec = fut.result()
            except Exception as exc:
                p = futs[fut]
                rec = {"uuid": os.path.splitext(os.path.basename(p))[0],
                       "error": f"worker: {exc}"[:200]}
            err += bool(rec.get("error"))
            ok += not rec.get("error")
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if n % 500 == 0:
                out.flush()
                rate = n / (time.time() - started)
                print(f"  {n}/{len(todo)} ok={ok} err={err} {rate:.1f}/s "
                      f"eta {(len(todo) - n) / rate / 60:.0f}m", flush=True)
    print(f"scan done: {ok} ok, {err} failed, "
          f"{(time.time() - started) / 60:.1f} min -> {CACHE_PATH}")

# =========================================================
# PHASE 2: RESOLVE
# =========================================================


def _d(s):
    return date.fromisoformat(s) if s else None


def parse_original(dfrom, dto):
    """The stored from/to as dates, or (None, None) if they are not sane."""
    if not dfrom or not dto:
        return None, None
    a = ts.extract_date_interval(str(dfrom)[:10])
    b = ts.extract_date_interval(str(dto)[:10])
    if not a or not b:
        return None, None
    f, t = a[0], b[1]
    return (f, t) if f <= t else (None, None)


def publisher_state(pub):
    if not pub:
        return None
    first = str(pub).split(",", 1)[0]
    st = sp.canon_state(first)
    if st:
        return st
    found = sp.states_from_title(first)
    return found[0] if len(found) == 1 else None


# Tamil Nadu's Statistical / District Handbooks and "TN at a Glance" end their
# titles with the EDITION: "Rainfall by Districts 2015-16 : SHB 2017" is 2015-16
# data. extract_date_interval unions every date in a title, which would stretch
# that to Apr 2015 - Dec 2017, so the marker is dropped whenever the title still
# has a date without it. "... : DHB 2017-18" alone keeps its edition as the date.
_HANDBOOK = re.compile(
    r"(?i)[\s:;,\-–]*\b(?:SHB|DHB|TN\s*GLANCE)\s*[-:]?\s*"
    r"(?:18|19|20)\d{2}(?:\s*[-–]\s*\d{2,4})?")


def title_interval(title):
    """Temporal_script._from_title, day-first, handbook edition dropped."""
    if not title or not ts.is_valid_value(title):
        return None, None
    title = str(title)
    stripped = _HANDBOOK.sub(" ", title)
    if stripped != title and ts._P_YEAR.search(stripped):
        title = stripped
    return date_interval(title) or (None, None)


def resolve_temporal(rec, title, orig_from, orig_to):
    """(from, to, source, check, date column) for one row."""
    f = t = None
    src = "none"
    rec = rec or {}
    best = choose_date_column(rec)
    hf, ht = headers_interval(rec.get("columns", []))
    tf, tt = title_interval(title)
    if best and best["from"]:
        f, t, src = _d(best["from"]), _d(best["to"]), "content_column"
    elif hf:
        f, t, src = hf, ht, "content_headers"
    elif tf:
        f, t, src = tf, tt, "title"

    # A file whose whole period is still in the future while its title names an
    # earlier one is a typo in the file: a COVID sheet headed "Cases till
    # 03.03.2031" under the title "as on 04/03/2021". Projections are left alone
    # -- they overlap their title's period, or the title has none.
    if src.startswith("content") and f > RUN_DATE and tf and tt < f:
        f, t, src = tf, tt, "title"

    of, ot = parse_original(orig_from, orig_to)
    had_orig = bool(orig_from or orig_to)

    if f:
        if f > t:
            f, t = t, f
        if not had_orig:
            check = "filled"
        elif (of, ot) == (f, t):
            check = "match"
        else:
            check = "corrected"
    elif of:
        # no evidence either way: keep the stored value, flagged
        f, t, src, check = of, ot, "original_unverified", "unverified"
    else:
        check = "empty"
    return f, t, src, check, (best["col"] if src == "content_column" else None)


def seed_records(con):
    """Hierarchy edges from dublin_core_remaining's resolved coverage strings.

    Spatial_script builds its gazetteer from the national scan cache, which is
    not on this machine; lot3 alone is three States. The strings that scan
    produced ("Nalanda, Bihar, India", "Rajgir, Nalanda, Bihar, India") are the
    same edges, one per dataset, so they are fed back in as records.
    """
    recs = {}
    rows = con.execute('''
        SELECT spatial_coverage, count(*) FROM dublin_core_remaining
        WHERE spatial_level IN ('district', 'sub_district')
        GROUP BY 1''').fetchall()
    for i, (cov, n) in enumerate(rows):
        parts = [p.strip() for p in str(cov).split(",")]
        if len(parts) < 3 or parts[-1] != "India":
            continue
        parts = parts[:-1]
        rec = {"d2s": [[parts[-2], parts[-1], n]], "districts": [parts[-2]]}
        if len(parts) == 3:
            rec["s2d"] = [[parts[0], parts[1], n]]
        recs[f"seed:{i}"] = rec
    return recs


def district_support(records):
    """_norm(district) -> Counter(State -> rows), before any dominance cut."""
    out = {}
    for rec in records.values():
        for d, s, c in rec.get("d2s", []):
            out.setdefault(sp._norm(d), Counter())[s] += c
    return out


def resolve_spatial(uuid, title, rec, gaz, pub_state, support):
    r = sp.resolve_one(uuid, title, rec, gaz)
    if not pub_state:
        return r
    # A State named by the file or the title outranks the publisher.
    if (rec or {}).get("states") or sp.states_from_title(title):
        return r
    # Otherwise any State in r was inferred by climbing the gazetteer, and a
    # place name shared across States climbs to all of them: Theni's "Cumbum"
    # block is also a Prakasam (Andhra Pradesh) sub-district, so a Theni table
    # came out Tamil Nadu + Andhra Pradesh. The publisher's State settles that
    # when it is among the candidates; when the climb found nothing ("unknown",
    # "unresolved") it is the best evidence left. A climb that lands only in
    # other States is left alone -- the file is about somewhere else.
    climbed = r["spatial_states"].split("; ") if r["spatial_states"] else []
    if r["spatial_level"] not in ("unknown", "unresolved") and not (
            len(climbed) > 1 and pub_state in climbed):
        return r
    # resolve_one attributes the injected State to "content", so the source
    # label is corrected afterwards.
    rec2 = dict(rec or {})
    rec2["states"] = [pub_state]

    def in_state(district):
        return support.get(sp._norm(district), Counter())[pub_state] >= sp.MIN_PAIR_COUNT

    # Keep only places the corpus has seen in that State. "Unresolved" names are
    # often not districts at all ("Kottur, Thiruthuraipoondi and Muthupettai"
    # from a "Places in District" column); the rest stay out and the row falls
    # back to State level.
    rec2["districts"] = [d for d in rec2.get("districts", []) if in_state(d)]
    rec2["subdistricts"] = [
        s for s in rec2.get("subdistricts", [])
        if sp._norm(s) in gaz["sub_to_dist"]
        and in_state(gaz["sub_to_dist"][sp._norm(s)])]
    r2 = sp.resolve_one(uuid, title, rec2, gaz)
    prior = r["spatial_source"]
    r2["spatial_source"] = "publisher" if prior == "none" else f"{prior}+publisher"
    return r2


def iso_from(d):
    return ts.to_from_iso(d)


def iso_to(d):
    return ts.to_to_iso(d)


def original_snapshot(db):
    """The from/to lot3 arrived with, frozen before the first --apply.

    temporal_check compares against these. Reading them off the live table
    would, on any re-run after an apply, compare the derivation with itself.
    """
    if ORIG_SNAPSHOT.exists():
        return
    con = duckdb.connect(db, read_only=True)
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()}
        if "temporal_check" in cols:
            sys.exit(f"{TABLE} was already rewritten and {ORIG_SNAPSHOT} is "
                     "missing; restore it from data/backups/ before re-running")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        con.execute(f'''COPY (SELECT DISTINCT nid, "{UUID_COL}" AS uuid,
                data_time_period_from, data_time_period_to,
                "Temporal Coverage", "Spatial Coverage" FROM {TABLE})
            TO '{ORIG_SNAPSHOT}' (FORMAT parquet)''')
    finally:
        con.close()
    print(f"original from/to frozen -> {ORIG_SNAPSHOT}")


def run_resolve(args):
    original_snapshot(args.db)
    con = duckdb.connect(args.db, read_only=True)
    rows = con.execute(f'''
        SELECT t.nid, t."{UUID_COL}", t."Title", o.data_time_period_from,
               o.data_time_period_to, o."Temporal Coverage",
               t."Publisher[state_department]"
        FROM {TABLE} t
        LEFT JOIN read_parquet('{ORIG_SNAPSHOT}') o
          ON o.nid IS NOT DISTINCT FROM t.nid          -- one lot3 row has no nid
         AND o.uuid = t."{UUID_COL}"''').fetchall()
    seeds = seed_records(con)
    con.close()

    cache = load_cache()
    readable = {u: r for u, r in cache.items() if not r.get("error")}
    print(f"{TABLE}: {len(rows)} rows | cache: {len(cache)} files, "
          f"{len(readable)} readable | {len(seeds)} seed edges")
    evidence = {**readable, **seeds}
    gaz = sp.build_gazetteer(evidence)
    support = district_support(evidence)

    out = []
    for nid, uuid, title, ofrom, oto, otc, pub in rows:
        rec = readable.get(uuid)
        f, t, tsrc, tcheck, dcol = resolve_temporal(rec, title, ofrom, oto)
        sr = resolve_spatial(uuid, title, rec, gaz, publisher_state(pub), support)
        tf, tt = title_interval(title)
        out.append({
            "nid": nid,
            "uuid": uuid,
            "title": title,
            "file": (cache.get(uuid) or {}).get("dir"),
            "file_error": (cache.get(uuid) or {}).get("error"),
            "orig_from": ofrom,
            "orig_to": oto,
            "orig_temporal_coverage": otc,
            "data_time_period_from": iso_from(f),
            "data_time_period_to": iso_to(t),
            "Temporal Coverage": f"{f.isoformat()}/{t.isoformat()}" if f else None,
            "temporal_source": tsrc,
            "temporal_check": tcheck,
            "date_col": dcol,
            "title_from": tf.isoformat() if tf else None,
            "title_to": tt.isoformat() if tt else None,
            **{c: sr[c] for c in sp.SPATIAL_COLS},
        })

    frame = pd.DataFrame(out)
    frame.to_csv(STAGE_CSV, index=False)
    print(f"staged -> {STAGE_CSV}")

    print("\nfiles:", dict(Counter(r["file"] or "(no file)" for r in out)))
    print("temporal_source:", dict(Counter(r["temporal_source"] for r in out)))
    print("temporal_check :", dict(Counter(r["temporal_check"] for r in out)))
    print("spatial_level  :", dict(Counter(r["spatial_level"] for r in out)))
    print("spatial_source :", dict(Counter(r["spatial_source"] for r in out)))

    if args.apply:
        apply(args.db, frame)


TEMPORAL_NEW = ["temporal_source", "temporal_check"]


def apply(db, frame):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # the columns this run overwrites, keyed like the update -- a complete undo
    snap = BACKUP_DIR / f"lot3_coverage_cols_{stamp}.parquet"
    con = duckdb.connect(db, read_only=True)
    existing = {r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()}
    keep = ["nid", UUID_COL, "data_time_period_from", "data_time_period_to",
            "Temporal Coverage", "Spatial Coverage"] + [
        c for c in TEMPORAL_NEW + sp.SPATIAL_COLS if c in existing]
    sel = ", ".join(f'"{c}"' for c in keep)
    con.execute(f"COPY (SELECT {sel} FROM {TABLE}) TO '{snap}' (FORMAT parquet)")
    con.close()
    dbcopy = f"{db}.bak-lot3coverage-{stamp}"
    shutil.copy2(db, dbcopy)
    print(f"backups: {snap}\n         {dbcopy}")

    upd = frame[["nid", "uuid", "data_time_period_from", "data_time_period_to",
                 "Temporal Coverage"] + TEMPORAL_NEW + sp.SPATIAL_COLS].copy()
    upd = upd.astype(object).where(upd.notna(), None)

    con = duckdb.connect(db)
    try:
        con.execute("BEGIN")
        for c in TEMPORAL_NEW + sp.SPATIAL_COLS:
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS "{c}" VARCHAR')
        con.register("cov_upd", upd)
        sets = ", ".join(
            [f'"{c}" = u."{c}"' for c in
             ["data_time_period_from", "data_time_period_to", "Temporal Coverage"]
             + TEMPORAL_NEW + sp.SPATIAL_COLS]
            + ['"Spatial Coverage" = u.spatial_coverage'])
        con.execute(f'''
            UPDATE {TABLE} AS d SET {sets}
            FROM (SELECT DISTINCT * FROM cov_upd) AS u
            WHERE d.nid IS NOT DISTINCT FROM u.nid AND d."{UUID_COL}" = u.uuid''')
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        chk = con.execute(f'''SELECT count(*) FILTER (WHERE temporal_check IS NULL),
                count(*) FILTER (WHERE spatial_level IS NULL) FROM {TABLE}''').fetchone()
        if chk != (0, 0):
            raise RuntimeError(f"rows left unwritten (temporal, spatial): {chk}")
        con.execute("COMMIT")
        con.execute("CHECKPOINT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    print(f"applied to all {n} rows of {TABLE}")

# =========================================================
# MAIN
# =========================================================


def main():
    global CACHE_PATH, STAGE_CSV
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--scan", action="store_true", help="phase 1: read the files")
    ap.add_argument("--apply", action="store_true", help="write the table")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--limit", type=int, default=0, help="scan at most N files")
    ap.add_argument("--refresh", action="store_true",
                    help="discard the scan cache (needed after changing scan_file)")
    ap.add_argument("--cache", default=str(CACHE_PATH))
    ap.add_argument("--stage", default=str(STAGE_CSV))
    args = ap.parse_args()
    CACHE_PATH, STAGE_CSV = Path(args.cache), Path(args.stage)

    if args.scan:
        con = duckdb.connect(args.db, read_only=True)
        uuids = {r[0] for r in con.execute(
            f'SELECT "{UUID_COL}" FROM {TABLE}').fetchall()}
        con.close()
        run_scan(args, uuids)
    else:
        run_resolve(args)


if __name__ == "__main__":
    main()
