import argparse
import csv
import json
import duckdb
import pandas as pd
import re
import os


base_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(base_dir, "metadata.db")
download_folder = os.path.join(base_dir, "..", "data", "lot3_downloads") + "/"

con = duckdb.connect(db_path)

def get_headers_csv(path):
    """Read the first CSV record (handles quoted headers spanning multiple lines,
    UTF-16 files and tab-delimited files masquerading as .csv)."""
    with open(path, 'rb') as f:
        head = f.read(4)
    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        encodings = ['utf-16'] + encodings
    for encoding in encodings:
        try:
            with open(path, newline='', encoding=encoding) as f:
                sample = f.readline()
                delimiter = '\t' if sample.count('\t') > sample.count(',') else ','
                f.seek(0)
                return next(csv.reader(f, delimiter=delimiter))
        except (UnicodeDecodeError, StopIteration, UnicodeError):
            continue
    raise ValueError(f"Could not decode CSV headers with any encoding: {path}")


def _record_keys(obj):
    """Keys of the first record: obj itself if a dict, else the first item of a list of objects.
    A dict wrapping a list of records (e.g. {"status": "success", "data": [...]}) yields the records' keys."""
    if isinstance(obj, dict):
        if obj == {"status": "FAIL"}:
            return []  # not a dataset (a failed download saved as {"status":"FAIL"})
        for value in obj.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return list(value[0].keys())
        return list(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return list(obj[0].keys())
    return []


def get_headers_json(path, max_bytes=200 * 1024 * 1024):
    """Keys of the first record of a JSON file (list of objects, or an object wrapping one).
    Only reads as much of a top-level array as needed so multi-GB files stay cheap."""
    decoder = json.JSONDecoder()
    size = 1024 * 1024
    with open(path, encoding='utf-8-sig') as f:
        while True:
            f.seek(0)
            raw = f.read(size)
            complete = len(raw) < size  # whole file fits in the buffer
            text = raw.lstrip()
            if text and text[0] not in '[{':
                # Not JSON at all: some ".json" downloads are really plain CSV text
                return get_headers_csv(path)
            if text.startswith('['):
                text = text[1:].lstrip()
            try:
                first, _ = decoder.raw_decode(text)
                return _record_keys(first)
            except json.JSONDecodeError:
                if complete:
                    raise
                if size >= max_bytes:
                    # e.g. a wrapper object whose record list closes late: fall back to a full parse if affordable
                    raise
                size *= 4


def get_headers(path):
    try:
        if path.endswith('.json'):
            return get_headers_json(path)
        if path.endswith('.xls') or path.endswith('.xlsx'):
            try:
                return pd.read_excel(path, nrows=0).columns.tolist()
            except ValueError:
                # Some "xls" downloads are really plain CSV text
                return get_headers_csv(path)
        return get_headers_csv(path)
    except Exception as e:
        print(f"Invalid path given: {path} - {str(e)}")
        return []


def create_path(batch=None, xls_only=False, csv_only=False, json_only=False):
    if json_only:
        query = (
            'SELECT "Identifier[UUID]", Format FROM dublin_core_lot3 '
            "WHERE Format IN ('text/json', 'application/json') "
            "AND (\"Conforms To\" IS NULL OR TRIM(\"Conforms To\") = '')"
        )
    elif csv_only:
        # batch is NULL for lot3 rows, so select by format; only rows whose header column is still blank
        query = (
            'SELECT "Identifier[UUID]", Format FROM dublin_core_lot3 '
            "WHERE (Format = 'text/csv' OR Format IS NULL) "
            "AND (\"Conforms To\" IS NULL OR TRIM(\"Conforms To\") = '')"
        )
    elif xls_only:
        # Reprocess every Excel dataset regardless of existing headers
        query = (
            'SELECT "Identifier[UUID]", Format FROM dublin_core_lot3 '
            "WHERE Format IN ('application/vnd.ms-excel', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')"
        )
    else:
        # Only (re)process datasets whose header column ("Conforms To") is still NULL/blank
        query = (
            f'SELECT "Identifier[UUID]", Format FROM dublin_core_lot3 '
            f'WHERE batch = {batch} '
            f'AND ("Conforms To" IS NULL OR TRIM("Conforms To") = \'\')'
        )
    result = con.execute(query).fetchall()
    paths_dict = {}
    for uuid, file_format in result:
        fmt = file_format.split('/')[-1] if file_format else 'csv'
        fmt = fmt.replace('geo+json', 'geojson')
        fmt = fmt.replace('vnd.ms-excel', 'xls')
        fmt = fmt.replace('vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx')
        path = download_folder + uuid + "." + fmt
        if os.path.exists(path):
            paths_dict[uuid] = path
        else:
            print(f"File not found: {path}")

    return paths_dict


def process_headers(paths_dict):
    result = {}
    for uuid, path in paths_dict.items():
        headers = get_headers(path)
        cleaned_headers = []
        headers_cleaned = False

        for header in headers:
            header = str(header)  # Excel year/number headers come back as ints
            original_header = header
            cleaned_header = re.sub(r'[^a-zA-Z0-9_%. /]', '', header)
            cleaned_headers.append(cleaned_header)
            if cleaned_header != original_header:
                headers_cleaned = True

        result[uuid] = {
            "path": path,
            "headers": cleaned_headers,
            "headers_cleaned": headers_cleaned
        }

    return result

def update_db(result):
    con.execute("ALTER TABLE dublin_core_lot3 ADD COLUMN IF NOT EXISTS headers_cleaned BOOLEAN")
    con.execute("BEGIN")
    for uuid, info in result.items():
        headers = ','.join(info["headers"])
        con.execute(
            'UPDATE dublin_core_lot3 SET headers_cleaned = ?, "Conforms To" = ? WHERE "Identifier[UUID]" = ?',
            [info["headers_cleaned"], headers, uuid],
        )
    con.execute("COMMIT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process dataset headers for NIC metadata")
    parser.add_argument("--batch", type=int, help="Specific batch number to process")
    parser.add_argument("--xls", action="store_true", help="Reprocess only Excel (application/vnd*) datasets across all batches")
    parser.add_argument("--csv", action="store_true", help="Process all text/csv datasets with blank headers (ignores batch)")
    parser.add_argument("--download-dir", help="Folder holding the downloaded files (default: data/lot3_downloads)")
    parser.add_argument("--json", action="store_true", help="Process all JSON datasets with blank headers (first-record keys; ignores batch)")
    args = parser.parse_args()

    if args.download_dir:
        download_folder = args.download_dir.rstrip("/") + "/"

    if args.json:
        print("Processing JSON datasets...")
        paths_dict = create_path(json_only=True)
        result = process_headers(paths_dict)
        update_db(result)
        print(f"Processed {len(result)} JSON datasets.")
        raise SystemExit(0)

    if args.csv:
        print("Processing CSV datasets...")
        paths_dict = create_path(csv_only=True)
        result = process_headers(paths_dict)
        update_db(result)
        print(f"Processed {len(result)} CSV datasets.")
        raise SystemExit(0)

    if args.xls:
        print("Processing Excel datasets...")
        paths_dict = create_path(xls_only=True)
        result = process_headers(paths_dict)
        update_db(result)
        print(f"Processed {len(result)} Excel datasets.")
        raise SystemExit(0)

    if args.batch is not None:
        batches = [args.batch]
    else:
        total_batches = int(input("Enter number of batches to process: "))
        batches = range(1, total_batches + 1)

    for batch in batches:
        print(f"Processing batch {batch}...")
        paths_dict = create_path(batch)
        result = process_headers(paths_dict)
        update_db(result)
        print(f"Batch {batch} processed.\n")