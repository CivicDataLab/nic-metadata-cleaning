import polars as pl
import pandas as pd
import re
import calendar
import warnings
import os

from io import BytesIO
from datetime import date

warnings.filterwarnings("ignore")

# =========================================================
# CONFIG
# =========================================================

# Download log written by aikosh_dataset_download.py (columns: nid,status,detail).
# We iterate the nids logged as 'success' here instead of an input metadata CSV.
LOG_FILE = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/aikosh_download_log.csv"

# Folder where the datasets were downloaded as {nid}.{ext}
DOWNLOADS_FOLDER = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/aikosh_downloads"

# Fresh output CSV: nid, from_date, to_date (ISO 8601)
OUTPUT_CSV = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/aikosh_temporal.csv"

NID_COL = "nid"
MIN_COL = "from_date"   # min date (ISO 8601) goes here
MAX_COL = "to_date"     # max date (ISO 8601) goes here

MAX_ROWS = 5000

MIN_YEAR = 1800
MAX_YEAR = 2035

# Month name -> number (matched by first 3 letters, all unique)
MONTH3 = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_PAT = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
)

# =========================================================
# VALID VALUE
# =========================================================

def is_valid_value(val):

    val = str(val).strip().lower()

    return val not in [
        "",
        "nan",
        "null",
        "none",
        "na"
    ]

# =========================================================
# REMOVE GARBAGE ROWS
# =========================================================

def remove_garbage_rows(df):

    if df is None or df.is_empty():
        return df

    try:

        df = df.with_columns([

            pl.col(col).cast(
                pl.Utf8,
                strict=False
            )

            for col in df.columns
        ])

        mask = df.select([

            pl.any_horizontal([

                pl.col(col)
                .str.contains(
                    "(?i)total|sum|average"
                )

                for col in df.columns

            ])

        ]).to_series()

        return df.filter(~mask)

    except Exception as e:

        print(f"⚠️ Garbage filter failed: {e}")

        return df

# =========================================================
# DATE RANGE EXTRACTION
#
# Understands, in this priority order:
#   - Fiscal year          2011-12 / 2011-2012  -> 01 Apr 2011 .. 31 Mar 2012
#   - Multi-year range      1999-2003           -> 01 Jan 1999 .. 31 Dec 2003
#   - Month + year          Jan 2017 / March-2014 -> 01 .. last-day of that month
#   - Standalone year       2019                -> 01 Jan 2019 .. 31 Dec 2019
# Returns (min_start_date, max_end_date) covering everything found, or None.
# =========================================================

def _valid_year(y):
    return MIN_YEAR <= y <= MAX_YEAR


def _last_day(year, month):
    return calendar.monthrange(year, month)[1]


def extract_date_range(val):

    try:

        s = str(val).strip()

        # drop bracketed noise e.g. "(Base 2004-05 = 100)"
        s = re.sub(r"\(.*?\)", "", s)

        starts = []
        ends = []

        # -------------------------------------------------
        # 1) FISCAL YEAR / YEAR RANGE  (consumes the match)
        #    YYYY-YY or YYYY-YYYY
        # -------------------------------------------------

        fy_pat = re.compile(
            r"(?<!\d)"
            r"(18\d{2}|19\d{2}|20\d{2})"
            r"\s*[-–/]\s*"
            r"(\d{2,4})"
            r"(?!\d)"
        )

        def fy_sub(m):

            y1 = int(m.group(1))
            raw = m.group(2)

            # 2-digit end -> take century from start (2011-12 -> 2012)
            if len(raw) == 2:
                y2 = int(str(y1)[:2] + raw)
            else:
                y2 = int(raw)

            if not (_valid_year(y1) and _valid_year(y2) and y2 > y1):
                return m.group(0)

            if y2 == y1 + 1:
                # consecutive years -> fiscal year (Apr..Mar)
                starts.append(date(y1, 4, 1))
                ends.append(date(y2, 3, 31))
            else:
                # wider span -> calendar range
                starts.append(date(y1, 1, 1))
                ends.append(date(y2, 12, 31))

            return " "  # consume so the years are not re-detected below

        s = fy_pat.sub(fy_sub, s)

        # -------------------------------------------------
        # 2) MONTH + YEAR  (consumes the match)
        # -------------------------------------------------

        my_pat = re.compile(
            r"(?<![a-z])(" + MONTH_PAT + r")[ ,\-/]+((?:18|19|20)\d{2})(?!\d)",
            re.I
        )

        def my_sub(m):

            mon = MONTH3[m.group(1).lower()[:3]]
            yr = int(m.group(2))

            if _valid_year(yr):
                starts.append(date(yr, mon, 1))
                ends.append(date(yr, mon, _last_day(yr, mon)))
                return " "

            return m.group(0)

        s = my_pat.sub(my_sub, s)

        # -------------------------------------------------
        # 3) STANDALONE YEARS (whatever is left)
        # -------------------------------------------------

        for ym in re.findall(
            r"(?<!\d)(18\d{2}|19\d{2}|20\d{2})(?!\d)",
            s
        ):

            y = int(ym)

            if _valid_year(y):
                starts.append(date(y, 1, 1))
                ends.append(date(y, 12, 31))

        if starts and ends:
            return min(starts), max(ends)

    except Exception:
        return None

    return None

# =========================================================
# FIND DATE COLUMN
# =========================================================

def find_date_column(df):

    best_col = None
    best_score = 0

    for col in df.columns:

        try:

            values = (
                df[col]
                .drop_nulls()
                .to_list()[:2000]
            )

            values = [
                v for v in values
                if is_valid_value(v)
            ]

            if len(values) == 0:
                continue

            hits = sum(
                1 for v in values
                if extract_date_range(v)
            )

            ratio = hits / len(values)

            if ratio > best_score:

                best_score = ratio
                best_col = col

        except Exception:
            continue

    return best_col if best_score > 0.5 else None

# =========================================================
# COMPUTE DATE RANGE
# =========================================================

def _merge(gmin, gmax, rng):
    s, e = rng
    gmin = s if gmin is None else min(gmin, s)
    gmax = e if gmax is None else max(gmax, e)
    return gmin, gmax


def compute_from_column(df, col):

    gmin = None
    gmax = None

    values = (
        df[col]
        .drop_nulls()
        .to_list()[:MAX_ROWS]
    )

    values = [
        v for v in values
        if is_valid_value(v)
    ]

    for v in values:

        rng = extract_date_range(v)

        if rng:
            gmin, gmax = _merge(gmin, gmax, rng)

    return gmin, gmax


def compute_from_headers(df):

    gmin = None
    gmax = None

    for col in df.columns:

        rng = extract_date_range(col)

        if rng:
            gmin, gmax = _merge(gmin, gmax, rng)

    return gmin, gmax

# =========================================================
# ANNUAL HEALTH SURVEY (AHS) SPECIAL CASE
#
# AHS datasets carry a `year` column whose values are survey *rounds*, not
# calendar years: "Baseline", "First/Second/Third Updation Round", ...
# Each round maps to an Indian fiscal year (Apr..Mar):
#     Baseline               -> FY 2010-11  (2010-04-01 .. 2011-03-31)
#     First  Updation Round  -> FY 2011-12
#     Second Updation Round  -> FY 2012-13
#     Third  Updation Round  -> FY 2013-14  ... and so on
# A single file may contain several rounds, so we span min-round-start to
# max-round-end.  These files also have year_of_death / year_of_birth columns,
# so this MUST run before the generic year extraction (which would otherwise
# pick up birth/death years and produce a nonsense range).
# =========================================================

AHS_BASE_FY = 2010   # Baseline == fiscal year starting 2010

_ROUND_WORD_ORDINAL = {
    "baseline": 0,
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
}


def _round_ordinal(label):
    """Round label -> ordinal (Baseline=0, First=1, ...), or None if not a round."""
    s = str(label).strip().lower()
    if not s:
        return None
    if "baseline" in s:
        return 0
    for word, ordv in _ROUND_WORD_ORDINAL.items():
        if word in s:
            return ordv
    m = re.search(r"round\s*(\d+)", s)   # bare "round 2"
    if m:
        return int(m.group(1))
    return None


def ahs_date_range(df):
    """If df is an AHS-style dataset (a `year` column of survey rounds), return
    the (min_start, max_end) fiscal-year range covering every round present.
    Returns None when this is not AHS round data."""

    # Prefer a column literally named "year"; else fall back to any column whose
    # values look like round labels.
    candidates = [c for c in df.columns if str(c).strip().lower() == "year"]
    if not candidates:
        candidates = list(df.columns)

    for col in candidates:
        try:
            vals = df[col].drop_nulls().unique().to_list()
        except Exception:
            continue

        ordinals = [o for o in (_round_ordinal(v) for v in vals) if o is not None]
        if not ordinals:
            continue

        lo, hi = min(ordinals), max(ordinals)
        start = date(AHS_BASE_FY + lo, 4, 1)
        end = date(AHS_BASE_FY + hi + 1, 3, 31)
        return start, end

    return None

# =========================================================
# ANALYZE DATASET
# =========================================================

def analyze_dataset(df):

    if df is None or df.is_empty():
        return None, None

    # AHS round-based datasets first (their numeric year_* columns would
    # otherwise mislead the generic extractor).
    ahs = ahs_date_range(df)
    if ahs:
        return ahs

    df = remove_garbage_rows(df)

    if df is None or df.is_empty():
        return None, None

    date_col = find_date_column(df)

    if date_col:
        return compute_from_column(df, date_col)

    return compute_from_headers(df)

# =========================================================
# LOCAL FILE READER
# =========================================================

def read_file_local(path):

    with open(path, "rb") as f:
        file_bytes = f.read()

    extension = (
        path.lower()
        .split(".")[-1]
        .strip()
    )

    # EXCEL FILES
    if extension in ["xls", "xlsx", "xlsm", "xlsb"]:

        for engine in ["openpyxl", "xlrd", "pyxlsb"]:

            try:
                bio = BytesIO(file_bytes)
                df = pd.read_excel(bio, engine=engine, dtype=str, nrows=10000)
                return pl.from_pandas(df)
            except Exception:
                continue

        # fallback auto engine
        try:
            bio = BytesIO(file_bytes)
            df = pd.read_excel(bio, dtype=str, nrows=10000)
            return pl.from_pandas(df)
        except Exception:
            pass

        # html disguised as xls
        try:
            bio = BytesIO(file_bytes)
            tables = pd.read_html(bio)
            if tables:
                return pl.from_pandas(tables[0])
        except Exception:
            pass

    # CSV FILES
    for enc in ["utf-8", "utf-8-sig", "latin1", "cp1252", "ISO-8859-1"]:

        try:
            bio = BytesIO(file_bytes)
            df = pl.read_csv(
                bio,
                encoding=enc,
                ignore_errors=True,
                infer_schema_length=0,
                n_rows=10000
            )
            return df
        except Exception:
            continue

    # FINAL FALLBACK
    try:
        bio = BytesIO(file_bytes)
        df = pd.read_csv(
            bio,
            dtype=str,
            engine="python",
            encoding="latin1",
            nrows=10000,
            on_bad_lines="skip"
        )
        return pl.from_pandas(df)
    except Exception as e:
        raise Exception(f"FAILED TO READ: {path}\n{e}")

# =========================================================
# LOCATE THE DOWNLOADED FILE FOR A NID
# =========================================================

def find_downloaded_file(nid):
    """Return the path to {nid}.<ext> in DOWNLOADS_FOLDER, or None."""
    for fname in os.listdir(DOWNLOADS_FOLDER):
        if fname.split(".", 1)[0] == str(nid):
            return os.path.join(DOWNLOADS_FOLDER, fname)
    return None

# =========================================================
# MAIN
# =========================================================

def load_success_nids(log_path):
    """Return an ordered, de-duplicated list of nids logged as 'success'."""
    import csv

    nids = []
    seen = set()
    with open(log_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "success":
                continue
            nid = str(row.get("nid", "")).strip()
            if nid and nid.lower() != "nan" and nid not in seen:
                seen.add(nid)
                nids.append(nid)
    return nids


if __name__ == "__main__":

    import csv

    nids = load_success_nids(LOG_FILE)
    print(f"Success nids in log: {len(nids)}")

    filled = 0
    no_file = 0
    no_dates = 0

    with open(OUTPUT_CSV, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([NID_COL, MIN_COL, MAX_COL])

        for nid in nids:

            path = find_downloaded_file(nid)

            if path is None:
                no_file += 1
                print(f"❓ {nid}: logged success but no file on disk")
                continue

            try:
                df = read_file_local(path)
                min_date, max_date = analyze_dataset(df)
            except Exception as e:
                print(f"⚠️ {nid}: {e}")
                min_date, max_date = None, None

            if min_date is not None and max_date is not None:
                writer.writerow([nid, min_date.isoformat(), max_date.isoformat()])
                filled += 1
                print(f"✅ {nid} → {min_date.isoformat()} to {max_date.isoformat()}")
            else:
                writer.writerow([nid, "", ""])
                no_dates += 1
                print(f"➖ {nid}: no dates found")

    print("\n===== SUMMARY =====")
    print(f"Success nids processed : {len(nids)}")
    print(f"Rows with dates        : {filled}")
    print(f"No downloaded file     : {no_file}")
    print(f"File but no dates found: {no_dates}")
    print(f"Written to             : {OUTPUT_CSV}")
