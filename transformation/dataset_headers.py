import duckdb
from duckdb.sqltypes import UUID
import pandas as pd
import re
import os


db_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

con = duckdb.connect(db_path)

def get_headers(path):
    try:
        if path.endswith('.xls') or path.endswith('.xlsx'):
            header = pd.read_excel(path, nrows=0)
        else:
            encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
            header = None
            for encoding in encodings:
                try:
                    header = pd.read_csv(path, nrows=0, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if header is None:
                raise ValueError("Could not decode file with any encoding")
        return header.columns.tolist()
    except Exception as e:
        print(f"Invalid path given: {path} - {str(e)}")
        return []


def create_path(batch):
    query = f'SELECT "Identifier[UUID]", Format FROM dublin_core_metadata WHERE batch = {batch} AND dataset_merge IS FALSE'
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
            cleaned_header = re.sub(r'[^a-zA-Z0-9_%.\s/]', '', header)
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
        con.execute(f'UPDATE dublin_core_metadata SET headers_cleaned = {headers_cleaned}, "Conforms To" = \'{headers}\' WHERE "Identifier[UUID]" = \'{uuid}\'')


if __name__ == "__main__":
    total_batches = int(input("Enter number of batches to process: "))

    for batch in range(1, total_batches+1):
        print(f"Processing batch {batch}...")
        paths_dict = create_path(batch)
        result = process_headers(paths_dict)
        update_db(result)
        print(f"Batch {batch} processed.\n")