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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

resource_info_metadata = 'https://www.data.gov.in/backend/dms/v1/resource/{}?_format=json'
captcha_token_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
captcha_image_gen = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
download_link_generator = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
dataset_downloader_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default source is the DB table itself (see load_metadata_from_db): lot3 was
# never delivered as a spreadsheet the way the earlier lots were, so there is no
# equivalent of remaining_raw_datasets.xlsx to drive it. --metadata-path still
# accepts a .csv/.xlsx for one-off runs.
metadata_csv_path = None
downloads_folder = os.path.join(REPO_ROOT, 'data', 'lot3_downloads')
captcha_image_path = os.path.join(REPO_ROOT, 'scripts', 'captcha.jpeg')

DB_PATH = os.path.join(REPO_ROOT, 'transformation', 'metadata.db')
DB_TABLE = "dublin_core_lot3"
DB_UUID_COL = "Identifier[UUID]"
DB_NID_COL = "nid"
DB_FORMAT_COL = "Format"
# Dublin Core name for what the raw tables call field_resource_type. Same codes:
# it matches field_resource_type on all 116,111 rows that join between
# dublin_core_remaining and remain_raw_metadata.
DB_RESOURCE_TYPE_COL = "Accrual Method"
DB_FLAG_COL = "file_present"


# Canonical MIME -> file extension mapping (dublin_core_metadata.Format values
# plus common variants). Also the value the DMS download API expects in its
# file_type payload field.
MIME_TO_EXT = {
    'text/csv': 'csv',
    'application/csv': 'csv',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.oasis.opendocument.spreadsheet': 'ods',
    'text/xml': 'xml',
    'application/xml': 'xml',
    'application/json': 'json',
    'application/geo+json': 'geojson',
    'application/zip': 'zip',
    'application/x-zip-compressed': 'zip',
    'text/plain': 'txt',
}


def mime_to_ext(file_format):
    """Map a MIME type to a short file extension ('unknown' if unmappable)."""
    if file_format is None or (isinstance(file_format, float) and pd.isna(file_format)):
        return 'unknown'
    fmt = str(file_format).strip().lower()
    if not fmt:
        return 'unknown'
    if fmt in MIME_TO_EXT:
        return MIME_TO_EXT[fmt]
    ext = fmt.split('/')[-1]
    ext = ext.replace('geo+json', 'geojson')
    ext = ext.replace('vnd.ms-excel', 'xls')
    return ext


def detect_error_body(filepath):
    """Return an error description if the saved file is a server error body
    (JSON error message, HTML error page, or empty), else None."""
    try:
        if os.path.getsize(filepath) == 0:
            return "empty file (0 bytes)"
        with open(filepath, 'rb') as f:
            head = f.read(512).lstrip()
        if head.startswith(b'{"message"') or head.startswith(b'{"error"'):
            return f"server returned error body: {head[:120].decode(errors='replace')}"
        low = head[:64].lower()
        if low.startswith(b'<!doctype html') or low.startswith(b'<html'):
            return "server returned an HTML page instead of data"
    except Exception as e:
        return f"could not inspect downloaded file: {e}"
    return None


def csv_has_more_rows_than(path, min_rows, chunk_size=64 * 1024):
    """True if the file has more than min_rows data rows (lines after the header).

    Reads only until min_rows + 2 lines are seen: the verify gate needs a yes/no,
    and counting every line of the 1 GB CSVs in the downloads folder is what
    made --verify run for hours. False on read errors.
    """
    need = min_rows + 2  # header + (min_rows + 1) data rows
    lines = 0
    last = b''
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                lines += chunk.count(b'\n')
                if lines >= need:
                    return True
                last = chunk
    except Exception:
        return False
    if last and not last.endswith(b'\n'):
        lines += 1  # final line without a trailing newline
    return lines >= need


VERIFY_CACHE_FIELDS = ['name', 'size', 'mtime_ns', 'min_rows', 'verdict']


def _load_verify_cache(cache_path):
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, newline='') as fh:
            for r in csv.DictReader(fh):
                cache[r['name']] = r
    return cache


def _save_verify_cache(cache_path, results):
    """results: name -> (size, mtime_ns, min_rows, verdict). Atomic replace."""
    tmp = cache_path + '.tmp'
    with open(tmp, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(VERIFY_CACHE_FIELDS)
        for name, (size, mtime_ns, min_rows, verdict) in results.items():
            w.writerow([name, size, mtime_ns, min_rows, verdict])
    os.replace(tmp, cache_path)


def scan_downloads(folder, min_rows, workers=8, progress_every=5000, cache_path=None):
    """Check every file in folder for the --verify gates.

    Returns (existing_uuids, valid_uuids, too_few_rows, error_bodies).

    Opening a file costs ~30 ms on this drive (NTFS via ntfs-3g/FUSE on a 5400 rpm
    HDD), so a full pass over the
    110k downloads takes ~55 min even reading only a few KB of each. Verdicts are
    cached in cache_path keyed by (size, mtime_ns, min_rows): a later --verify
    opens only new or changed files, and stat alone covers the rest.
    """
    entries = [e for e in os.scandir(folder) if e.is_file()]
    total = len(entries)
    print(f"Verify mode: {total} files in {folder}; checking against cache ...", flush=True)

    cache = _load_verify_cache(cache_path)
    results = {}  # name -> (size, mtime_ns, min_rows, verdict)
    todo = []
    for entry in entries:
        try:
            st = entry.stat()
        except OSError:
            continue
        size, mtime_ns = str(st.st_size), str(st.st_mtime_ns)
        c = cache.get(entry.name)
        if c and c['size'] == size and c['mtime_ns'] == mtime_ns and c['min_rows'] == str(min_rows):
            results[entry.name] = (size, mtime_ns, str(min_rows), c['verdict'])
        else:
            todo.append((entry, size, mtime_ns))
    print(f"Verify mode: {total - len(todo)} unchanged since the last verify, "
          f"{len(todo)} to open and check.", flush=True)

    def check(item):
        entry, size, mtime_ns = item
        name = entry.name
        if detect_error_body(entry.path):
            verdict = 'error_body'
        else:
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext == 'csv' and not csv_has_more_rows_than(entry.path, min_rows):
                verdict = 'too_few_rows'
            else:
                verdict = 'valid'
        return name, (size, mtime_ns, str(min_rows), verdict)

    started = time.time()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, (name, res) in enumerate(ex.map(check, todo), 1):
                results[name] = res
                if i % progress_every == 0:
                    print(f"  checked {i}/{len(todo)} ({time.time() - started:.0f}s)", flush=True)
    finally:
        # Save even on Ctrl-C, so an interrupted verify does not start over.
        if cache_path:
            _save_verify_cache(cache_path, results)

    existing, valid = set(), set()
    too_few_rows = error_bodies = 0
    for name, (_, _, _, verdict) in results.items():
        uuid_part = name.split('.', 1)[0]
        existing.add(uuid_part)
        if verdict == 'valid':
            valid.add(uuid_part)
        elif verdict == 'too_few_rows':
            too_few_rows += 1
        else:
            error_bodies += 1
    return existing, valid, too_few_rows, error_bodies

session = requests.Session()

session.headers.update({
    'User-Agent': 'PostmanRuntime/7.51.1',})

# Some government hosts have broken TLS chains; download_dataset falls back to
# verify=False for those, so silence the resulting insecure-request warnings.
requests.packages.urllib3.disable_warnings()

log_file_path = os.path.join(REPO_ROOT, 'data', 'lot3_dataset_download_log.csv')


def load_metadata(path):
    """Read the driving metadata table. Needs the columns the download loop
    reads: nid, uuid, file_format, field_resource_type."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, dtype={'nid': str, 'uuid': str})
    return pd.read_excel(path)


def load_metadata_from_db(db_path=None, table=None):
    """Build the driving metadata frame from the Dublin Core table in metadata.db.

    The table stores the same facts under Dublin Core names, so map them onto the
    column names the download loop expects:
        nid -> nid, Identifier[UUID] -> uuid, Format -> file_format,
        Accrual Method -> field_resource_type.
    """
    db_path = db_path or DB_PATH
    table = table or DB_TABLE
    con = duckdb.connect(db_path, read_only=True)
    try:
        df = con.execute(
            f'SELECT CAST("{DB_NID_COL}" AS VARCHAR) AS nid, '
            f'       CAST("{DB_UUID_COL}" AS VARCHAR) AS uuid, '
            f'       "{DB_FORMAT_COL}" AS file_format, '
            f'       CAST("{DB_RESOURCE_TYPE_COL}" AS VARCHAR) AS field_resource_type '
            f'FROM "{table}"'
        ).fetch_df()
    finally:
        con.close()
    return df




def fetch_captcha_token():
    """Return (token, sid), or (None, None) if the captcha endpoint returns a
    bad/non-JSON body (so callers can retry rather than crash)."""
    try:
        response = session.get(captcha_token_url, timeout=(15, 60))
    except requests.exceptions.RequestException as e:
        print(f"Captcha token request failed (network): {e}")
        return None, None
    print(f"Captcha API response: {response.status_code} {response.text[:500]}")
    try:
        data = json.loads(response.text)
        return data['token'], data['sid']
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Captcha token response was not usable JSON: {e}")
        return None, None

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
        "file_type":[{"value":mime_to_ext(file_format)}],
        "export_status":[{"value":"download"}],
        "ogdp_captcha_sid":[{"value":str(sid)}],
        "ogdp_captcha_token":[{"value":str(token)}],
        "ogdp_captcha_response":[{"value":str(captcha_response)}],
        "catalog_id":[{"target_id":""}],
        "resource_id":[{"target_id":str(resource_id)}],
        "parameters":{}
    }
    try:
        resp = session.post(download_link_generator, json=payload, timeout=(15, 60))
    except requests.exceptions.RequestException as e:
        print(f"JWT request failed (network): {e}")
        return None
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError:
        print(f"JWT response was not JSON (status {resp.status_code}): {resp.text[:200]!r}")
        return None
    return data.get('jwt_access_token')


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


def download_dataset(resource_id, jwt_token, uuid, file_format, timeout=(15, 120), sess=None):
    # In parallel mode each worker passes its own thread-local Session; sequential
    # callers fall back to the shared module-level session.
    s = sess if sess is not None else session
    download_url = dataset_downloader_url.format(resource_id, jwt_token)
    file_extension = mime_to_ext(file_format)
    if file_extension == 'unknown':
        file_extension = 'csv'

    filename = f"{uuid}.{file_extension}"
    filepath = os.path.join(downloads_folder, filename)

    try:
        try:
            response = s.get(download_url, stream=True, timeout=timeout, verify=True)
        except requests.exceptions.SSLError:
            # field_resource_type 2 redirects to external gov hosts (e.g. censusindia.gov.in,
            # mowr.nic.in) that serve valid data over a broken TLS chain. Retry once with
            # certificate verification disabled so those datasets are still retrievable.
            print(f"SSL verify failed for {uuid}; retrying with verification disabled")
            response = s.get(download_url, stream=True, timeout=timeout, verify=False)

        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            error_body = detect_error_body(filepath)
            if error_body:
                os.remove(filepath)
                # JWT/download-token expiry is signalled as HTTP 200 with a
                # {"message":"...Download Token Expired."} body — NOT a 401 — so the
                # status-code check below never catches it. Flag it as retryable so
                # the caller refreshes the JWT and retries instead of permanently
                # failing a perfectly downloadable dataset.
                low = error_body.lower()
                if 'token expired' in low or 'not authorised' in low or 'not authorized' in low:
                    print(f"Download token expired for {uuid}; refresh JWT and retry")
                    return (False, True, error_body)
                print(f"Bad download for {uuid}: {error_body}")
                return (False, False, error_body)
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
        error_msg = f"SSL Certificate Error (verify-off also failed): {str(e)}"
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
    parser.add_argument('--skip-resource-types', type=str, default=None,
                        help="Comma-separated field_resource_type values to skip (e.g. '2' to skip "
                             "external-link datasets, which are slow and mostly dead). "
                             "field_resource_type 5 is always skipped. When driving off the DB "
                             f"table these are read from \"{DB_RESOURCE_TYPE_COL}\".")
    parser.add_argument('--only-resource-types', type=str, default=None,
                        help="Comma-separated field_resource_type values to download exclusively "
                             "(e.g. '2' for a dedicated external-link run). Mutually exclusive with --skip-resource-types.")
    parser.add_argument('--connect-timeout', type=float, default=5.0,
                        help="Per-request connect timeout in seconds. Dead external hosts (common for "
                             "field_resource_type 2) fail this fast instead of hanging. Default: 15.")
    parser.add_argument('--read-timeout', type=float, default=120.0,
                        help="Per-request read timeout in seconds. Default: 120.")
    parser.add_argument('--workers', type=int, default=1,
                        help="Number of parallel download workers sharing one JWT. Default 1 = "
                             "original sequential path. Higher (e.g. 8) gives ~Nx throughput for "
                             "fast hosts like censusindia. Per-row DB flag writes are skipped in "
                             "parallel mode (resume uses disk+log via --path).")
    parser.add_argument('--metadata-path', type=str, default=None,
                        help="Driving metadata table (.csv or .xlsx) with nid, uuid, file_format "
                             f"and field_resource_type columns. Default: read from \"{DB_TABLE}\" "
                             "in metadata.db. Use this to download a set of datasets that is not in "
                             "that table (--path only filters the default rows, it cannot add rows).")
    parser.add_argument('--downloads-folder', type=str, default=None,
                        help="Directory to save files into. Default: data/lot3_downloads.")
    parser.add_argument('--log-path', type=str, default=None,
                        help="Download log CSV, also the resume source. Give a separate log when "
                             "using --metadata-path so the two runs do not skip each other's rows.")
    parser.add_argument('--no-db-flag', action='store_true',
                        help=f"Do not write {DB_FLAG_COL} back to \"{DB_TABLE}\" on success. Required "
                             "when downloading into a folder that table's consumers do not scan — "
                             "the flag would otherwise claim a file is present where they look.")
    parser.add_argument('--test-force-herd', action='store_true',
                        help="Debug only: mid-run, invalidate the shared JWT once to force a 401 "
                             "refresh 'herd' and validate that exactly one worker regenerates it.")
    args = parser.parse_args()

    if args.metadata_path:
        metadata_csv_path = args.metadata_path
    if args.downloads_folder:
        downloads_folder = args.downloads_folder
    if args.log_path:
        log_file_path = args.log_path
    os.makedirs(downloads_folder, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(log_file_path)), exist_ok=True)
    if metadata_csv_path:
        df = load_metadata(metadata_csv_path)
        metadata_source = metadata_csv_path
    else:
        df = load_metadata_from_db()
        metadata_source = f'{DB_PATH}::"{DB_TABLE}"'
    print(f"Metadata: {len(df)} rows from {metadata_source}")
    print(f"Downloads folder: {downloads_folder}")
    print(f"Log: {log_file_path}")

    if args.verify and args.metadata_path:
        # --verify rewrites file_present for every row of DB_TABLE from one folder's
        # contents; doing that from a partial folder would blank the flag table-wide.
        parser.error("--verify cannot be combined with --metadata-path")

    skip_resource_types = None
    if args.skip_resource_types:
        skip_resource_types = {s.strip() for s in args.skip_resource_types.split(',') if s.strip()}
    only_resource_types = None
    if args.only_resource_types:
        only_resource_types = {s.strip() for s in args.only_resource_types.split(',') if s.strip()}
    if skip_resource_types and only_resource_types:
        parser.error("--skip-resource-types and --only-resource-types are mutually exclusive.")

    # Parse format filter and resolve to the set of UUIDs allowed for download
    format_filter = None
    allowed_uuids_by_format = None
    if args.formats:
        format_filter = {f.strip().lower() for f in args.formats.split(',') if f.strip()}
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

    # In verify mode, build a set of UUIDs whose file is present AND (for CSVs) has > min_rows rows
    existing_file_uuids = set()  # disk-presence only
    valid_file_uuids = set()     # passes presence + content gates
    too_few_rows = 0
    error_bodies = 0
    if args.verify:
        verify_cache_path = os.path.join(
            os.path.dirname(log_file_path),
            f"verify_cache_{os.path.basename(os.path.normpath(downloads_folder))}.csv")
        existing_file_uuids, valid_file_uuids, too_few_rows, error_bodies = \
            scan_downloads(downloads_folder, args.min_rows, cache_path=verify_cache_path)
        print(f"Verify mode: {len(existing_file_uuids)} files on disk, "
              f"{len(valid_file_uuids)} pass content gates (>{args.min_rows} rows for CSVs); "
              f"{too_few_rows} CSVs have too few rows and {error_bodies} files are "
              f"server error bodies — these will be re-downloaded.")

    LOG_FIELDS = ['uuid', 'file_type', 'status', 'detail']

    # Open the DB only when something needs it. A read-write connection held for
    # a multi-hour download run locks metadata.db for every other job; parallel
    # mode and --no-db-flag never write the per-row flag.
    needs_db = (args.verify or format_filter is not None or args.retry_low_rows
                or (not args.no_db_flag and args.workers <= 1))
    db_conn = duckdb.connect(DB_PATH) if needs_db else None
    if db_conn is None:
        print("DB: not opened (no --verify/--formats/--retry-low-rows, and no per-row flag writes).")

    # Ensure file_present column exists on the metadata table
    existing_cols = {
        r[0] for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [DB_TABLE],
        ).fetchall()
    } if db_conn is not None else {DB_FLAG_COL}
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
                    f'SELECT "{DB_UUID_COL}" FROM "{DB_TABLE}" '
                    f'WHERE "{DB_FORMAT_COL}" IN ({placeholders})',
                    wanted_mimes,
                ).fetchall()
            }
        print(f"Format filter: {len(allowed_uuids_by_format)} UUIDs in DB match.")

    # --retry-low-rows: pull UUIDs whose stored row_count is below the threshold
    allowed_uuids_by_low_rows = None
    if args.retry_low_rows:
        if 'row_count' not in existing_cols:
            parser.error(
                f'--retry-low-rows needs a row_count column on "{DB_TABLE}", which does not '
                'have one. Populate it first, or select the rows to retry with --path.')
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

    # ---------------- parallel-mode infrastructure (shared JWT) ----------------
    # One JWT is shared by all workers. Captcha solving + JWT minting run under a
    # lock (they use the global session and the fixed captcha.jpeg path, so they
    # must stay single-threaded); downloads use per-thread sessions.
    _jwt_lock = threading.Lock()
    _jwt_holder = {'jwt': None}
    _regen_count = {'n': 0}

    def _regenerate_jwt(resource_id, file_format):
        """Mint a fresh JWT via the captcha flow. Caller MUST hold _jwt_lock."""
        for _ in range(6):
            token, sid = fetch_captcha_token()
            if not token or not sid:
                time.sleep(1)
                continue
            cap = get_captcha_input(sid, token)
            if not cap:
                continue
            new = get_jwt_token(token, sid, cap, resource_id, file_format)
            if new:
                return new
        return None

    def get_valid_jwt(expected, resource_id, file_format):
        """Herd-safe refresh: only the first thread whose `expected` still matches
        the shared JWT (or None at startup) regenerates; the rest of the herd take
        the already-refreshed token instead of each minting their own."""
        with _jwt_lock:
            if _jwt_holder['jwt'] == expected or _jwt_holder['jwt'] is None:
                _regen_count['n'] += 1
                print(f"[JWT] regenerating (herd leader, regen #{_regen_count['n']})")
                _jwt_holder['jwt'] = _regenerate_jwt(resource_id, file_format)
            else:
                print("[JWT] took already-refreshed token")
            return _jwt_holder['jwt']

    def process_row_parallel(item):
        resource_id, uuid, file_format, file_type = item
        tsess = requests.Session()
        tsess.headers.update({'User-Agent': 'PostmanRuntime/7.51.1'})
        # 1 initial attempt + up to 2 refresh-retries on 401; never drop the row.
        for _attempt in range(3):
            jwt = _jwt_holder['jwt']
            if jwt is None:
                jwt = get_valid_jwt(None, resource_id, file_format)
                if jwt is None:
                    return (uuid, file_type, 'failed', 'JWT acquisition failed')
            success, should_retry, error_msg = download_dataset(
                resource_id, jwt, uuid, file_format,
                timeout=(args.connect_timeout, args.read_timeout), sess=tsess,
            )
            if success:
                return (uuid, file_type, 'success', '')
            if should_retry:  # 401/expired -> herd-safe refresh, retry same row
                get_valid_jwt(jwt, resource_id, file_format)
                continue
            return (uuid, file_type, 'failed', error_msg)
        return (uuid, file_type, 'failed', 'JWT retry exhausted (repeated 401)')

    work_rows = []  # populated in parallel mode; drained by the pool after the loop
    # ---------------------------------------------------------------------------

    for index, row in df.iterrows():
        resource_id = row.get('nid')
        uuid = row.get('uuid')
        file_format = row.get('file_format')
        file_type = mime_to_ext(file_format)
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

        frt = str(field_resource_type).strip()
        # int-like values (e.g. 2.0) come out of pandas as floats; normalise
        if frt.endswith('.0'):
            frt = frt[:-2]

        if frt == '5':
            print(f"Skipping row {index}: field_resource_type is 5")
            log_writer.writerow([uuid, file_type, 'skipped', 'field_resource_type is 5'])
            log_file.flush()
            continue

        # Not logged: keeps these UUIDs unprocessed so a later dedicated run
        # (e.g. --only-resource-types 2) can still pick them up.
        if skip_resource_types is not None and frt in skip_resource_types:
            print(f"Skipping row {index}: field_resource_type {frt} in --skip-resource-types")
            continue

        if only_resource_types is not None and frt not in only_resource_types:
            print(f"Skipping row {index}: field_resource_type {frt} not in --only-resource-types")
            continue

        file_extension = mime_to_ext(file_format)

        SKIP_FORMATS = {'zip', 'geojson', 'wms'}
        if file_extension.lower() in SKIP_FORMATS:
            print(f"Skipping row {index}: Unsupported format {file_extension}")
            log_writer.writerow([uuid, file_type, 'skipped', f'Unsupported format: {file_extension}'])
            log_file.flush()
            continue

        resource_id = str(int(resource_id))

        # Parallel mode: collect the eligible row and defer the actual download to
        # the worker pool after this filtering loop. All skip/log logic above is
        # identical to the sequential path.
        if args.workers > 1:
            work_rows.append((resource_id, uuid, file_format, file_type))
            continue

        while True:
            if jwt_token is None:
                token, sid = fetch_captcha_token()
                if not token or not sid:
                    print("Failed to fetch captcha token. Retrying...")
                    time.sleep(1)
                    continue

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
            success, should_retry, error_msg = download_dataset(
                resource_id, jwt_token, uuid, file_format,
                timeout=(args.connect_timeout, args.read_timeout),
            )
            time.sleep(0.5)
            if success:
                log_writer.writerow([uuid, file_type, 'success', ''])
                log_file.flush()
                if not args.no_db_flag:
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

    # ---------------- parallel execution ----------------
    # Only the main thread writes the log (serialized here), so no log lock is
    # needed. Workers only download + refresh the shared JWT. Per-row DB flag
    # writes are intentionally skipped (duckdb isn't concurrent-write-safe and
    # --path resume relies on disk+log, not the flag).
    if args.workers > 1:
        print(f"Parallel mode: {len(work_rows)} datasets across {args.workers} workers.")
        done = 0
        herd_injected = False
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(process_row_parallel, it) for it in work_rows]
            for fut in as_completed(futures):
                uuid_r, ft_r, status_r, detail_r = fut.result()
                log_writer.writerow([uuid_r, ft_r, status_r, detail_r])
                log_file.flush()
                done += 1
                if done % 200 == 0:
                    print(f"  ... {done}/{len(work_rows)} done")
                if args.test_force_herd and not herd_injected and done >= 2:
                    print("[TEST] injecting bogus JWT to force a mid-run 401 refresh herd")
                    _jwt_holder['jwt'] = 'eyBOGUS.eyBOGUS.sig'
                    herd_injected = True
        print(f"Parallel mode complete: {done} datasets processed, "
              f"{_regen_count['n']} JWT (re)generations.")

    log_file.close()
    if db_conn is not None:
        db_conn.close()




