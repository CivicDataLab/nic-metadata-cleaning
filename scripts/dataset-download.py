import requests
import json
import os
import base64
import argparse
from datetime import datetime, timezone
import csv
import pandas as pd
import time
import re
import captcha
import openpyxl
import duckdb

resource_info_metadata = 'https://www.data.gov.in/backend/dms/v1/resource/{}?_format=json'
captcha_token_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
captcha_image_gen = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
download_link_generator = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
dataset_downloader_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'

metadata_csv_path = '/home/aakash/NIC/Newfolder/ResourceList_DoFHW/ResourceList_Department-of-Health-and-Family-Welfare.xlsx'
downloads_folder = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads'
#downloads_folder = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/sample_downloaded_files'
captcha_image_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/scripts/captcha.jpeg"

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
DB_TABLE = "dublin_core_metadata"
DB_UUID_COL = "Identifier[UUID]"
DB_FLAG_COL = "file_present"

os.makedirs(downloads_folder, exist_ok=True)

session = requests.Session()

session.headers.update({
    'User-Agent': 'PostmanRuntime/7.51.1',})

df = pd.read_excel(metadata_csv_path)

log_file_path = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/dataset_download_log.csv'




def fetch_captcha_token():
    response = session.get(captcha_token_url)
    print(f"Captcha API response: {response.status_code} {response.text[:500]}")
    data = json.loads(response.text)
    token = data['token']
    sid = data['sid']
    print(f"Captcha Token: {token}, Captcha SID: {sid}")
    return token, sid

def get_captcha_input(sid, token):
    captcha_image_url = captcha_image_gen.format(sid, token)
    print(f"Captcha Image URL: {captcha_image_url}")
    try:
        with open(captcha_image_path, "wb") as file:
            file.write(session.get(captcha_image_url).content)
        print(f"Captcha image saved to: {captcha_image_path}")
    except Exception as e:
        print(f"Error downloading captcha image: {e}")
        return None

    captcha_response = captcha.solve_captcha(captcha_image_path).strip().upper()
    return captcha_response



def get_jwt_token(token, sid, captcha_response, resource_id, file_format):
    payload = {
        "name":[{"value":"Resource Download"}],
        "field_domain":["4"],
        "field_domain_visibility":["4","4"],
        "uid":[{"value":0}],
        "ip":[{"value":""}],
        "usage":[{"value":"2"}],
        "purpose":[{"value":"7"}],
        "file_type":[{"value":str(file_format[5:])}],
        "export_status":[{"value":"download"}],
        "ogdp_captcha_sid":[{"value":str(sid)}],
        "ogdp_captcha_token":[{"value":str(token)}],
        "ogdp_captcha_response":[{"value":str(captcha_response)}],
        "catalog_id":[{"target_id":""}],
        "resource_id":[{"target_id":str(resource_id)}],
        "parameters":{}
    }
    response = session.post(download_link_generator, json=payload)
    response = json.loads(response.text)
    jwt_token = response.get('jwt_access_token')
    return jwt_token


def is_token_expiring_soon(jwt_token, buffer_seconds=30):
    """Check if JWT token will expire within buffer_seconds."""
    try:
        payload = jwt_token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp_time = datetime.fromtimestamp(decoded['exp'], tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        remaining = (exp_time - now).total_seconds()
        print(f"JWT token expires in {remaining:.0f}s")
        return remaining < buffer_seconds
    except Exception as e:
        print(f"Could not decode JWT expiry: {e}")
        return True


def download_dataset(resource_id, jwt_token, uuid, file_format):
    download_url = dataset_downloader_url.format(resource_id, jwt_token)
    file_extension = file_format.split('/')[-1] if file_format else 'csv'
    file_extension = file_extension.replace('geo+json', 'geojson')
    file_extension = file_extension.replace('vnd.ms-excel', 'xls')

    filename = f"{uuid}.{file_extension}"
    filepath = os.path.join(downloads_folder, filename)

    try:
        response = session.get(download_url, stream=True, timeout=300)

        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded: {filename}")
            return (True, False, "")

        elif response.status_code in [401]:
            error_msg = f"JWT token expired/unauthorized - Status: {response.status_code}"
            print(f"JWT auth error for {uuid}: {error_msg}")
            return (False, True, error_msg)

        elif response.status_code in [500, 502, 503, 504]:
            error_msg = f"Server error - Status: {response.status_code}"
            print(f"Server error for {uuid}: {error_msg}")
            return (False, False, error_msg)

        else:
            error_msg = f"HTTP error - Status: {response.status_code}"
            print(f"HTTP error for {uuid}: {error_msg}")
            return (False, False, error_msg)

    except requests.exceptions.SSLError as e:
        error_msg = f"SSL Certificate Error: {str(e)}"
        print(f"SSL error for {uuid}: {error_msg}")
        return (False, False, error_msg)

    except requests.exceptions.Timeout as e:
        error_msg = f"Timeout Error: {str(e)}"
        print(f"Timeout error for {uuid}: {error_msg}")
        return (False, False, error_msg)

    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection Error: {str(e)}"
        print(f"Connection error for {uuid}: {error_msg}")
        return (False, False, error_msg)

    except Exception as e:
        error_msg = f"Unexpected Error: {str(e)}"
        print(f"Unexpected error for {uuid}: {error_msg}")
        return (False, False, error_msg)



def extract_uuid_from_url(url):
    if pd.isna(url) or not url:
        return None
    try:
        parts = url.split('/')
        for part in parts:
            if '-' in part and len(part) == 36:
                return part
    except:
        return None
    return None

if __name__ == "__main__":
    # Use existing uuid column from CSV instead of extracting from URL
    # df['uuid'] = df['datafile_url'].apply(extract_uuid_from_url)

    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true',
                        help="Verify that UUIDs logged as 'success' exist in the downloads folder; re-download any missing files.")
    parser.add_argument('--formats', type=str, default=None,
                        help="Comma-separated file extensions to download (e.g. 'csv,xls,xml'). "
                             "Matches against dublin_core_metadata.Format. Default: all formats.")
    parser.add_argument('--min-rows', type=int, default=5,
                        help="In verify mode, CSV files with fewer than this many data rows are treated as missing and re-downloaded. Default: 5.")
    parser.add_argument('--path', type=str, default=None,
                        help="Path to a CSV with a 'uuid' column. Only those UUIDs that are missing from the downloads folder will be attempted.")
    parser.add_argument('--retry-low-rows', action='store_true',
                        help="Re-download datasets whose dublin_core_metadata.row_count is below --retry-row-threshold. "
                             "Bypasses the processed-log and disk-presence checks so existing files are overwritten.")
    parser.add_argument('--retry-row-threshold', type=int, default=5,
                        help="Row-count threshold for --retry-low-rows (strictly less-than). Default: 5.")
    args = parser.parse_args()

    # Parse format filter and resolve to the set of UUIDs allowed for download
    format_filter = None
    allowed_uuids_by_format = None
    if args.formats:
        format_filter = {f.strip().lower() for f in args.formats.split(',') if f.strip()}
        # MIME -> short extension mapping used in dublin_core_metadata.Format
        MIME_TO_EXT = {
            'text/csv': 'csv',
            'application/vnd.ms-excel': 'xls',
            'text/xml': 'xml',
            'application/json': 'json',
            'application/geo+json': 'geojson',
            'application/zip': 'zip',
        }
        wanted_mimes = [m for m, e in MIME_TO_EXT.items() if e in format_filter]
        print(f"Format filter: {sorted(format_filter)}  ->  MIME types: {wanted_mimes}")

    # Parse --path: CSV of UUIDs to consider; keep only ones not already on disk
    allowed_uuids_by_path = None
    if args.path:
        if not os.path.isfile(args.path):
            raise FileNotFoundError(f"--path CSV not found: {args.path}")
        path_df = pd.read_csv(args.path)
        if 'uuid' not in path_df.columns:
            raise ValueError(f"--path CSV {args.path} must contain a 'uuid' column. Found: {list(path_df.columns)}")
        csv_uuids = {str(u).strip() for u in path_df['uuid'].dropna() if str(u).strip()}

        present_on_disk = set()
        for fname in os.listdir(downloads_folder):
            full = os.path.join(downloads_folder, fname)
            if os.path.isfile(full):
                present_on_disk.add(fname.split('.', 1)[0])

        already = csv_uuids & present_on_disk
        allowed_uuids_by_path = csv_uuids - present_on_disk
        print(f"--path filter: {len(csv_uuids)} UUIDs in CSV, "
              f"{len(already)} already on disk (skipped), "
              f"{len(allowed_uuids_by_path)} to attempt download.")

    jwt_token = None
    token = None
    sid = None

    def count_csv_rows(path):
        """Return number of data rows (excluding header), or -1 on error."""
        try:
            with open(path, 'rb') as f:
                n = sum(1 for _ in f) - 1
            return max(n, 0)
        except Exception:
            return -1

    # In verify mode, build a set of UUIDs whose file is present AND (for CSVs) has > min_rows rows
    existing_file_uuids = set()  # disk-presence only
    valid_file_uuids = set()     # passes presence + row-count gate
    too_few_rows = 0
    if args.verify:
        for fname in os.listdir(downloads_folder):
            full = os.path.join(downloads_folder, fname)
            if not os.path.isfile(full):
                continue
            uuid_part = fname.split('.', 1)[0]
            existing_file_uuids.add(uuid_part)
            ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
            if ext == 'csv':
                rows = count_csv_rows(full)
                if rows > args.min_rows:
                    valid_file_uuids.add(uuid_part)
                else:
                    too_few_rows += 1
            else:
                # Non-CSV formats: trust presence
                valid_file_uuids.add(uuid_part)
        print(f"Verify mode: {len(existing_file_uuids)} files on disk, "
              f"{len(valid_file_uuids)} pass row-count gate (>{args.min_rows} rows for CSVs); "
              f"{too_few_rows} CSVs have too few rows and will be re-downloaded.")

    LOG_FIELDS = ['uuid', 'file_type', 'status', 'detail']

    # Open DB connection (kept open so successful downloads can update file_present)
    db_conn = duckdb.connect(DB_PATH)

    # Ensure file_present column exists on the metadata table
    existing_cols = {
        r[0] for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [DB_TABLE],
        ).fetchall()
    }
    if DB_FLAG_COL not in existing_cols:
        db_conn.execute(
            f'ALTER TABLE "{DB_TABLE}" ADD COLUMN "{DB_FLAG_COL}" BOOLEAN DEFAULT FALSE'
        )
        print(f"Added column {DB_FLAG_COL} to {DB_TABLE}")

    # Resolve --formats filter against the DB
    if format_filter is not None:
        if not wanted_mimes:
            print(f"WARNING: format filter {sorted(format_filter)} matched no known MIME types — nothing will download.")
            allowed_uuids_by_format = set()
        else:
            placeholders = ', '.join(['?'] * len(wanted_mimes))
            allowed_uuids_by_format = {
                r[0] for r in db_conn.execute(
                    f'SELECT "{DB_UUID_COL}" FROM "{DB_TABLE}" WHERE "Format" IN ({placeholders})',
                    wanted_mimes,
                ).fetchall()
            }
        print(f"Format filter: {len(allowed_uuids_by_format)} UUIDs in DB match.")

    # --retry-low-rows: pull UUIDs whose stored row_count is below the threshold
    allowed_uuids_by_low_rows = None
    if args.retry_low_rows:
        allowed_uuids_by_low_rows = {
            r[0] for r in db_conn.execute(
                f'SELECT "{DB_UUID_COL}" FROM "{DB_TABLE}" '
                f'WHERE row_count IS NOT NULL AND row_count < ?',
                [args.retry_row_threshold],
            ).fetchall()
        }
        print(f"--retry-low-rows: {len(allowed_uuids_by_low_rows)} UUIDs have "
              f"row_count < {args.retry_row_threshold} and will be re-downloaded.")

    # In verify mode, sync the DB flag from the actual contents of the downloads folder
    # (file_present = TRUE only if file exists AND, for CSVs, has > --min-rows rows)
    db_present_uuids = set()
    if args.verify:
        db_conn.register('disk_uuids_df', pd.DataFrame({'uuid': list(valid_file_uuids)}))
        db_conn.execute(
            f'UPDATE "{DB_TABLE}" '
            f'SET "{DB_FLAG_COL}" = ("{DB_UUID_COL}" IN (SELECT uuid FROM disk_uuids_df))'
        )
        db_conn.unregister('disk_uuids_df')

        present_count = db_conn.execute(
            f'SELECT COUNT(*) FROM "{DB_TABLE}" WHERE "{DB_FLAG_COL}" = TRUE'
        ).fetchone()[0]
        missing_count = db_conn.execute(
            f'SELECT COUNT(*) FROM "{DB_TABLE}" WHERE "{DB_FLAG_COL}" = FALSE OR "{DB_FLAG_COL}" IS NULL'
        ).fetchone()[0]
        print(f"Verify mode: DB flag synced — {present_count} present, {missing_count} missing on disk.")

        db_present_uuids = {
            r[0] for r in db_conn.execute(
                f'SELECT "{DB_UUID_COL}" FROM "{DB_TABLE}" WHERE "{DB_FLAG_COL}" = TRUE'
            ).fetchall()
        }

    # Load already-processed UUIDs from existing log to allow resuming
    processed_uuids = set()
    log_exists = os.path.exists(log_file_path)
    if log_exists:
        with open(log_file_path, 'r', newline='') as existing_log:
            reader = csv.DictReader(existing_log)
            for log_row in reader:
                uuid_val = log_row.get('uuid')
                if not uuid_val:
                    continue
                # In verify mode, only consider an entry processed if its file is on disk
                if args.verify and log_row.get('status') == 'success' \
                        and uuid_val not in db_present_uuids:
                    continue
                processed_uuids.add(uuid_val)
        print(f"Resuming: {len(processed_uuids)} already-processed entries found in log.")

    # Initialize CSV log file
    log_file = open(log_file_path, 'a', newline='')
    log_writer = csv.writer(log_file)
    if not log_exists:
        log_writer.writerow(LOG_FIELDS)
        log_file.flush()

    for index, row in df.iterrows():
        resource_id = row.get('nid')
        uuid = row.get('uuid')
        file_format = row.get('file_format')
        file_type = file_format.split('/')[-1] if file_format else 'unknown'
        print(file_type)
        field_resource_type = row.get('field_resource_type')

        # --retry-low-rows bypasses the processed-log check so the file is fetched again
        in_low_rows_retry = (
            allowed_uuids_by_low_rows is not None
            and str(uuid) in allowed_uuids_by_low_rows
        )

        if str(uuid) in processed_uuids and not in_low_rows_retry:
            print(f"Skipping row {index}: already processed ({uuid})")
            continue

        if allowed_uuids_by_format is not None and str(uuid) not in allowed_uuids_by_format:
            print(f"Skipping row {index}: format not in --formats filter ({uuid})")
            continue

        if allowed_uuids_by_path is not None and str(uuid) not in allowed_uuids_by_path:
            print(f"Skipping row {index}: not in --path CSV or already on disk ({uuid})")
            continue

        if allowed_uuids_by_low_rows is not None and str(uuid) not in allowed_uuids_by_low_rows:
            print(f"Skipping row {index}: row_count >= {args.retry_row_threshold} ({uuid})")
            continue

        if pd.isna(resource_id) or pd.isna(uuid):
            print(f"Skipping row {index}: Missing resource_id or uuid")
            log_writer.writerow([uuid, file_type, 'skipped', 'Missing resource_id or uuid'])
            log_file.flush()
            continue

        if not re.fullmatch(r'\d+', str(resource_id).strip()):
            print(f"Skipping row {index}: Malformed nid '{resource_id}'")
            log_writer.writerow([uuid, file_type, 'skipped', f'Malformed nid: {resource_id}'])
            log_file.flush()
            continue

        if str(field_resource_type) == '5':
            print(f"Skipping row {index}: field_resource_type is 5")
            log_writer.writerow([uuid, file_type, 'skipped', 'field_resource_type is 5'])
            log_file.flush()
            continue

        file_extension = file_format.split('/')[-1] if file_format else 'unknown'
        file_extension = file_extension.replace('geo+json', 'geojson')
        file_extension = file_extension.replace('vnd.ms-excel', 'xls')

        SKIP_FORMATS = {'zip', 'geojson', 'WMS'}
        if file_extension in SKIP_FORMATS:
            print(f"Skipping row {index}: Unsupported format {file_extension}")
            log_writer.writerow([uuid, file_type, 'skipped', f'Unsupported format: {file_extension}'])
            log_file.flush()
            continue

        resource_id = str(int(resource_id))

        while True:
            if jwt_token is None:
                token, sid = fetch_captcha_token()

                captcha_response = get_captcha_input(sid, token)
                if not captcha_response:
                    print("Failed to get captcha input. Exiting.")
                    log_writer.writerow([uuid, file_type, 'failed', 'Captcha input failed'])
                    log_file.flush()
                    break
                jwt_token = get_jwt_token(token, sid, captcha_response, resource_id, file_format)
                if not jwt_token:
                    print("Failed to get JWT token. Retrying captcha...")
                    continue
            if jwt_token and is_token_expiring_soon(jwt_token):
                print("JWT token expiring soon. Refreshing...")
                jwt_token = None
                continue
            success, should_retry, error_msg = download_dataset(resource_id, jwt_token, uuid, file_format)
            time.sleep(0.5)
            if success:
                log_writer.writerow([uuid, file_type, 'success', ''])
                log_file.flush()
                db_conn.execute(
                    f'UPDATE "{DB_TABLE}" SET "{DB_FLAG_COL}" = TRUE WHERE "{DB_UUID_COL}" = ?',
                    [str(uuid)],
                )
                break
            elif should_retry:
                print("JWT token may have expired. Getting new token...")
                jwt_token = None
            else:
                print(f"Skipping dataset due to: {error_msg}")
                log_writer.writerow([uuid, file_type, 'failed', error_msg])
                log_file.flush()
                break

    log_file.close()
    db_conn.close()




