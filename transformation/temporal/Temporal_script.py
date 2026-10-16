import polars as pl
import pandas as pd
import duckdb
import re
import warnings
import os
import argparse
import calendar

from datetime import date
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

# =========================================================
# CONFIG
# =========================================================

# Local folder holding the downloaded datasets (named <uuid>.<ext>)
LOCAL_DIR = (
    "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/"
    "data/final_batch_downloads"
)

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

# NOTE: hyphenated table name -> MUST be double-quoted in every SQL string
TABLE_NAME = "remaining-raw-datasets"
UUID_COL = "uuid"
TITLE_COL = "Title"
FROM_COL = "data_time_period_from"
TO_COL = "data_time_period_to"

VALID_EXT = (".csv", ".xls", ".xlsx", ".xlsm", ".xlsb")

MAX_WORKERS = 8
MAX_ROWS = 5000
SAVE_INTERVAL = 200

MIN_YEAR = 1800
MAX_YEAR = 2035

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
                    r"(?i)\b(total|sum|average)\b"
                )

                for col in df.columns

            ])

        ]).to_series()

        return df.filter(~mask)

    except Exception as e:

        print(f"[warn] Garbage filter failed: {e}")

        return df

# =========================================================
# YEAR EXTRACTION  (used only to DETECT the date column)
# =========================================================

def extract_years(val):

    try:

        val = str(val).strip()

        # remove brackets
        val = re.sub(r"\(.*?\)", "", val)

        range_pattern = re.compile(
            r"(?<!\d)"
            r"(18\d{2}|19\d{2}|20\d{2})"
            r"\s*[-–/]\s*"
            r"(\d{2,4})"
            r"(?!\d)"
        )

        match = range_pattern.search(val)

        if match:

            start = int(match.group(1))
            end_raw = match.group(2)

            if len(end_raw) == 2:
                end = int(str(start)[:2] + end_raw)
            else:
                end = int(end_raw)

            if (
                MIN_YEAR <= start <= MAX_YEAR
                and MIN_YEAR <= end <= MAX_YEAR
            ):
                return start, end

        year_matches = re.findall(
            r"(?<!\d)"
            r"(18\d{2}|19\d{2}|20\d{2})"
            r"(?!\d)",
            val
        )

        if year_matches:

            years = [
                int(y) for y in year_matches
                if MIN_YEAR <= int(y) <= MAX_YEAR
            ]

            if years:
                return min(years), max(years)

    except Exception:
        return None

    return None

# =========================================================
# DATE INTERVAL EXTRACTION
# Returns (start_date, end_date) as datetime.date objects, or None.
# Each cell may hold several date tokens (e.g. a range "A to B"); we
# collect every token's own interval and return (min start, max end).
# Granularity is honoured:
#   full date        -> that exact day
#   "Mon YYYY"       -> first .. last day of that month
#   fiscal "2020-21" -> Apr 1 .. Mar 31  (matches extract_coverage_from_title)
#   plain year       -> Jan 1 .. Dec 31
# =========================================================

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_MONTH_ALT = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember|t)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_YEAR = r"(18\d{2}|19\d{2}|20\d{2})"

# 1) ISO / year-first full date: 2015-07-24, 2015/07/24
_P_ISO = re.compile(rf"(?<!\d){_YEAR}[-/](\d{{1,2}})[-/](\d{{1,2}})(?!\d)")
# 2) day-first with dash/dot: 24-05-2017, 08.11.2021, 19.01.2018
_P_DMY_DOT = re.compile(rf"(?<!\d)(\d{{1,2}})[-.](\d{{1,2}})[-.]{_YEAR}(?!\d)")
# 2b) slash, year-last: 9/24/2021, 12/30/2013 (month-first / US-style here)
_P_MDY_SLASH = re.compile(rf"(?<!\d)(\d{{1,2}})/(\d{{1,2}})/{_YEAR}(?!\d)")
# 3) day + month-name + year: "26-Sep-2013", "1 May 2023", "16th July 2021"
_P_DMON_Y = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+({_MONTH_ALT})(?![a-z])[\s\-.,]+{_YEAR}(?!\d)"
)
# 4) month-name + year (month precision): "May, 2019", "Nov.2018", "April 2022"
_P_MON_Y = re.compile(rf"(?<![a-z])({_MONTH_ALT})(?![a-z])[\s.,'\-]*{_YEAR}(?!\d)")
# 5) fiscal range: 2020-21, 2005-2009 (hyphen / en-dash only, like the sibling)
_P_FISCAL = re.compile(rf"(?<!\d){_YEAR}\s*[-–]\s*(\d{{2,4}})(?!\d)")
# 6) bare 4-digit year
_P_YEAR = re.compile(rf"(?<!\d){_YEAR}(?!\d)")


def _valid_ymd(y, m, d):
    return (
        MIN_YEAR <= y <= MAX_YEAR
        and 1 <= m <= 12
        and 1 <= d <= calendar.monthrange(y, m)[1]
    )


def _month_bounds(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _full_end_year(y1, y2_raw):
    """Expand a fiscal range end token to a full 4-digit year with century
    rollover: "2015"+"16" -> 2016 ; "2009"+"10" -> 2010 ; "1999"+"00" -> 2000.
    A 4-digit end token is used as-is. (Mirrors extract_coverage_from_title.)"""
    if len(y2_raw) == 4:
        return int(y2_raw)
    end = (y1 // 100) * 100 + int(y2_raw)
    if end <= y1:
        end += 100
    return end


def extract_date_interval(val, _keep_parens=False):

    s = str(val).strip()

    if not s:
        return None

    if _keep_parens:
        s = s.lower()
    else:
        # drop parentheticals so a fiscal year stays primary and "as on ..."
        # currency notes don't pull the boundary, e.g. "2024-25 (as on 31-12-2024)"
        stripped = re.sub(r"\(.*?\)", " ", s)
        # ...but if the ONLY date lives inside the brackets ("NFHS-4 (2015-16)"),
        # stripping loses it entirely -> retry on the original below.
        if not _P_YEAR.search(stripped) and _P_YEAR.search(s):
            return extract_date_interval(val, _keep_parens=True)
        s = stripped.lower()

    starts = []
    ends = []
    work = [s]  # boxed so the nested helper can blank consumed spans

    def run(pattern, handler):
        text = work[0]
        blanks = None
        for m in pattern.finditer(text):
            res = handler(m)
            if res is None:
                continue
            starts.append(res[0])
            ends.append(res[1])
            if blanks is None:
                blanks = list(text)
            for k in range(m.start(), m.end()):
                blanks[k] = " "
        if blanks is not None:
            work[0] = "".join(blanks)

    def h_iso(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(y, mo, d):
            dt = date(y, mo, d)
            return dt, dt
        return None

    def h_dmy(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if mo > 12 and d <= 12:       # unambiguous -> it's really day/month
            d, mo = mo, d
        if _valid_ymd(y, mo, d):
            dt = date(y, mo, d)
            return dt, dt
        return None

    def h_mdy(m):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mo, d = a, b                  # slash defaults to month-first here
        if a > 12 and b <= 12:        # first is out of month range -> it's the day
            mo, d = b, a
        if _valid_ymd(y, mo, d):
            dt = date(y, mo, d)
            return dt, dt
        return None

    def h_dmon(m):
        d = int(m.group(1))
        mo = _MONTHS.get(m.group(2))
        y = int(m.group(3))
        if mo and _valid_ymd(y, mo, d):
            dt = date(y, mo, d)
            return dt, dt
        return None

    def h_mony(m):
        mo = _MONTHS.get(m.group(1))
        y = int(m.group(2))
        if mo and MIN_YEAR <= y <= MAX_YEAR:
            return _month_bounds(y, mo)
        return None

    def h_fiscal(m):
        y1 = int(m.group(1))
        end = _full_end_year(y1, m.group(2))
        if MIN_YEAR <= y1 <= MAX_YEAR and MIN_YEAR <= end <= MAX_YEAR:
            return date(y1, 4, 1), date(end, 3, 31)
        return None

    def h_year(m):
        y = int(m.group(1))
        if MIN_YEAR <= y <= MAX_YEAR:
            return date(y, 1, 1), date(y, 12, 31)
        return None

    # priority order: most specific (full date) -> least (bare year)
    run(_P_ISO, h_iso)
    run(_P_DMY_DOT, h_dmy)
    run(_P_MDY_SLASH, h_mdy)
    run(_P_DMON_Y, h_dmon)
    run(_P_MON_Y, h_mony)
    run(_P_FISCAL, h_fiscal)
    run(_P_YEAR, h_year)

    if not starts:
        return None

    return min(starts), max(ends)

# =========================================================
# FIND DATE COLUMN
# =========================================================

# A column's cells are trusted as dates only if its header NAMES a time field.
# Counts land in 1800-2035 all the time ("No. of Registrations" -> 1809), so a
# high year-hit ratio alone is not evidence.
_TEMPORAL_HEADER = re.compile(
    r"(?i)(^|[^a-z])(year|yr|date|month|period|quarter|fy|financial\s*year|"
    r"as\s*on|as\s*at|time|week|day)([^a-z]|$)"
)
# ...but a header that carries its OWN period token is a MEASURE for that period
# ("No. of Registrations - 2016-17"), so the date is in the header, not the cells.
_PERIOD_IN_HEADER = re.compile(r"(?<!\d)(18|19|20)\d{2}(?!\d)")


def _header_is_temporal(col):
    name = str(col)
    if _PERIOD_IN_HEADER.search(name):
        return False
    return bool(_TEMPORAL_HEADER.search(name))


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
                if extract_years(v)
            )

            ratio = hits / len(values)

            if ratio > best_score:
                best_score = ratio
                best_col = col

        except Exception:
            continue

    if best_score <= 0.5:
        return None

    # reject count/label columns that merely LOOK year-ish
    if not _header_is_temporal(best_col):
        return None

    return best_col

# =========================================================
# COMPUTE FROM/TO (as dates)
# =========================================================

def compute_from_column(df, col):

    values = (
        df[col]
        .drop_nulls()
        .to_list()[:MAX_ROWS]
    )

    values = [
        v for v in values
        if is_valid_value(v)
    ]

    starts = []
    ends = []

    for v in values:
        iv = extract_date_interval(v)
        if iv:
            starts.append(iv[0])
            ends.append(iv[1])

    if not starts:
        return None, None

    return min(starts), max(ends)


def compute_from_headers(df):

    starts = []
    ends = []

    for col in df.columns:
        iv = extract_date_interval(col)
        if iv:
            starts.append(iv[0])
            ends.append(iv[1])

    if not starts:
        return None, None

    return min(starts), max(ends)

# =========================================================
# ANALYZE DATASET
# =========================================================

def analyze_dataset(df, title=None):

    if df is None or df.is_empty():
        return _from_title(title)

    original = df

    df = remove_garbage_rows(df)

    if df is None or df.is_empty():
        # every row looked like a total/subtotal line; headers survive it
        df = original

    date_col = find_date_column(df)

    if date_col:
        from_date, to_date = compute_from_column(df, date_col)
        if from_date:
            return from_date, to_date

    from_date, to_date = compute_from_headers(df)
    if from_date:
        return from_date, to_date

    # nothing in the contents -> the title is the last source
    return _from_title(title)


def _from_title(title):
    """Last resort: parse the dataset Title. Same conventions as the contents
    parser (fiscal 2014-18 -> Apr 1 2014 .. Mar 31 2018)."""
    if not title or not is_valid_value(title):
        return None, None
    iv = extract_date_interval(title)
    if not iv:
        return None, None
    return iv[0], iv[1]

# =========================================================
# LOCAL FILE LISTING
# =========================================================

def list_local_files(directory):

    files = []

    for name in os.listdir(directory):
        if name.lower().endswith(VALID_EXT):
            files.append(os.path.join(directory, name))

    print(f"TOTAL LOCAL FILES (valid types): {len(files)}")

    return files

# =========================================================
# SMART FILE READER (LOCAL PATH)
# =========================================================

def read_local_file(path):

    with open(path, "rb") as fh:
        file_bytes = fh.read()

    extension = (
        path.lower()
        .split(".")[-1]
        .strip()
    )

    # =====================================================
    # EXCEL FILES
    # =====================================================

    if extension in [
        "xls",
        "xlsx",
        "xlsm",
        "xlsb"
    ]:

        excel_engines = [
            "openpyxl",
            "xlrd",
            "pyxlsb"
        ]

        for engine in excel_engines:

            try:

                bio = BytesIO(file_bytes)

                df = pd.read_excel(
                    bio,
                    engine=engine,
                    dtype=str,
                    nrows=10000
                )

                return pl.from_pandas(df)

            except Exception:
                continue

        # fallback auto engine
        try:

            bio = BytesIO(file_bytes)

            df = pd.read_excel(
                bio,
                dtype=str,
                nrows=10000
            )

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

    # =====================================================
    # CSV FILES
    # =====================================================

    csv_encodings = [
        "utf-8",
        "utf-8-sig",
        "latin1",
        "cp1252",
        "ISO-8859-1"
    ]

    for enc in csv_encodings:

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

    # =====================================================
    # FINAL FALLBACK
    # =====================================================

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
# ISO FORMATTING
# =========================================================

def to_from_iso(d):
    return f"{d.isoformat()}T00:00:00" if d is not None else None


def to_to_iso(d):
    return f"{d.isoformat()}T23:59:59" if d is not None else None

# =========================================================
# DB: UUIDS WITHOUT TEMPORAL COVERAGE
# =========================================================

def get_uuids_without_temporal_coverage():

    con = duckdb.connect(DB_PATH, read_only=True)

    try:

        # not every target table carries a Title; fall back to NULL titles
        try:
            con.execute(f'SELECT "{TITLE_COL}" FROM "{TABLE_NAME}" LIMIT 0')
            title_select = f'"{TITLE_COL}"'
        except Exception:
            print(f"[warn] no {TITLE_COL!r} column on {TABLE_NAME} "
                  f"-> title fallback disabled")
            title_select = "NULL"

        rows = con.execute(
            f'''
            SELECT "{UUID_COL}", {title_select}
            FROM "{TABLE_NAME}"
            WHERE ("{FROM_COL}" IS NULL
                   OR TRIM("{FROM_COL}") = '')
              AND "{UUID_COL}" IS NOT NULL
            '''
        ).fetchall()

    finally:
        con.close()

    # uuid -> title, so the title fallback needs no extra round-trip per file
    return {str(r[0]): r[1] for r in rows}

# =========================================================
# PROCESS FILE
# =========================================================

def process_file(path, title=None):

    uuid = os.path.splitext(
        os.path.basename(path)
    )[0]

    try:

        df = read_local_file(path)

        from_date, to_date = analyze_dataset(df, title)

        return {
            "uuid": uuid,
            "path": path,
            "from_iso": to_from_iso(from_date),
            "to_iso": to_to_iso(to_date),
        }

    except Exception as e:

        f, t = _from_title(title)
        return {
            "uuid": uuid,
            "path": path,
            "from_iso": to_from_iso(f),
            "to_iso": to_to_iso(t),
            "error": str(e),
        }

# =========================================================
# SAVE (write-and-clear buffer)
# =========================================================

def save_progress(buffer):

    # Keep only rows where we actually detected temporal coverage
    updates = [
        {
            "uuid": r["uuid"],
            "dfrom": r["from_iso"],
            "dto": r["to_iso"],
        }
        for r in buffer
        if r.get("from_iso") and r.get("to_iso")
    ]

    if not updates:
        return 0

    df = pd.DataFrame(updates)

    con = duckdb.connect(DB_PATH)

    try:

        con.register("updates", df)

        con.execute(
            f'''
            UPDATE "{TABLE_NAME}" AS d
            SET "{FROM_COL}" = u.dfrom,
                "{TO_COL}"   = u.dto
            FROM updates AS u
            WHERE d."{UUID_COL}" = u.uuid
            '''
        )

        con.unregister("updates")

    finally:
        con.close()

    return len(updates)

# =========================================================
# DRY RUN PREVIEW
# =========================================================

def run_dry(paths, sample_cap=500, show=40, titles=None):
    titles = titles or {}

    print(
        f"\nDRY RUN - scanning up to {sample_cap} files, "
        f"showing up to {show} detected (nothing written)\n"
    )

    scanned = 0
    shown = 0

    for path in paths:

        if scanned >= sample_cap or shown >= show:
            break

        scanned += 1

        uuid_ = os.path.splitext(os.path.basename(path))[0]

        try:
            df = read_local_file(path)
        except Exception:
            df = None

        if df is None or df.is_empty():
            tf, tt = _from_title(titles.get(uuid_))
            if tf:
                shown += 1
                print(f"[{shown}] {uuid_}  (title, unreadable file)")
                print(f"     parsed: {to_from_iso(tf)}  ..  {to_to_iso(tt)}")
                print(f"     raw:    {str(titles.get(uuid_))[:70]!r}")
            continue

        df2 = remove_garbage_rows(df)

        if df2 is None or df2.is_empty():
            df2 = df

        col = find_date_column(df2)

        if col:
            vals = [
                v for v in df2[col].drop_nulls().to_list()
                if is_valid_value(v)
            ][:MAX_ROWS]
            source = f"col={col!r}"
            raw = list(dict.fromkeys(str(x) for x in vals))[:6]
            starts, ends = [], []
            for v in vals:
                iv = extract_date_interval(v)
                if iv:
                    starts.append(iv[0])
                    ends.append(iv[1])
        else:
            source = "headers"
            raw = list(df2.columns)[:6]
            starts, ends = [], []
            for c in df2.columns:
                iv = extract_date_interval(c)
                if iv:
                    starts.append(iv[0])
                    ends.append(iv[1])

        uuid = os.path.splitext(os.path.basename(path))[0]

        if not starts:
            # same last resort the real run uses
            tf, tt = _from_title(titles.get(uuid))
            if not tf:
                continue
            starts, ends = [tf], [tt]
            source = "title"
            raw = [str(titles.get(uuid))[:70]]

        shown += 1
        f_iso = to_from_iso(min(starts))
        t_iso = to_to_iso(max(ends))

        print(f"[{shown}] {uuid}  ({source})")
        print(f"     parsed: {f_iso}  ..  {t_iso}")
        print(f"     raw:    {raw}")

    print(
        f"\nScanned {scanned} files, {shown} had detectable temporal "
        f"coverage. Nothing written."
    )

# =========================================================
# MAIN
# =========================================================

def main():

    global TABLE_NAME, UUID_COL

    parser = argparse.ArgumentParser(
        description=(
            "Extract temporal coverage from locally-downloaded datasets "
            "and write data_time_period_from/to onto remaining-raw-datasets."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview detected from/to pairs for a sample; write nothing."
    )
    parser.add_argument(
        "--table",
        default=TABLE_NAME,
        help=f"Target table to update (default {TABLE_NAME})."
    )
    parser.add_argument(
        "--uuid-col",
        default=UUID_COL,
        help=f"Column holding the file UUID (default {UUID_COL})."
    )
    parser.add_argument(
        "--sample-cap",
        type=int,
        default=500,
        help="Dry-run: max files to scan (default 500)."
    )
    args = parser.parse_args()

    TABLE_NAME = args.table
    UUID_COL = args.uuid_col

    print(f"TARGET: {TABLE_NAME} (uuid column: {UUID_COL})")

    # -----------------------------------------------------
    # LIST LOCAL FILES
    # -----------------------------------------------------

    all_files = list_local_files(LOCAL_DIR)

    # -----------------------------------------------------
    # ONLY KEEP UUIDS THAT HAVE NO TEMPORAL COVERAGE YET
    # (filename without extension == uuid)
    # -----------------------------------------------------

    titles = get_uuids_without_temporal_coverage()
    empty_uuids = set(titles)

    print(f"UUIDs without temporal coverage in DB: {len(empty_uuids)}")

    paths = [
        p for p in all_files
        if os.path.splitext(os.path.basename(p))[0] in empty_uuids
    ]

    print(f"FILES TO PROCESS (local file + missing coverage): {len(paths)}")

    # -----------------------------------------------------
    # DRY RUN
    # -----------------------------------------------------

    if args.dry_run:
        run_dry(paths, sample_cap=args.sample_cap, titles=titles)
        return

    # -----------------------------------------------------
    # PROCESS EVERYTHING
    # writes happen on the MAIN thread only (workers read files)
    # -----------------------------------------------------

    pending = []
    total_processed = 0
    total_written = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = {
            executor.submit(
                process_file,
                path,
                titles.get(os.path.splitext(os.path.basename(path))[0]),
            ): path
            for path in paths
        }

        for count, future in enumerate(as_completed(futures), start=1):

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "uuid": None,
                    "from_iso": None,
                    "to_iso": None,
                    "error": str(e),
                }

            pending.append(result)
            total_processed += 1

            if count % SAVE_INTERVAL == 0:

                written = save_progress(pending)
                total_written += written
                pending = []  # clear the buffer after flushing

                print(
                    f"Progress: processed {total_processed}/{len(paths)} "
                    f"| written so far {total_written}"
                )

    # -----------------------------------------------------
    # FINAL FLUSH
    # -----------------------------------------------------

    total_written += save_progress(pending)

    print(
        f"\nDONE - processed {total_processed} files, "
        f"wrote temporal coverage for {total_written} datasets "
        f"into {TABLE_NAME}"
    )


if __name__ == "__main__":
    main()
