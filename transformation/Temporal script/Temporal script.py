import polars as pl
import pandas as pd
import boto3
import re
import warnings
import os

from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

# =========================================================
# CONFIG
# =========================================================

BUCKET_NAME = "nic-ogdp-datasets"

PREFIX = "downloaded-datasets/downloaded-datasets-mohfw/batch_42/"

OUTPUT_FILE = "temptest.xlsx"

MAX_WORKERS = 8
MAX_ROWS = 5000
SAVE_INTERVAL = 100

s3 = boto3.client("s3")

# =========================================================
# REGEX
# =========================================================

YEAR_RANGE_REGEX = re.compile(
    r"(18\d{2}|19\d{2}|20\d{2})\s*[-–]\s*(\d{2,4})"
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
# YEAR EXTRACTION
# =========================================================

def extract_years(val):

    try:

        val = str(val).strip()

        # remove brackets
        val = re.sub(r"\(.*?\)", "", val)

        # -------------------------------------------------
        # VALID YEAR RANGE
        # -------------------------------------------------

        CURRENT_MAX_YEAR = 2035
        MIN_YEAR = 1800

        # -------------------------------------------------
        # STRICT YEAR RANGE MATCH
        # prevents matching inside long numbers
        # -------------------------------------------------

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

            # ---------------------------------------------
            # HANDLE 2020-21
            # ---------------------------------------------

            if len(end_raw) == 2:

                end = int(
                    str(start)[:2] + end_raw
                )

            else:

                end = int(end_raw)

            # ---------------------------------------------
            # VALIDATE YEAR RANGE
            # ---------------------------------------------

            if (

                MIN_YEAR <= start <= CURRENT_MAX_YEAR
                and
                MIN_YEAR <= end <= CURRENT_MAX_YEAR

            ):

                return start, end

        # -------------------------------------------------
        # STANDALONE YEARS
        # STRICT BOUNDARY MATCH
        # -------------------------------------------------

        year_matches = re.findall(

            r"(?<!\d)"
            r"(18\d{2}|19\d{2}|20\d{2})"
            r"(?!\d)",

            val
        )

        if year_matches:

            years = []

            for y in year_matches:

                y = int(y)

                # -----------------------------------------
                # VALIDATE REALISTIC YEARS
                # -----------------------------------------

                if MIN_YEAR <= y <= CURRENT_MAX_YEAR:
                    years.append(y)

            if years:

                return min(years), max(years)

    except Exception:
        return None

    return None
# =========================================================
# COVERAGE
# =========================================================

def format_coverage(value):

    if value is None:
        return None

    return f"P{value}Y^^xsd:duration"


def calculate_coverage_from_years(years_list):

    years_list = sorted(set(years_list))

    if len(years_list) < 2:
        return None

    diffs = [

        years_list[i+1] - years_list[i]

        for i in range(
            len(years_list)-1
        )
    ]

    return min(diffs) if diffs else None

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
                if extract_years(v)

            )

            ratio = hits / len(values)

            if ratio > best_score:

                best_score = ratio
                best_col = col

        except Exception:
            continue

    return best_col if best_score > 0.5 else None

# =========================================================
# COMPUTE YEARS
# =========================================================

def compute_from_column(df, col):

    global_min = None
    global_max = None

    values = (
        df[col]
        .drop_nulls()
        .to_list()[:MAX_ROWS]
    )

    values = [

        v for v in values
        if is_valid_value(v)

    ]

    years_list = []

    for v in values:

        yr = extract_years(v)

        if yr:

            s, e = yr

            years_list.extend([s, e])

            global_min = (
                s if global_min is None
                else min(global_min, s)
            )

            global_max = (
                e if global_max is None
                else max(global_max, e)
            )

    coverage_raw = (
        calculate_coverage_from_years(
            years_list
        )
    )

    coverage = format_coverage(
        coverage_raw
    )

    return global_min, global_max, coverage


def compute_from_headers(df):

    global_min = None
    global_max = None

    years_list = []

    for col in df.columns:

        yr = extract_years(col)

        if yr:

            s, e = yr

            years_list.extend([s, e])

            global_min = (
                s if global_min is None
                else min(global_min, s)
            )

            global_max = (
                e if global_max is None
                else max(global_max, e)
            )

    coverage_raw = (
        calculate_coverage_from_years(
            years_list
        )
    )

    coverage = format_coverage(
        coverage_raw
    )

    return global_min, global_max, coverage

# =========================================================
# ANALYZE DATASET
# =========================================================

def analyze_dataset(df):

    if df is None or df.is_empty():
        return None, None, None

    df = remove_garbage_rows(df)

    if df is None or df.is_empty():
        return None, None, None

    date_col = find_date_column(df)

    if date_col:
        return compute_from_column(
            df,
            date_col
        )

    return compute_from_headers(df)

# =========================================================
# S3 LISTING
# =========================================================

def list_s3_files(bucket, prefix=""):

    paginator = s3.get_paginator(
        "list_objects_v2"
    )

    total = 0

    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=prefix
    ):

        contents = page.get("Contents", [])

        for obj in contents:

            total += 1

            yield obj["Key"]

    print(f"\n✅ TOTAL S3 FILES FOUND: {total}")

# =========================================================
# SMART FILE READER
# =========================================================

def read_file_from_s3(bucket, key):

    obj = s3.get_object(
        Bucket=bucket,
        Key=key
    )

    file_bytes = obj["Body"].read()

    extension = (
        key.lower()
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

                print(
                    f"✅ Excel read "
                    f"({engine}) → {key}"
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

                return pl.from_pandas(
                    tables[0]
                )

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

            print(
                f"✅ CSV read "
                f"({enc}) → {key}"
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

        raise Exception(
            f"FAILED TO READ: {key}\n{e}"
        )

# =========================================================
# HELPERS
# =========================================================

def extract_batch_name(key):

    parts = key.split("/")

    for part in parts:

        if part.lower().startswith("batch"):
            return part

    return "unknown"


def generate_s3_url(bucket, key):

    return (
        f"https://{bucket}.s3.amazonaws.com/{key}"
    )

# =========================================================
# PROCESS FILE
# =========================================================

def process_file(i, key):

    try:

        print(f"\n🔄 Processing {i}: {key}")

        df = read_file_from_s3(
            BUCKET_NAME,
            key
        )

        min_year, max_year, coverage = (
            analyze_dataset(df)
        )

        filename = os.path.basename(key)

        dataset_id = os.path.splitext(
            filename
        )[0]

        return {

            "dataset_id": dataset_id,

            "dataset": key,

            "batch_name":
                extract_batch_name(key),

            "file_url":
                generate_s3_url(
                    BUCKET_NAME,
                    key
                ),

            "min_year": min_year,

            "max_year": max_year,

            "coverage": coverage

        }

    except Exception as e:

        return {

            "dataset_id": os.path.splitext(
                os.path.basename(key)
            )[0],

            "dataset": key,

            "batch_name":
                extract_batch_name(key),

            "file_url":
                generate_s3_url(
                    BUCKET_NAME,
                    key
                ),

            "min_year": None,

            "max_year": None,

            "coverage": None,

            "error": str(e)
        }

# =========================================================
# SAVE
# =========================================================

def save_progress(results):

    pd.DataFrame(results).to_excel(
        OUTPUT_FILE,
        index=False
    )

    print(
        f"\n💾 Saved "
        f"{len(results)} records"
    )

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    results = []

    # -----------------------------------------------------
    # GET ALL S3 FILES
    # -----------------------------------------------------

    all_keys = list(

        list_s3_files(
            BUCKET_NAME,
            PREFIX
        )
    )

    print(
        f"\n📦 TOTAL S3 FILES: "
        f"{len(all_keys)}"
    )

    # -----------------------------------------------------
    # FILTER VALID FILE TYPES
    # -----------------------------------------------------

    keys = [

        k for k in all_keys

        if k.lower().endswith(

            (
                ".csv",
                ".xlsx",
                ".xls",
                ".xlsm",
                ".xlsb"
            )
        )
    ]

    print(
        f"✅ VALID FILES: "
        f"{len(keys)}"
    )

    # -----------------------------------------------------
    # PROCESS EVERYTHING
    # -----------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {

            executor.submit(
                process_file,
                i,
                key
            ): key

            for i, key in enumerate(
                keys,
                start=1
            )
        }

        for count, future in enumerate(
            as_completed(futures),
            start=1
        ):

            try:

                result = future.result()

            except Exception as e:

                result = {
                    "dataset": "unknown",
                    "error": str(e)
                }

            results.append(result)

            print(
                f"✅ Done: "
                f"{result.get('dataset_id')} "
                f"→ "
                f"{result.get('min_year')} "
                f"to "
                f"{result.get('max_year')}"
            )

            if count % SAVE_INTERVAL == 0:

                save_progress(results)

    # -----------------------------------------------------
    # FINAL SAVE
    # -----------------------------------------------------

    save_progress(results)

    print("\n🚀 FINAL OUTPUT GENERATED")