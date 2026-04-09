# import pandas as pd
# import re
# import os
# import warnings
# warnings.filterwarnings("ignore")

# # =========================================================
# # CONFIG
# # =========================================================

# ENABLE_COLUMN_FILTER = True

# # =========================================================
# # REGEX
# # =========================================================

# STRONG_DATE_HEADER_REGEX = re.compile(
#     r"(date|time|timestamp|created|updated|start|end)",
#     re.IGNORECASE
# )

# TEMPORAL_HEADER_REGEX = re.compile(
#     r"(year|yr|fy|quarter|month|mon)",
#     re.IGNORECASE
# )

# NON_DATE_HEADER_REGEX = re.compile(
#     r"(id|code|number|qty|price|amount|total|zip|phone)",
#     re.IGNORECASE
# )

# YEAR_RANGE_REGEX = re.compile(r"(19\d{2}|20\d{2})\s*[-–]\s*(\d{2,4})")

# # =========================================================
# # CLEANING
# # =========================================================

# def remove_garbage_rows(df):
#     mask = df.astype(str).apply(
#         lambda row: row.str.contains(r"total|sum|average", case=False, na=False).any(),
#         axis=1
#     )
#     return df[~mask]

# # =========================================================
# # PARSERS
# # =========================================================

# def extract_years_from_text(val):
#     try:
#         val = str(val)

#         # remove brackets
#         val = re.sub(r"\(.*?\)", "", val)

#         # year range
#         match = YEAR_RANGE_REGEX.search(val)
#         if match:
#             start = int(match.group(1))
#             end_raw = match.group(2)

#             if len(end_raw) == 2:
#                 end = int(str(start)[:2] + end_raw)
#             else:
#                 end = int(end_raw)

#             return start, end

#         # single year
#         match = re.search(r"(19\d{2}|20\d{2})", val)
#         if match:
#             y = int(match.group(1))
#             return y, y

#     except:
#         return None

#     return None

# # =========================================================
# # FILE READERS
# # =========================================================

# def read_csv_safe(file_path):
#     for enc in ["utf-8", "latin1", "cp1252"]:
#         try:
#             return pd.read_csv(file_path, encoding=enc, dtype=str, low_memory=False)
#         except:
#             continue
#     raise Exception("Encoding failed")


# def read_excel_safe(file_path):
#     try:
#         return pd.read_excel(file_path, engine="openpyxl")
#     except:
#         try:
#             return pd.read_excel(file_path, engine="xlrd")
#         except:
#             return pd.read_excel(file_path)


# def read_file_smart(file_path):
#     if file_path.endswith((".xlsx", ".xls")):
#         try:
#             df = pd.read_excel(file_path, header=[0,1], engine="openpyxl")
#             df.columns = [
#                 "_".join([str(i) for i in col if str(i) != "nan"]).strip()
#                 for col in df.columns
#             ]
#             return df
#         except:
#             return read_excel_safe(file_path)
#     else:
#         return read_csv_safe(file_path)

# # =========================================================
# # MAIN DATASET ANALYSIS
# # =========================================================

# def analyze_dataset(df):

#     df = remove_garbage_rows(df)

#     global_min = None
#     global_max = None

#     for col in df.columns:

#         # ---- HEADER ----
#         yr = extract_years_from_text(col)
#         if yr:
#             s, e = yr
#             global_min = s if global_min is None else min(global_min, s)
#             global_max = e if global_max is None else max(global_max, e)

#         # ---- VALUES ----
#         values = df[col].dropna().astype(str).head(2000)

#         # column filter (important)
#         if ENABLE_COLUMN_FILTER:
#             hits = sum(1 for v in values if extract_years_from_text(v))
#             ratio = hits / len(values) if len(values) > 0 else 0

#             if ratio < 0.3:
#                 continue

#         for v in values:
#             yr = extract_years_from_text(v)
#             if yr:
#                 s, e = yr
#                 global_min = s if global_min is None else min(global_min, s)
#                 global_max = e if global_max is None else max(global_max, e)

#     return global_min, global_max

# # =========================================================
# # MAIN EXECUTION
# # =========================================================

# if __name__ == "__main__":

#     folder_path = r"C:\Users\HP\scrape\nic-metadata-cleaning\data\sample_downloaded_files"
#     output_file = os.path.join(folder_path, "dataset_temporal_coverage.xlsx")

#     results = []

#     for file in os.listdir(folder_path):

#         if not file.endswith((".csv", ".xlsx", ".xls")):
#             continue

#         try:
#             print(f"\nProcessing: {file}")

#             file_path = os.path.join(folder_path, file)
#             df = read_file_smart(file_path)

#             min_year, max_year = analyze_dataset(df)

#             print(f"Done: {file} → {min_year} to {max_year}")

#             results.append({
#                 "dataset": file,
#                 "min_year": min_year,
#                 "max_year": max_year
#             })

#         except Exception as e:
#             print(f"Error: {file} → {e}")

#             results.append({
#                 "dataset": file,
#                 "min_year": None,
#                 "max_year": None,
#                 "error": str(e)
#             })

#     pd.DataFrame(results).to_excel(output_file, index=False)

#     print("\nFINAL OUTPUT GENERATED 🚀")
# 
# import pandas as pd
# import re
# import os
# import warnings
# warnings.filterwarnings("ignore")

# # =========================================================
# # REGEX
# # =========================================================

# YEAR_RANGE_REGEX = re.compile(r"(18\d{2}|19\d{2}|20\d{2})\s*[-–]\s*(\d{2,4})")

# # =========================================================
# # CLEANING
# # =========================================================

# def remove_garbage_rows(df):
#     mask = df.astype(str).apply(
#         lambda row: row.str.contains(r"total|sum|average", case=False, na=False).any(),
#         axis=1
#     )
#     return df[~mask]

# # =========================================================
# # PARSER (UPDATED FOR 1800s)
# # =========================================================

# def extract_years(val):
#     try:
#         val = str(val)

#         # remove brackets
#         val = re.sub(r"\(.*?\)", "", val)

#         # YEAR RANGE (includes 1800s)
#         match = YEAR_RANGE_REGEX.search(val)
#         if match:
#             start = int(match.group(1))
#             end_raw = match.group(2)

#             if len(end_raw) == 2:
#                 end = int(str(start)[:2] + end_raw)
#             else:
#                 end = int(end_raw)

#             return start, end

#         # SINGLE / MULTIPLE YEARS (includes 1800s)
#         years = re.findall(r"(18\d{2}|19\d{2}|20\d{2})", val)

#         if years:
#             years = [int(y) for y in years]
#             return min(years), max(years)

#     except:
#         return None

#     return None

# # =========================================================
# # STEP 1: FIND DATE COLUMN
# # =========================================================

# def find_date_column(df):

#     best_col = None
#     best_score = 0

#     for col in df.columns:

#         values = df[col].dropna().astype(str).head(2000)

#         if len(values) == 0:
#             continue

#         hits = sum(1 for v in values if extract_years(v))
#         ratio = hits / len(values)

#         if ratio > best_score:
#             best_score = ratio
#             best_col = col

#     if best_score > 0.5:
#         return best_col

#     return None

# # =========================================================
# # STEP 2: COMPUTE FROM COLUMN (FULL DATA)
# # =========================================================

# def compute_from_column(df, col):

#     global_min = None
#     global_max = None

#     values = df[col].dropna().astype(str)

#     for v in values:

#         yr = extract_years(v)

#         if yr:
#             s, e = yr

#             global_min = s if global_min is None else min(global_min, s)
#             global_max = e if global_max is None else max(global_max, e)

#     return global_min, global_max

# # =========================================================
# # STEP 3: FALLBACK → HEADERS
# # =========================================================

# def compute_from_headers(df):

#     global_min = None
#     global_max = None

#     for col in df.columns:

#         yr = extract_years(col)

#         if yr:
#             s, e = yr

#             global_min = s if global_min is None else min(global_min, s)
#             global_max = e if global_max is None else max(global_max, e)

#     return global_min, global_max

# # =========================================================
# # MAIN ANALYSIS
# # =========================================================

# def analyze_dataset(df):

#     df = remove_garbage_rows(df)

#     # STEP 1 → find real date column
#     date_col = find_date_column(df)

#     if date_col:
#         return compute_from_column(df, date_col)

#     # STEP 2 → fallback to headers
#     return compute_from_headers(df)

# # =========================================================
# # FILE READERS
# # =========================================================

# def read_csv_safe(file_path):
#     for enc in ["utf-8", "latin1", "cp1252"]:
#         try:
#             return pd.read_csv(file_path, encoding=enc, dtype=str, low_memory=False)
#         except:
#             continue
#     raise Exception("Encoding failed")


# def read_excel_safe(file_path):
#     try:
#         return pd.read_excel(file_path, engine="openpyxl")
#     except:
#         try:
#             return pd.read_excel(file_path, engine="xlrd")
#         except:
#             return pd.read_excel(file_path)


# def read_file_smart(file_path):
#     if file_path.endswith((".xlsx", ".xls")):
#         try:
#             df = pd.read_excel(file_path, header=[0,1], engine="openpyxl")
#             df.columns = [
#                 "_".join([str(i) for i in col if str(i) != "nan"]).strip()
#                 for col in df.columns
#             ]
#             return df
#         except:
#             return read_excel_safe(file_path)
#     else:
#         return read_csv_safe(file_path)

# # =========================================================
# # MAIN EXECUTION
# # =========================================================

# if __name__ == "__main__":

#     folder_path = r"C:\Users\HP\scrape\nic-metadata-cleaning\data\sample_downloaded_files\sample test"
#     output_file = os.path.join(folder_path, "dataset_temporal_coverage.xlsx")

#     results = []

#     for file in os.listdir(folder_path):

#         if not file.endswith((".csv", ".xlsx", ".xls")):
#             continue

#         try:
#             print(f"\nProcessing: {file}")

#             file_path = os.path.join(folder_path, file)
#             df = read_file_smart(file_path)

#             min_year, max_year = analyze_dataset(df)

#             print(f"Done: {file} → {min_year} to {max_year}")

#             results.append({
#                 "dataset": file,
#                 "min_year": min_year,
#                 "max_year": max_year
#             })

#         except Exception as e:
#             print(f"Error: {file} → {e}")

#             results.append({
#                 "dataset": file,
#                 "min_year": None,
#                 "max_year": None,
#                 "error": str(e)
#             })

#     pd.DataFrame(results).to_excel(output_file, index=False)

#     print("\nFINAL OUTPUT GENERATED ")

# import pandas as pd
# import re
# import os
# import warnings
# from io import BytesIO

# warnings.filterwarnings("ignore")

# # =========================================================
# # LOCAL CONFIG
# # =========================================================

# folder_path = r"C:\Users\HP\scrape\nic-metadata-cleaning\data\sample_downloaded_files"
# output_file = os.path.join(folder_path, "dataset_temporal_coverage.xlsx")

# # =========================================================
# # REGEX
# # =========================================================

# YEAR_RANGE_REGEX = re.compile(r"(18\d{2}|19\d{2}|20\d{2})\s*[-–]\s*(\d{2,4})")

# # =========================================================
# # CLEANING
# # =========================================================

# def remove_garbage_rows(df):
#     mask = df.astype(str).apply(
#         lambda row: row.str.contains(r"total|sum|average", case=False, na=False).any(),
#         axis=1
#     )
#     return df[~mask]

# # =========================================================
# # MISSING VALUE HANDLING (NEW)
# # =========================================================

# def is_valid_value(val):
#     val = str(val).strip().lower()
#     if val in ["", "nan", "null", "none", "na"]:
#         return False
#     return True

# # =========================================================
# # PARSER
# # =========================================================

# def extract_years(val):
#     try:
#         val = str(val)
#         val = re.sub(r"\(.*?\)", "", val)

#         match = YEAR_RANGE_REGEX.search(val)
#         if match:
#             start = int(match.group(1))
#             end_raw = match.group(2)

#             if len(end_raw) == 2:
#                 end = int(str(start)[:2] + end_raw)
#             else:
#                 end = int(end_raw)

#             return start, end

#         years = re.findall(r"(18\d{2}|19\d{2}|20\d{2})", val)
#         if years:
#             years = [int(y) for y in years]
#             return min(years), max(years)

#     except:
#         return None

#     return None

# # =========================================================
# # STEP 1: FIND DATE COLUMN
# # =========================================================

# def find_date_column(df):

#     best_col = None
#     best_score = 0

#     for col in df.columns:

#         values = df[col].dropna().astype(str)
#         values = values[values.apply(is_valid_value)].head(2000)

#         if len(values) == 0:
#             continue

#         hits = sum(1 for v in values if extract_years(v))
#         ratio = hits / len(values)

#         if ratio > best_score:
#             best_score = ratio
#             best_col = col

#     if best_score > 0.5:
#         return best_col

#     return None

# # =========================================================
# # COVERAGE CALCULATION (NEW)
# # =========================================================

# def calculate_coverage(values):

#     years_list = []

#     for v in values:
#         yr = extract_years(v)
#         if yr:
#             years_list.extend([yr[0], yr[1]])

#     years_list = sorted(set(years_list))

#     if len(years_list) < 2:
#         return None

#     diffs = [
#         years_list[i+1] - years_list[i]
#         for i in range(len(years_list)-1)
#     ]

#     return min(diffs) if diffs else None

# # =========================================================
# # STEP 2: COMPUTE FROM COLUMN
# # =========================================================

# def compute_from_column(df, col):

#     global_min = None
#     global_max = None

#     values = df[col].dropna().astype(str)
#     values = values[values.apply(is_valid_value)]

#     for v in values:
#         yr = extract_years(v)
#         if yr:
#             s, e = yr
#             global_min = s if global_min is None else min(global_min, s)
#             global_max = e if global_max is None else max(global_max, e)

#     coverage = calculate_coverage(values)

#     return global_min, global_max, coverage

# # =========================================================
# # STEP 3: FALLBACK → HEADERS
# # =========================================================

# def compute_from_headers(df):

#     global_min = None
#     global_max = None

#     for col in df.columns:
#         yr = extract_years(col)
#         if yr:
#             s, e = yr
#             global_min = s if global_min is None else min(global_min, s)
#             global_max = e if global_max is None else max(global_max, e)

#     return global_min, global_max, None  # coverage not applicable

# # =========================================================
# # MAIN ANALYSIS
# # =========================================================

# def analyze_dataset(df):

#     df = remove_garbage_rows(df)

#     date_col = find_date_column(df)

#     if date_col:
#         return compute_from_column(df, date_col)

#     return compute_from_headers(df)

# # =========================================================
# # FILE READERS
# # =========================================================

# def read_csv_safe(file_path):
#     for enc in ["utf-8", "latin1", "cp1252"]:
#         try:
#             return pd.read_csv(file_path, encoding=enc, dtype=str, low_memory=False)
#         except:
#             continue
#     raise Exception("Encoding failed")


# def read_excel_safe(file_path):
#     try:
#         return pd.read_excel(file_path, engine="openpyxl")
#     except:
#         try:
#             return pd.read_excel(file_path, engine="xlrd")
#         except:
#             return pd.read_excel(file_path)


# def read_file_smart(file_path):
#     if file_path.endswith((".xlsx", ".xls")):
#         try:
#             df = pd.read_excel(file_path, header=[0,1], engine="openpyxl")
#             df.columns = [
#                 "_".join([str(i) for i in col if str(i) != "nan"]).strip()
#                 for col in df.columns
#             ]
#             return df
#         except:
#             return read_excel_safe(file_path)
#     else:
#         return read_csv_safe(file_path)

# # =========================================================
# # MAIN EXECUTION (LOCAL)
# # =========================================================

# if __name__ == "__main__":

#     results = []

#     for i, file in enumerate(os.listdir(folder_path), start=1):

#         if not file.endswith((".csv", ".xlsx", ".xls")):
#             continue

#         try:
#             print(f"\nProcessing {i}: {file}")

#             file_path = os.path.join(folder_path, file)
#             df = read_file_smart(file_path)

#             min_year, max_year, coverage = analyze_dataset(df)

#             print(f"Done: {file} → {min_year} to {max_year} | coverage: {coverage}")

#             results.append({
#                 "dataset": file,
#                 "min_year": min_year,
#                 "max_year": max_year,
#                 "coverage": coverage
#             })

#         except Exception as e:
#             print(f"Error: {file} → {e}")

#             results.append({
#                 "dataset": file,
#                 "min_year": None,
#                 "max_year": None,
#                 "coverage": None,
#                 "error": str(e)
#             })

#     pd.DataFrame(results).to_excel(output_file, index=False)

#     print("\nFINAL OUTPUT GENERATED 🚀")
import pandas as pd
import re
import os
import warnings

warnings.filterwarnings("ignore")

# =========================================================
# LOCAL CONFIG
# =========================================================

folder_path = r"C:\Users\HP\scrape\nic-metadata-cleaning\data\sample_downloaded_files"
output_file = os.path.join(folder_path, "dataset_temporal_coverage.xlsx")

# =========================================================
# REGEX
# =========================================================

YEAR_RANGE_REGEX = re.compile(r"(18\d{2}|19\d{2}|20\d{2})\s*[-–]\s*(\d{2,4})")

# =========================================================
# CLEANING
# =========================================================

def remove_garbage_rows(df):
    mask = df.astype(str).apply(
        lambda row: row.str.contains(r"total|sum|average", case=False, na=False).any(),
        axis=1
    )
    return df[~mask]

# =========================================================
# MISSING VALUE HANDLING
# =========================================================

def is_valid_value(val):
    val = str(val).strip().lower()
    if val in ["", "nan", "null", "none", "na"]:
        return False
    return True

# =========================================================
# PARSER
# =========================================================

def extract_years(val):
    try:
        val = str(val)
        val = re.sub(r"\(.*?\)", "", val)

        match = YEAR_RANGE_REGEX.search(val)
        if match:
            start = int(match.group(1))
            end_raw = match.group(2)

            if len(end_raw) == 2:
                end = int(str(start)[:2] + end_raw)
            else:
                end = int(end_raw)

            return start, end

        years = re.findall(r"(18\d{2}|19\d{2}|20\d{2})", val)
        if years:
            years = [int(y) for y in years]
            return min(years), max(years)

    except:
        return None

    return None

# =========================================================
# COVERAGE FORMAT (NEW)
# =========================================================

def format_coverage(value):
    if value is None:
        return None
    return f"P{value}Y^^xsd:duration"

# =========================================================
# COVERAGE CALCULATION
# =========================================================

def calculate_coverage_from_years(years_list):

    years_list = sorted(set(years_list))

    if len(years_list) < 2:
        return None

    diffs = [
        years_list[i+1] - years_list[i]
        for i in range(len(years_list)-1)
    ]

    return min(diffs) if diffs else None


def calculate_coverage(values):

    years_list = []

    for v in values:
        yr = extract_years(v)
        if yr:
            years_list.extend([yr[0], yr[1]])

    return calculate_coverage_from_years(years_list)

# =========================================================
# STEP 1: FIND DATE COLUMN
# =========================================================

def find_date_column(df):

    best_col = None
    best_score = 0

    for col in df.columns:

        values = df[col].dropna().astype(str)
        values = values[values.apply(is_valid_value)].head(2000)

        if len(values) == 0:
            continue

        hits = sum(1 for v in values if extract_years(v))
        ratio = hits / len(values)

        if ratio > best_score:
            best_score = ratio
            best_col = col

    if best_score > 0.5:
        return best_col

    return None

# =========================================================
# STEP 2: COMPUTE FROM COLUMN
# =========================================================

def compute_from_column(df, col):

    global_min = None
    global_max = None

    values = df[col].dropna().astype(str)
    values = values[values.apply(is_valid_value)]

    for v in values:
        yr = extract_years(v)
        if yr:
            s, e = yr
            global_min = s if global_min is None else min(global_min, s)
            global_max = e if global_max is None else max(global_max, e)

    coverage_raw = calculate_coverage(values)
    coverage = format_coverage(coverage_raw)

    return global_min, global_max, coverage

# =========================================================
# STEP 3: FALLBACK → HEADERS
# =========================================================

def compute_from_headers(df):

    global_min = None
    global_max = None
    years_list = []

    for col in df.columns:

        yr = extract_years(col)

        if yr:
            s, e = yr

            global_min = s if global_min is None else min(global_min, s)
            global_max = e if global_max is None else max(global_max, e)

            years_list.extend([s, e])

    coverage_raw = calculate_coverage_from_years(years_list)
    coverage = format_coverage(coverage_raw)

    return global_min, global_max, coverage

# =========================================================
# MAIN ANALYSIS
# =========================================================

def analyze_dataset(df):

    df = remove_garbage_rows(df)

    date_col = find_date_column(df)

    if date_col:
        return compute_from_column(df, date_col)

    return compute_from_headers(df)

# =========================================================
# FILE READERS
# =========================================================

def read_csv_safe(file_path):
    for enc in ["utf-8", "latin1", "cp1252"]:
        try:
            return pd.read_csv(file_path, encoding=enc, dtype=str, low_memory=False)
        except:
            continue
    raise Exception("Encoding failed")


def read_excel_safe(file_path):
    try:
        return pd.read_excel(file_path, engine="openpyxl")
    except:
        try:
            return pd.read_excel(file_path, engine="xlrd")
        except:
            return pd.read_excel(file_path)


def read_file_smart(file_path):
    if file_path.endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(file_path, header=[0,1], engine="openpyxl")
            df.columns = [
                "_".join([str(i) for i in col if str(i) != "nan"]).strip()
                for col in df.columns
            ]
            return df
        except:
            return read_excel_safe(file_path)
    else:
        return read_csv_safe(file_path)

# =========================================================
# MAIN EXECUTION
# =========================================================

if __name__ == "__main__":

    results = []

    for i, file in enumerate(os.listdir(folder_path), start=1):

        if not file.endswith((".csv", ".xlsx", ".xls")):
            continue

        try:
            print(f"\nProcessing {i}: {file}")

            file_path = os.path.join(folder_path, file)
            df = read_file_smart(file_path)

            min_year, max_year, coverage = analyze_dataset(df)

            print(f"Done: {file} → {min_year} to {max_year} | coverage: {coverage}")

            results.append({
                "dataset": file,
                "min_year": min_year,
                "max_year": max_year,
                "coverage": coverage
            })

        except Exception as e:
            print(f"Error: {file} → {e}")

            results.append({
                "dataset": file,
                "min_year": None,
                "max_year": None,
                "coverage": None,
                "error": str(e)
            })

    pd.DataFrame(results).to_excel(output_file, index=False)

    print("\nFINAL OUTPUT GENERATED 🚀")