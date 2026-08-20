import argparse
import csv
import duckdb
from duckdb.sqltypes import UUID
import pandas as pd
import re
import os


db_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

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


def get_headers(path):
    try:
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


def create_path(batch=None, xls_only=False):
    if xls_only:
        # Reprocess every Excel dataset regardless of existing headers
        query = (
            'SELECT "Identifier[UUID]", Format FROM dublin_core_remaining '
            "WHERE Format LIKE 'application/vnd%'"
        )
    else:
        # Only (re)process datasets whose header column ("Conforms To") is still NULL/blank
        query = (
            f'SELECT "Identifier[UUID]", Format FROM dublin_core_remaining '
            f'WHERE batch = {batch} '
            f'AND ("Conforms To" IS NULL OR TRIM("Conforms To") = \'\')'
        )
    result = con.execute(query).fetchall()
    download_folder = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads/"
    paths_dict = {}
    for uuid, file_format in result:
        fmt = file_format.split('/')[-1] if file_format else 'csv'
        fmt = fmt.replace('geo+json', 'geojson')
        fmt = fmt.replace('vnd.ms-excel', 'xls')
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
    for uuid, info in result.items():
        headers_cleaned = info["headers_cleaned"]
        headers = ','.join(info["headers"])
        con.execute(f'UPDATE dublin_core_remaining SET headers_cleaned = {headers_cleaned}, "Conforms To" = \'{headers}\' WHERE "Identifier[UUID]" = \'{uuid}\'')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process dataset headers for NIC metadata")
    parser.add_argument("--batch", type=int, help="Specific batch number to process")
    parser.add_argument("--xls", action="store_true", help="Reprocess only Excel (application/vnd*) datasets across all batches")
    args = parser.parse_args()

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