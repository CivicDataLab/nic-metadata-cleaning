"""
HVD Pulse (xlsx edition) -- monthly High Value Dataset scoring with a freshness
check, reading dublin_core_metadata.xlsx directly. No DuckDB, no Postgres.

    hvd_score = 0.35*demand + 0.25*temporal + 0.15*geo
              + 0.10*liveness + 0.15*punctuality

Every signal is normalised to [0,1]. A signal that is unavailable for a row is
NaN, not zero, and `combine` redistributes its weight across the rest -- a
missing signal is not evidence of low value.

The two freshness terms are separate on purpose:

  liveness     how stale is this, in absolute terms. 0.5 ** (days/365), so a
               year-old row scores 0.5 whatever cadence it declared. Universal.

  punctuality  did this refresh inside its OWN declared period. Binary: 1.0 on
               time, 0.0 late. NaN when the check does not apply -- not API-fed,
               cadence coarser than annual, or no modification date.

Making the half-life itself cadence-relative (one term instead of two) inverts
the score: a Decadal table 8.5 years stale scores 0.55 while a Quarterly one 4
years stale scores 0.00002, and Daily underflows to a hard 0.0. Since the
cadence is a publisher-controlled dropdown, that is a score you can buy by
editing a field. Here, declaring a lax cadence only ever buys NaN -- the neutral
outcome -- so a publisher who does refresh monthly can only lose by declaring
Decadal.

Two rules key off the dataset's RESOURCE TYPE (the portal's
`field_resource_type`, carried as `Accrual Method` on the dublin_core tables),
because two kinds of dataset are misread by the generic signals:

  type 6   API-served datasets -- dashboards and JSON feeds. Nobody downloads
           them, they are polled, so `ogdp_download_count` reads near zero and
           demand understates them. The download facet reads
           `api_request_count` instead.

  type 2   external links to a publisher's own host. The portal row is a
           POINTER, so `Date Modified` records edits to the pointer rather than
           refreshes of the data behind it. Both freshness terms are measured
           from the last date the DATA covers instead.

BOTH RULES ARE INERT ON THIS WORKBOOK, and that is expected rather than a bug.
`Accrual Method` here is "1" on 206,971 of 206,972 rows and "5" on the
remaining one -- no type 2 and no type 6 -- so every row scores the generic
way. The code is kept because it costs nothing and the workbook is a snapshot:
the moment an export carries type 2 or 6 rows, the rules start applying with no
edit here. The type-2 rule also has no `data_time_period_to` to read on this
table (the column does not exist in the export) and would fall back to the end
year of Temporal Coverage -- see `dataset_last_date`.

Stateless by design: no snapshot ledger, no cadence table, no score history.
Each run is a pure function of the workbook it reads.

Reads read-only and writes one CSV. It never writes the portal's
`High Value Dataset Category` field -- that stays a human publishing decision.

WHY IT READS THE WAY IT DOES
----------------------------
The workbook is ~77 MB / 206,972 rows x 79 columns. The scoring arithmetic is
vectorised numpy and costs ~1-2s; essentially all the wall time is spreadsheet
decode, so that is the only place worth optimising.

  * python_calamine (Rust) decodes the sheet in ~14s. openpyxl -- which is what
    `pd.read_excel` would reach for by default -- takes minutes on a file this
    size and holds far more memory. calamine is driven DIRECTLY rather than via
    `pd.read_excel(engine="calamine")` because that engine needs pandas >= 2.2
    and this environment pins pandas 2.1.3.
  * openpyxl remains a fallback so the script still runs where calamine is
    absent, just slowly. It warns when it takes that path.
  * The 15 columns actually used are cached to Parquet, keyed on the workbook's
    size+mtime, so only the first run per workbook version pays the decode and
    later runs load in well under a second. That matters here because the data
    lives on a slow external drive. --no-cache and --refresh-cache opt out.

Every cell in this workbook is stored as TEXT, including the dates and the
counts, which is the same shape the DuckDB VARCHAR columns had. The signal code
below is therefore a verbatim port -- `as_text`, `to_naive_datetime` and
`pd.to_numeric` do all the coercion, exactly as they did before.

Usage:
    python hvd_scoring/hvd_score_xlsx.py
    python hvd_scoring/hvd_score_xlsx.py --xlsx /path/to/dublin_core_metadata.xlsx
    python hvd_scoring/hvd_score_xlsx.py --limit 1000
    python hvd_scoring/hvd_score_xlsx.py --cut-mode absolute --cut-value 0.42
"""

import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- config ----

# Anchored to the repo root, so the defaults resolve from any working directory.
repo_root = Path(__file__).resolve().parent.parent

# $HVD_XLSX overrides, so a scheduled run can be pointed elsewhere with no flags.
default_xlsx = os.environ.get(
    "HVD_XLSX", str(repo_root / "dublin_core_metadata.xlsx"))
default_out = str(repo_root / "hvd_scoring" / "hvd_scores_xlsx.csv")
default_cache_dir = str(repo_root / "hvd_scoring" / ".cache")

# The data sheet. Sheet2 of this workbook exists but is empty.
default_sheet = "Sheet1"

weights = {
    "demand": 0.35,
    "temporal": 0.25,
    "geo": 0.15,
    "liveness": 0.10,
    "punctuality": 0.15,
}

# Declared cadence -> days it is allowed to go without a refresh. Anything not
# listed here is not auditable by a monthly run (decadal, five yearly, biennial,
# one-time, others, irregular, blank) and scores punctuality NaN.
#
# On this workbook Accrual Periodicity is a purl.org CLD URI, so the prefix is
# stripped in `load` before the lookup. The observed spread is monthly 179,272 /
# irregular 17,220 / quarterly 7,121 / annual 3,358 / onetime 1 -- so `irregular`
# and `onetime` (17,221 rows) are deliberately unmapped and score NaN.
cadence_days = {
    "hourly": 30.0,
    "daily": 30.0,
    "weekly": 30.0,
    "fortnightly": 30.0,
    "monthly": 30.0,
    "quarterly": 91.0,
    "half yearly": 183.0,
    "biannual": 183.0,
    "annual": 365.0,
}

# One run interval, and the floor under every cadence above. A monthly job
# cannot resolve anything finer, so sub-monthly cadences all collapse to it and
# the check reduces to exactly the intended question: was it updated this month
# or not. Keep this equal to the sub-monthly entries in `cadence_days` -- the
# floor is applied AFTER the lookup, so a larger value here silently overrides
# them.
run_interval_days = 30.0

# Accepted spellings of the field_from_api gate. Free-text VARCHAR: this
# database already holds '1', '0', '' and NULL in it across tables, plus the
# literal string 'NULL' in the aikosh tables. Compared lower-cased.
#
# NOTE for this workbook: field_from_api is '0' on every one of its 206,972
# rows. Punctuality is therefore NaN table-wide (flag `not_from_api`) and its
# 0.15 weight redistributes across the other four signals on every row. That is
# the intended handling of a signal the data cannot support -- but it also means
# --api-only selects zero rows here and exits at "Nothing to score.", so the
# flag is rejected up front with an explanation rather than failing late.
api_true = {"1", "true", "yes", "y", "t"}
api_blank = {"", "null", "none", "nan"}

half_life_days = 365.0

# Resource types that get a substituted signal input. The value is the portal's
# `field_resource_type` code, which the dublin_core tables carry as
# `Accrual Method`; matched as a trimmed string because it arrives as text.
# Neither set matches anything in this workbook -- see the module docstring.
request_count_types = {"6"}   # demand reads api_request_count, not downloads
dataset_date_types = {"2"}    # freshness reads the data's own last date

n_states_ut = 36  # 28 states + 8 union territories

# A "State-wise" / "UT-wise" title reports one row per State/UT, so the dataset
# already spans all 36. "District-wise", "Crop-wise" etc. deliberately do not.
state_wise_re = re.compile(
    r"\b(?:state|ut|u\.?t\.?|union\s+territor(?:y|ies))[\s/-]*wise\b", re.I
)

# The purl.org prefix Accrual Periodicity arrives with on this table.
cadence_uri_prefix = "http://purl.org/cld/freq/"

# ------------------------------------------------------------------------
# The columns this script reads, mapped to the internal names the signal
# functions expect. This replaces the per-table SQL `select` of the DuckDB
# version -- same contract, same alias names.
#
# A column missing from the workbook is NOT fatal for the three optional ones
# below; everything here is required except those, and `load` says plainly
# which one is missing rather than raising a KeyError from deep inside a signal.
# ------------------------------------------------------------------------
column_map = {
    "nid": "nid",
    "Title": "Title",
    "Collection": "Collection",
    "Publisher[ministry_department]": "Publisher[ministry_department]",
    "Spatial Coverage": "Spatial Coverage",
    "Temporal Coverage": "temporal_raw",
    "ogdp_download_count": "ogdp_download_count",
    "ogdp_view_count": "ogdp_view_count",
    "Date Created": "date_created_raw",
    "Date Issued": "date_issued_raw",
    "Date Modified": "modified_raw",
    "Accrual Periodicity": "cadence_raw",
    "field_from_api": "field_from_api",
    "Accrual Method": "resource_type_raw",
    "api_request_count": "request_count_raw",
}

# Driving the resource-type rules. Absent -> the rule goes quiet and the row
# scores the generic way; it costs no signal. `data_time_period_to` is simply
# not present in this export, which is why it has no `column_map` entry at all.
optional_internal = ("resource_type_raw", "request_count_raw", "data_end_raw")

ministry_col = "Publisher[ministry_department]"


# ------------------------------------------------------------------- read ----

def read_workbook(xlsx, sheet):
    """Decode `sheet` of `xlsx` into a DataFrame of the mapped columns, as text.

    Tries python_calamine first (~14s on the 77 MB workbook), falls back to
    openpyxl (minutes) with a warning. Only the mapped columns are materialised:
    the sheet has 79 and the extra 64 are pure memory cost.
    """
    t0 = time.perf_counter()
    try:
        from python_calamine import CalamineWorkbook
    except ImportError:
        return _read_openpyxl(xlsx, sheet, t0)

    book = CalamineWorkbook.from_path(str(xlsx))
    if sheet not in book.sheet_names:
        raise SystemExit(
            f"No sheet {sheet!r} in {xlsx}; found: {', '.join(book.sheet_names)}"
        )
    rows = book.get_sheet_by_name(sheet).to_python(skip_empty_area=False)
    if not rows:
        raise SystemExit(f"Sheet {sheet!r} of {xlsx} is empty.")

    header = [str(h) for h in rows[0]]
    idx = _resolve_columns(header, xlsx)
    # Build column-wise: one list comprehension per kept column beats
    # materialising 206,972 x 79 Python objects and then dropping 64 of them.
    df = pd.DataFrame({
        internal: [r[i] if i < len(r) else None for r in rows[1:]]
        for i, internal in idx.items()
    })
    print(f"Decoded {len(df):,} rows x {len(df.columns)} columns via calamine "
          f"in {time.perf_counter() - t0:.1f}s")
    return df


def _read_openpyxl(xlsx, sheet, t0):
    """Fallback path. Correct, just slow -- minutes on a workbook this size."""
    print("WARNING: python_calamine not installed; falling back to openpyxl, "
          "which takes minutes on a workbook this size.\n"
          "         pip install python-calamine", file=sys.stderr)
    raw = pd.read_excel(xlsx, sheet_name=sheet, dtype=str)
    idx = _resolve_columns([str(c) for c in raw.columns], xlsx)
    df = raw.iloc[:, list(idx)].copy()
    df.columns = [idx[i] for i in idx]
    print(f"Decoded {len(df):,} rows x {len(df.columns)} columns via openpyxl "
          f"in {time.perf_counter() - t0:.1f}s")
    return df


def _resolve_columns(header, xlsx):
    """{position -> internal name} for the mapped columns, or a clear exit.

    Reports every missing required column at once: finding out about them one
    re-run at a time, at ~14s a decode, is its own small tax.
    """
    pos = {}
    missing = []
    for source, internal in column_map.items():
        if source in header:
            pos[header.index(source)] = internal
        elif internal in optional_internal:
            continue  # rule goes quiet; `load` fills NaN
        else:
            missing.append(source)
    if missing:
        raise SystemExit(
            f"{xlsx} is missing required column(s): {', '.join(missing)}.\n"
            f"Found {len(header)} columns; this script expects the "
            f"dublin_core_metadata export."
        )
    return pos


def cache_path(xlsx, cache_dir):
    """Parquet cache key: workbook size + mtime.

    Content hashing a 77 MB file on a slow spinning external drive costs about
    as much as re-decoding it, so the key is the cheap stat-only pair instead --
    the same convention the rest of this repo uses for that drive. Edit the
    workbook and the key changes; restore an old copy and its own cache comes
    back.
    """
    st = Path(xlsx).stat()
    return Path(cache_dir) / f"{Path(xlsx).stem}.{st.st_size}-{int(st.st_mtime)}.parquet"


def read_cached(xlsx, sheet, cache_dir, use_cache=True, refresh=False):
    """`read_workbook`, memoised to Parquet.

    The cache holds the mapped columns AFTER text coercion, never the raw Excel
    values. That is not incidental: a raw object column mixing str and int is
    unwritable by Arrow ("Could not convert 'x' with type str: tried to convert
    to int64"), whereas the all-text frame round-trips exactly. Coercion is also
    what the signal code wants anyway, so nothing is lost by doing it earlier.
    """
    if not use_cache:
        return _as_all_text(read_workbook(xlsx, sheet))

    path = cache_path(xlsx, cache_dir)
    if path.exists() and not refresh:
        t0 = time.perf_counter()
        try:
            df = pd.read_parquet(path)
            print(f"Loaded {len(df):,} rows from cache {path.name} "
                  f"in {time.perf_counter() - t0:.2f}s")
            return df
        except Exception as e:  # noqa: BLE001 - a bad cache must never be fatal
            print(f"Ignoring unreadable cache {path.name}: {e}", file=sys.stderr)

    df = _as_all_text(read_workbook(xlsx, sheet))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        print(f"Cached to {path}")
    except Exception as e:  # noqa: BLE001 - caching is an optimisation only
        print(f"Could not write cache ({e}); continuing.", file=sys.stderr)
    return df


def _as_all_text(df):
    """Every mapped column to str with nulls as ''.

    Matches the VARCHAR shape the DuckDB version handed the signals, and makes
    the frame Parquet-safe in one step.
    """
    return pd.DataFrame({c: as_text(df[c]) for c in df.columns})


# ------------------------------------------------------------------- load ----

def load(xlsx, sheet, cache_dir, use_cache=True, refresh=False,
         ministries=None, limit=None):
    """Read the workbook and normalise it into the columns the signals expect.

    The two derivations here are the pandas equivalents of what the DuckDB
    profile did in SQL:

      issued_raw   COALESCE(NULLIF(trim("Date Created"), ''), "Date Issued").
                   Date Created, not Date Issued, is the demand-age basis:
                   Date Issued carries the API's `published` and is blank on
                   tens of thousands of rows, while Date Created carries
                   `created` and is populated on effectively every row.
      cadence_raw  replace(..., 'http://purl.org/cld/freq/', '') -- this table
                   stores Accrual Periodicity as a CLD URI, which would match
                   nothing in `cadence_days` unstripped.

    Row filters are applied in the same order the SQL did it -- ministries, then
    limit -- so --limit keeps meaning "the first N of the selected ministries".
    --api-only is applied later, in main, exactly as LIMIT preceded it before.
    """
    df = read_cached(xlsx, sheet, cache_dir, use_cache, refresh)

    if ministries:
        df = df[df[ministry_col].isin(list(ministries))]
    if limit:
        df = df.head(int(limit))
    df = df.reset_index(drop=True)

    # NULLIF(trim(...), '') -> fall back to Date Issued where Date Created is blank.
    created = df["date_created_raw"].str.strip()
    df["issued_raw"] = created.where(created != "", df["date_issued_raw"])

    # Both columns are ISO date strings. Anything unparseable becomes NaT, which
    # the signals read as missing.
    df["date_issued"] = to_naive_datetime(df["issued_raw"])
    df["date_modified"] = to_naive_datetime(df["modified_raw"])

    # This table's Temporal Coverage is already `start:YYYY;end:YYYY` (the SQL
    # profile's "start_end"), so it passes through. Blank -> the 'None' missing
    # marker `signal_temporal` looks for.
    tc = df["temporal_raw"].str.strip()
    df["temporal_coverage"] = tc.where(tc != "", "None")

    df["cadence"] = (df["cadence_raw"].str.replace(cadence_uri_prefix, "", regex=False)
                     .str.strip().str.lower())
    df["from_api"] = df["field_from_api"].str.strip()

    # The three columns the resource-type rules read are OPTIONAL: a workbook
    # without one leaves the rule quiet instead of raising. `data_end_raw` is
    # always absent on this export.
    for col in optional_internal:
        if col not in df.columns:
            df[col] = np.nan
    df["resource_type"] = as_text(df["resource_type_raw"]).str.strip()
    return df


def as_text(s):
    """Series -> object dtype of str, with nulls as ''. Idempotent on text."""
    return s.astype("object").where(s.notna(), "").astype(str)


def to_naive_datetime(s):
    """Parse to tz-naive datetimes; NaT for anything unparseable."""
    out = pd.to_datetime(s, errors="coerce", utc=True)
    try:
        return out.dt.tz_localize(None)
    except (TypeError, AttributeError):
        return out


# ---------------------------------------------------------------- signals ----

def minmax(s, clip_pct=None):
    """Min-max to [0,1], keeping NaN as missing.

    `clip_pct` winsorises the upper tail first. Without it a handful of outliers
    flatten everything else to zero: the top download count is ~360x the median,
    and one 211-year temporal span crushed the 3-year majority to 0.009. Values
    above the cap saturate at 1.0 -- they are top-tier on that signal either way.
    """
    x = s
    if clip_pct is not None and s.notna().any():
        x = s.clip(upper=np.nanpercentile(s.dropna(), clip_pct))
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi == lo:
        return x.notna().astype(float).replace(0.0, np.nan)
    return (x - lo) / (hi - lo)


def demand_count(df):
    """The access count `demand` reads, per row, and where it came from.

    Downloads everywhere except the API-served resource types, whose download
    counter is near zero by construction -- those datasets are polled, not
    downloaded -- so `api_request_count` is the only count that reflects their
    use at all. No row of this workbook is such a type, so in practice every row
    here reports `downloads`; the branch is kept for the tables that do.

    A row of a request-count type whose request count is NULL keeps its download
    count, flagged. Zero requests is evidence and is used as a zero; an absent
    or unselected column is not evidence of anything.
    """
    downloads = pd.to_numeric(df["ogdp_download_count"], errors="coerce")
    requests = pd.to_numeric(df["request_count_raw"], errors="coerce")

    api_served = df["resource_type"].isin(request_count_types)
    use_requests = api_served & requests.notna()

    count = downloads.mask(use_requests, requests)

    # Last write wins, so the order is precedence lowest-first.
    source = pd.Series("downloads", index=df.index)
    source[api_served] = "no_request_count"
    source[use_requests] = "api_requests"
    return count, source


def signal_demand(df, as_of, clip_pct):
    """Access count and views per month since publication, log-damped.

    Rates rather than lifetime totals, because raw counts are age-biased.
    """
    months = (pd.Timestamp(as_of) - df["date_issued"]).dt.days / 30.44
    months = months.where(months >= 1.0, 1.0)

    count, count_source = demand_count(df)

    facets = [
        minmax(np.log1p(pd.to_numeric(s, errors="coerce") / months), clip_pct)
        for s in (count, df["ogdp_view_count"])
    ]
    # Average the two; if only one is present, use it alone.
    demand = pd.concat(facets, axis=1).mean(axis=1, skipna=True)
    return demand, months, count, count_source


def signal_temporal(df, clip_pct, min_start):
    """Span in years parsed from Temporal Coverage.

    One snapshot supports lookup; multiple years support trend analysis. Log-
    transformed because the gain from 1 -> 3 years is large and from 100 -> 200
    negligible. The literal string 'None' is a missing marker, not a zero span.

    TWO ENCODINGS, because this table carries both:

      start:YYYY-MM-DD;end:YYYY-MM-DD   206,797 rows. The span is the interval's
          DURATION, not the difference of its year labels. Year labels
          double-count fiscal years: start:2018-04-01;end:2019-03-31 is twelve
          months, but its labels say 2018..2019, which reads as two years --
          twice the depth of a calendar-year peer covering the same twelve
          months. Apr-Mar is the norm on this table, so this is not a rare
          edge: 44,865 rows (21.7%) disagree between the two readings.
          This is the same correction `from_interval` applies in the DuckDB
          original, which exists for exactly this reason; it is reproduced here
          because this export changed shape -- the workbook used to carry bare
          `start:YYYY;end:YYYY`, where there was no sub-year detail to use.

      start:YYYY;end:YYYY               5 rows. No sub-year information exists,
          so the span stays the label arithmetic, `end - start + 1`.

    Temporal Coverage is populated on 206,802 of 206,972 rows, so unlike the
    previous export this signal now carries its full 0.25 weight on virtually
    every row rather than redistributing it.
    """
    tc = df["temporal_coverage"].fillna("").str.strip()
    start_raw = tc.str.extract(r"start:([^;]+)", expand=False).str.strip()
    end_raw = tc.str.extract(r"end:(.+)$", expand=False).str.strip()

    # A bare year parses as 1 January, which would silently put the five
    # year-only rows on the duration path and cost them a year of depth. Gate on
    # the literal shape instead, so only a real YYYY-MM-DD pair qualifies.
    iso = r"^\d{4}-\d{2}-\d{2}"
    full = (start_raw.str.match(iso).fillna(False)
            & end_raw.str.match(iso).fillna(False))

    start_dt = to_naive_datetime(start_raw)
    end_dt = to_naive_datetime(end_raw)
    days = (end_dt - start_dt).dt.days
    # Reversed intervals are garbage, not zero-length, and fall through to NaN.
    dated = full & start_dt.notna() & end_dt.notna() & (days >= 0)
    dur_depth = (days / 365.25).round().clip(lower=1)

    start = start_raw.str.extract(r"^(\d{4})", expand=False).astype(float)
    end = end_raw.str.extract(r"^(\d{4})", expand=False).astype(float)
    yr_depth = (end - start + 1).where(start.notna() & end.notna())

    depth = yr_depth.mask(dated, dur_depth)
    depth = depth.where(depth >= 1)  # guard reversed / garbage ranges

    # Starts before `min_start` are parse artifacts, not history -- single-year
    # AHS/HMIS surveys carrying start:1910. Left in, they scored temporal ~1.0
    # and made up 38% of the candidate set. Treated as missing rather than zero:
    # an unparseable field is not evidence of low value.
    implausible = (start < min_start).fillna(False)
    depth = depth.mask(implausible)

    # Why temporal is absent, so a reviewer can tell a bad date from no date.
    flag = pd.Series("ok", index=df.index)
    flag[tc.isin(["", "None"]) | start.isna() | end.isna()] = "no_date"
    flag[implausible] = f"implausible_start_pre_{min_start}"

    return minmax(np.log1p(depth), clip_pct), depth, flag


def signal_geo(df):
    """Fraction of the 36 States/UTs a dataset spans.

    Later rules override earlier ones:
      1. per-Collection fraction of distinct States/UTs the merge family spans
         (28/36 beats 4/36),
      2. national ('India') but not resolved per State/UT -> half credit,
      3. a State/UT-wise title already spans all 36 -> full credit.

    A national row inside a partial-coverage collection is deliberately pinned
    to 0.5 rather than its collection fraction.
    """
    spatial = df["Spatial Coverage"]
    state = spatial.map(parse_state)
    is_national = spatial.fillna("").str.strip().str.lower() == "india"
    state_wise = df["Title"].fillna("").str.contains(state_wise_re)

    coll = df["Collection"].fillna("").str.strip()
    has_coll = coll != ""
    per_coll = (
        pd.DataFrame({"coll": coll, "state": state})
        .dropna(subset=["state"])
        .groupby("coll")["state"]
        .nunique()
    )

    geo = (coll.map(per_coll).astype(float) / n_states_ut).clip(upper=1.0)
    geo = geo.where(has_coll)
    geo = geo.mask(is_national, 0.5)
    geo = geo.mask(state_wise, 1.0)

    # Report the state count only where a collection exists, or rows without one
    # inherit the empty-string group's tally.
    return geo, state, coll.map(per_coll).where(has_coll)


def parse_state(spatial):
    """State/UT is the token before the trailing 'India'.

    'Bihar, Nalanda, Bihar, India' -> 'Bihar'; bare 'India' -> None (national,
    not attributable to one state).
    """
    if not isinstance(spatial, str):
        return None
    parts = [p.strip() for p in spatial.split(",") if p.strip()]
    if len(parts) < 2 or parts[-1].lower() != "india":
        return None
    return parts[-2]


def dataset_last_date(df, min_start_year):
    """The last date the DATA itself covers, from the most precise source there is.

    In precedence order:

      1. `data_end_raw` -- the portal's own data_time_period_to. Not present in
         this export at all, so on this workbook the rule always falls through.
      2. the end of a `YYYY-MM-DD/YYYY-MM-DD` Temporal Coverage interval. Also a
         full date, so it is used as-is. This table's Temporal Coverage is the
         `start:/end:` form, so this too is normally a miss here.
      3. the end YEAR of a `start:YYYY;end:YYYY` Temporal Coverage, read as 31
         December of that year -- the last date a dataset labelled that year
         could cover. Charitable by up to a year on purpose: this is the
         fallback that keeps the rule alive on the year-granularity tables, and
         reading it as 1 January would invent staleness the metadata never
         claimed.

    Ends before `min_start_year` are parse artifacts rather than history -- the
    same guard `signal_temporal` puts on starts -- and are dropped, so the row
    falls back to its Date Modified instead of being scored maximally stale off
    a bad parse.
    """
    tc = as_text(df["temporal_raw"]).str.strip()

    explicit = to_naive_datetime(df["data_end_raw"])
    interval_end = to_naive_datetime(tc.str.split("/", n=1).str[1])
    year_end = to_naive_datetime(
        tc.str.extract(r"end:(\d{4})", expand=False) + "-12-31"
    )

    end = explicit.fillna(interval_end).fillna(year_end)
    return end.mask(end.dt.year < min_start_year)


def freshness_date(df, min_start_year):
    """The date both freshness terms are measured from, per row, and why.

    `Date Modified` everywhere except the resource types in `dataset_date_types`
    -- external links, where the portal row is a pointer to a file on someone
    else's host and the modification date is the edit date of the POINTER, not
    of the data. Scoring those on the data's last date asks what was actually
    meant: is this data current.

    No row of this workbook is such a type, so every row here reports
    `metadata_modified`. `freshness_basis` in the output says which basis each
    row used, so this stays visible rather than assumed.
    """
    data_end = dataset_last_date(df, min_start_year)
    prefer_data = df["resource_type"].isin(dataset_date_types)
    use_data = prefer_data & data_end.notna()

    date = df["date_modified"].mask(use_data, data_end)

    # Last write wins, so the order is precedence lowest-first.
    basis = pd.Series("metadata_modified", index=df.index)
    basis[prefer_data] = "no_dataset_date"
    basis[use_data] = "dataset_last_date"
    return date, data_end, basis


def signal_liveness(dates, as_of, half_life):
    """Exponential decay on days since last refresh: 0.5 ** (days/half_life).

    Decay rather than min-max because the age distribution is not spread out:
    the bulk of this data was modified years ago, so min-max would hand almost
    the whole [0,1] range to distinctions inside the stale bulk and crowd the
    live tail at the top. Decay is absolute, so the live rows separate cleanly.

    Rows dated after `as_of` (clock skew, scoring against a past date, or a
    dataset whose data runs into the future) saturate at 1.0 rather than scoring
    above it.
    """
    days = (pd.Timestamp(as_of) - dates).dt.days
    live = np.power(0.5, days / half_life)
    return live.clip(upper=1.0).where(dates.notna()), days


def signal_punctuality(days_stale, df):
    """Did this refresh inside its own declared period? 1.0 yes, 0.0 no, NaN n/a.

    Binary, not graded, because liveness already carries how-stale as a gradient
    -- grading this too would just double-count it. Late is a hard 0 rather than
    NaN on purpose: a monthly dataset that missed its month is real evidence,
    not absent evidence.

    Gated on field_from_api. A dataset nobody promised to auto-refresh should
    not be marked down for not auto-refreshing; those rows score NaN and their
    weight redistributes across the other four signals.

    ON THIS WORKBOOK THAT GATE IS CLOSED FOR EVERY ROW: field_from_api is '0'
    throughout, so punctuality is NaN on all 206,972 rows and the whole 0.15
    redistributes. The run summary prints the flag tally, where this shows up as
    `not_from_api` = 206,972 rather than being silently absent.
    """
    # NaN here means "not auditable" and must stay NaN -- `fillna` would quietly
    # turn unauditable rows into scored (mostly late) ones. The floor only
    # applies to cadences that ARE mapped.
    expected = df["cadence"].map(cadence_days)
    expected = expected.where(expected.isna(), expected.clip(lower=run_interval_days))

    token = df["from_api"].str.lower()
    is_api = token.isin(api_true)
    is_blank = token.isin(api_blank)
    has_date = days_stale.notna()
    scored = is_api & has_date & expected.notna()

    punctual = pd.Series(np.nan, index=df.index)
    punctual[scored] = (days_stale[scored] <= expected[scored]).astype(float)

    # Why the check did or did not apply, so a 0 (missed its window) never gets
    # read as a NaN (did not apply) in the CSV.
    #
    # These are mask overwrites, not an if/elif chain: the LAST write wins, so
    # the order below is precedence lowest-first. Effective precedence is
    # on_time/late > from_api_blank > not_from_api > no_modified_date >
    # cadence_not_auditable -- i.e. a row that is not API-fed reads as
    # `not_from_api` even if it also has no date, because that is the more
    # informative reason. Reordering these lines changes which reason surfaces.
    flag = pd.Series("cadence_not_auditable", index=df.index)
    flag[~has_date] = "no_modified_date"
    flag[~is_api & ~is_blank] = "not_from_api"
    flag[is_blank] = "from_api_blank"
    flag[scored] = np.where(punctual[scored] == 1.0, "on_time", "late")

    return punctual, expected, flag


def combine(sig):
    """Weighted sum, with a missing signal's weight redistributed proportionally."""
    w = pd.DataFrame(
        {k: np.where(sig[k].notna(), weights[k], 0.0) for k in weights},
        index=sig.index,
    )
    total = w.sum(axis=1)
    contrib = sum(w[k] * sig[k].fillna(0.0) for k in weights)
    return (contrib / total).where(total > 0)


# ------------------------------------------------------------------- main ----

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--xlsx", default=default_xlsx,
                   help=f"Workbook to score (default: {default_xlsx}, or $HVD_XLSX)")
    p.add_argument("--sheet", default=default_sheet,
                   help=f"Worksheet holding the data (default: {default_sheet})")
    p.add_argument("--out", default=default_out)
    p.add_argument("--cache-dir", default=default_cache_dir,
                   help="Where the Parquet decode cache lives "
                        f"(default: {default_cache_dir})")
    p.add_argument("--no-cache", action="store_true",
                   help="Decode the workbook every run; do not read or write the cache")
    p.add_argument("--refresh-cache", action="store_true",
                   help="Re-decode the workbook and overwrite its cache entry")
    p.add_argument("--as-of", default=str(date.today()))
    p.add_argument("--ministry-departments", nargs="+", default=None,
                   help="Restrict to these ministry_department values (exact match)")
    p.add_argument("--limit", type=int, default=None,
                   help="Score at most N rows (applied after "
                        "--ministry-departments and before --api-only). For "
                        "smoke tests: signals and a percentile cut are normalised "
                        "over the rows loaded, so scores are not comparable to a "
                        "full run")
    p.add_argument("--api-only", action="store_true",
                   help="Score only API-fed rows (field_from_api in "
                        f"{sorted(api_true)}). NOTE: field_from_api is '0' on "
                        "every row of dublin_core_metadata.xlsx, so this selects "
                        "nothing there and is rejected up front")
    p.add_argument("--cut-mode", choices=("percentile", "absolute"), default="percentile",
                   help="How to pick candidates. 'absolute' is the prod setting: a "
                        "percentile cut cannot move in aggregate, so the candidate "
                        "count would never change month to month")
    p.add_argument("--cut-value", type=float, default=10.0,
                   help="Top N%% for percentile mode (computed over the rows actually "
                        "loaded, so --ministry-departments and --api-only both move it), "
                        "or the score threshold for absolute mode")
    p.add_argument("--clip-pct", type=float, default=99.0,
                   help="Winsorise signal upper tails at this percentile")
    p.add_argument("--half-life", type=float, default=half_life_days,
                   help="Days after which liveness halves")
    p.add_argument("--min-start-year", type=int, default=1950,
                   help="Temporal starts before this are treated as unparseable. "
                        "Doubles as the floor on a dataset's own end date")
    args = p.parse_args()

    if args.limit is not None and args.limit < 1:
        p.error("--limit must be a positive integer")
    if not Path(args.xlsx).exists():
        raise SystemExit(f"No such workbook: {args.xlsx}")

    df = load(args.xlsx, args.sheet, args.cache_dir,
              use_cache=not args.no_cache, refresh=args.refresh_cache,
              ministries=args.ministry_departments, limit=args.limit)

    if args.api_only:
        df = df[df["from_api"].str.lower().isin(api_true)].reset_index(drop=True)
        if df.empty:
            raise SystemExit(
                "--api-only selected 0 rows: field_from_api is not one of "
                f"{sorted(api_true)} on any row of this workbook (it is '0' "
                "throughout dublin_core_metadata.xlsx).\n"
                "Drop --api-only -- punctuality is gated on the same field "
                "anyway, so those rows already score it NaN."
            )

    print(f"Scoring {len(df):,} rows from {Path(args.xlsx).name}"
          + (f" (--limit {args.limit})" if args.limit else "")
          + (" (API-fed rows only)" if args.api_only else ""))
    if df.empty:
        raise SystemExit("Nothing to score.")

    demand, months, dcount, dcount_source = signal_demand(
        df, args.as_of, args.clip_pct)
    temporal, depth, temporal_flag = signal_temporal(
        df, args.clip_pct, args.min_start_year)
    geo, state, coll_states = signal_geo(df)
    fresh_date, data_end, freshness_basis = freshness_date(df, args.min_start_year)
    liveness, days_stale = signal_liveness(fresh_date, args.as_of, args.half_life)
    punctuality, expected, punctuality_flag = signal_punctuality(days_stale, df)

    sig = pd.DataFrame({
        "demand": demand, "temporal": temporal, "geo": geo,
        "liveness": liveness, "punctuality": punctuality,
    })
    score = combine(sig)

    # How much evidence a score rests on. Weight redistribution means a row with
    # one saturated signal can score high on thin evidence; this surfaces the
    # thinness for the reviewer rather than suppressing it.
    n_signals = sig.notna().sum(axis=1)
    signals_present = sig.notna().apply(
        lambda r: "+".join(c for c in sig.columns if r[c]) or "none", axis=1
    )

    if args.cut_mode == "absolute":
        cut = args.cut_value
    else:
        cut = np.nanpercentile(score, 100 - args.cut_value)

    out = pd.DataFrame({
        "nid": df["nid"],
        "Title": df["Title"],
        "Collection": df["Collection"],
        "ministry": df[ministry_col],
        "resource_type": df["resource_type"],
        "downloads": pd.to_numeric(df["ogdp_download_count"], errors="coerce"),
        "views": pd.to_numeric(df["ogdp_view_count"], errors="coerce"),
        "api_requests": pd.to_numeric(df["request_count_raw"], errors="coerce"),
        "demand_count": dcount,
        "demand_count_source": dcount_source,
        "date_issued": df["date_issued"],
        "months_since_issue": months.round(1),
        "date_modified": df["date_modified"],
        "date_dataset_end": data_end,
        "date_freshness": fresh_date,
        "freshness_basis": freshness_basis,
        "days_since_freshness": days_stale,
        "declared_cadence": df["cadence"],
        "expected_period_days": expected,
        "field_from_api": df["from_api"],
        "punctuality_flag": punctuality_flag,
        "temporal_span_years": depth,
        "temporal_flag": temporal_flag,
        "state_ut": state,
        "collection_states_covered": coll_states,
        "hvd_demand": demand.round(4),
        "hvd_temporal": temporal.round(4),
        "hvd_geo": geo.round(4),
        "hvd_liveness": liveness.round(4),
        "hvd_punctuality": punctuality,
        "hvd_score": score.round(4),
        "hvd_candidate": (score >= cut).astype(int),
        "n_signals": n_signals,
        "signals_present": signals_present,
    }).sort_values(["hvd_score", "n_signals"], ascending=[False, False])

    out.to_csv(args.out, index=False)

    print("\nSignal availability (missing -> weight redistributed):")
    for k in weights:
        n = int(sig[k].notna().sum())
        print(f"  {k:12s} {n:6d}/{len(df)}  ({100 * n / len(df):5.1f}%)")

    print("\nResource-type rules (demand count / freshness date):")
    for name, s in (("demand count", dcount_source), ("freshness", freshness_basis)):
        for f, n in s.value_counts().items():
            print(f"  {name:14s} {f:20s} {n:6d}")
    on_req = dcount_source == "api_requests"
    if on_req.any():
        dl = dcount[dcount_source == "downloads"].dropna()
        rq = dcount[on_req].dropna()
        if len(dl) and len(rq):
            print(f"  scale check    downloads median {dl.median():.0f}, "
                  f"p99 {np.nanpercentile(dl, 99):.0f}  |  requests median "
                  f"{rq.median():.0f}, max {rq.max():.0f}")

    print("\nPunctuality:")
    for f, n in punctuality_flag.value_counts().items():
        print(f"  {f:24s} {n:6d}")

    print("\nScore distribution:")
    print(score.describe().round(4).to_string())

    print(f"\n{args.cut_mode} cut = {cut:.4f} -> "
          f"{int(out['hvd_candidate'].sum())} candidates")

    print("\nEvidence depth of candidates:")
    cand = out[out.hvd_candidate == 1]
    for combo, n in cand["signals_present"].value_counts().items():
        print(f"  {combo:48s} {n:5d}  ({100 * n / len(cand):5.1f}%)")

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
