"""Retry datasets that were never successfully downloaded, and log the ones
that still fail along with their error code.

"Not downloaded" is defined by disk, not by log status: a dataset counts as
missing if there is no ``{uuid}.{ext}`` file in the downloads folder. This
naturally covers both previously-*failed* rows and *never-attempted* rows, and
ignores stale/incorrect log entries. The retry set is therefore:

    eligible DB UUIDs  -  UUIDs already present on disk

For each missing dataset we run the same captcha -> JWT -> download flow used by
``dataset-download.py``. If the download succeeds the file is written and the
dataset drops out of the failure log on the next run. If it fails we write a row
to ``data/failed_downloads_log.csv`` with a parsed ``error_code`` column so the
failures can be grouped (e.g. SignatureDoesNotMatch, HTTP_500, SSL, Timeout).

Usage:
    python scripts/retry_failed_downloads.py                # retry all missing
    python scripts/retry_failed_downloads.py --limit 20     # retry first 20 (smoke test)
    python scripts/retry_failed_downloads.py --skip-codes SignatureDoesNotMatch
            # don't bother re-attempting known hard server-side blocks
"""

import os
import re
import csv
import json
import time
import base64
import argparse
from datetime import datetime, timezone

import requests
import duckdb

import captcha  # local easyocr-based solver (run from scripts/ dir)

# --- endpoints (same as dataset-download.py) ------------------------------
CAPTCHA_TOKEN_URL = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
CAPTCHA_IMAGE_GEN = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
DOWNLOAD_LINK_GENERATOR = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
DATASET_DOWNLOADER_URL = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'

# --- paths ----------------------------------------------------------------
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_FOLDER = os.path.join(REPO, 'data', 'first_batch_downloads')
CAPTCHA_IMAGE_PATH = os.path.join(REPO, 'scripts', 'captcha.jpeg')
FAILURE_LOG_PATH = os.path.join(REPO, 'data', 'failed_downloads_log.csv')

DB_PATH = os.path.join(REPO, 'transformation', 'metadata.db')
DB_TABLE = 'dublin_core_metadata'
DB_UUID_COL = 'Identifier[UUID]'
DB_NID_COL = 'nid'
DB_FORMAT_COL = 'Format'
DB_FLAG_COL = 'file_present'

# formats the original pipeline never downloads
SKIP_EXTENSIONS = {'zip', 'geojson', 'WMS'}

LOG_FIELDS = ['uuid', 'nid', 'file_type', 'error_code', 'error_detail', 'timestamp']

session = requests.Session()
session.headers.update({'User-Agent': 'PostmanRuntime/7.51.1'})


def ext_from_format(file_format):
    if not file_format:
        return 'unknown'
    e = str(file_format).split('/')[-1]
    return e.replace('geo+json', 'geojson').replace('vnd.ms-excel', 'xls')


def fetch_captcha_token():
    data = session.get(CAPTCHA_TOKEN_URL, timeout=30).json()
    return data['token'], data['sid']


def solve_captcha_for(sid, token):
    img = session.get(CAPTCHA_IMAGE_GEN.format(sid, token), timeout=30).content
    with open(CAPTCHA_IMAGE_PATH, 'wb') as f:
        f.write(img)
    return captcha.solve_captcha(CAPTCHA_IMAGE_PATH).strip().upper()


def get_jwt_token(resource_id, file_format, max_attempts=12):
    """Solve captchas until a JWT is issued for this resource (or give up)."""
    file_type = ext_from_format(file_format)
    for _ in range(max_attempts):
        token, sid = fetch_captcha_token()
        captcha_response = solve_captcha_for(sid, token)
        payload = {
            "name": [{"value": "Resource Download"}],
            "field_domain": ["4"],
            "field_domain_visibility": ["4", "4"],
            "uid": [{"value": 0}],
            "ip": [{"value": ""}],
            "usage": [{"value": "2"}],
            "purpose": [{"value": "7"}],
            "file_type": [{"value": str(file_type)}],
            "export_status": [{"value": "download"}],
            "ogdp_captcha_sid": [{"value": str(sid)}],
            "ogdp_captcha_token": [{"value": str(token)}],
            "ogdp_captcha_response": [{"value": str(captcha_response)}],
            "catalog_id": [{"target_id": ""}],
            "resource_id": [{"target_id": str(resource_id)}],
            "parameters": {},
        }
        try:
            jwt = session.post(DOWNLOAD_LINK_GENERATOR, json=payload, timeout=30).json().get('jwt_access_token')
        except Exception:
            jwt = None
        if jwt:
            return jwt
        time.sleep(0.5)
    return None


def jwt_expiring_soon(jwt_token, buffer_seconds=30):
    try:
        payload = jwt_token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        exp = datetime.fromtimestamp(decoded['exp'], tz=timezone.utc)
        return (exp - datetime.now(tz=timezone.utc)).total_seconds() < buffer_seconds
    except Exception:
        return True


def classify_error(status_code, body, exc_name=None):
    """Return a short, groupable error code from a response or exception."""
    if exc_name:
        mapping = {
            'SSLError': 'SSL',
            'Timeout': 'TIMEOUT',
            'ConnectTimeout': 'TIMEOUT',
            'ReadTimeout': 'TIMEOUT',
            'ConnectionError': 'CONNECTION',
        }
        return mapping.get(exc_name, exc_name.upper())
    # Storage backend returns an XML <Error><Code>...</Code></Error> body
    if body:
        m = re.search(r'<Code>([^<]+)</Code>', body)
        if m:
            return m.group(1)  # e.g. SignatureDoesNotMatch, AccessDenied
    return f'HTTP_{status_code}'


def attempt_download(resource_id, jwt_token, uuid, file_format):
    """Returns (success, should_refresh_jwt, error_code, error_detail)."""
    url = DATASET_DOWNLOADER_URL.format(resource_id, jwt_token)
    ext = ext_from_format(file_format)
    filepath = os.path.join(DOWNLOADS_FOLDER, f"{uuid}.{ext}")
    try:
        resp = session.get(url, stream=True, timeout=300)
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return (True, False, '', '')
        if resp.status_code == 401:
            return (False, True, 'HTTP_401', 'JWT expired/unauthorized')
        body = resp.content[:2000].decode('utf-8', 'replace')
        code = classify_error(resp.status_code, body)
        return (False, False, code, f"Status {resp.status_code}: {body[:300]}")
    except requests.exceptions.RequestException as e:
        code = classify_error(None, None, exc_name=type(e).__name__)
        return (False, False, code, str(e)[:300])
    except Exception as e:
        return (False, False, 'UNEXPECTED', str(e)[:300])


def disk_uuids():
    out = set()
    for fname in os.listdir(DOWNLOADS_FOLDER):
        if os.path.isfile(os.path.join(DOWNLOADS_FOLDER, fname)):
            out.add(fname.split('.', 1)[0])
    return out


def get_missing_datasets(conn):
    """eligible DB rows whose file is not on disk."""
    present = disk_uuids()
    rows = conn.execute(
        f'SELECT "{DB_UUID_COL}", "{DB_NID_COL}", "{DB_FORMAT_COL}" FROM "{DB_TABLE}"'
    ).fetchall()
    missing = []
    for uuid, nid, fmt in rows:
        if uuid is None or nid is None:
            continue
        if ext_from_format(fmt) in SKIP_EXTENSIONS:
            continue
        if str(uuid) in present:
            continue
        if not re.fullmatch(r'\d+', str(nid).strip()):
            continue
        missing.append((str(uuid), str(int(nid)), fmt))
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None,
                    help='Only attempt the first N missing datasets (smoke test).')
    ap.add_argument('--skip-codes', type=str, default=None,
                    help='Comma-separated error codes whose previously-logged failures '
                         'should NOT be retried (e.g. SignatureDoesNotMatch).')
    args = ap.parse_args()

    skip_codes = set()
    if args.skip_codes:
        skip_codes = {c.strip() for c in args.skip_codes.split(',') if c.strip()}

    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
    conn = duckdb.connect(DB_PATH)

    missing = get_missing_datasets(conn)
    print(f"{len(missing)} eligible datasets missing from disk.")

    # If skipping known-hard error codes, drop UUIDs whose last logged failure
    # matches one of those codes.
    if skip_codes and os.path.exists(FAILURE_LOG_PATH):
        hard = set()
        with open(FAILURE_LOG_PATH, newline='') as f:
            for r in csv.DictReader(f):
                if r.get('error_code') in skip_codes:
                    hard.add(r['uuid'])
        before = len(missing)
        missing = [m for m in missing if m[0] not in hard]
        print(f"Skipping {before - len(missing)} datasets with prior error codes in {sorted(skip_codes)}.")

    if args.limit:
        missing = missing[:args.limit]
        print(f"--limit: attempting {len(missing)} datasets.")

    # Rewrite the failure log fresh for the datasets we touch this run.
    log_f = open(FAILURE_LOG_PATH, 'w', newline='')
    writer = csv.writer(log_f)
    writer.writerow(LOG_FIELDS)
    log_f.flush()

    jwt_token = None
    n_ok = n_fail = 0
    for i, (uuid, nid, fmt) in enumerate(missing, 1):
        file_type = ext_from_format(fmt)
        while True:
            if jwt_token is None or jwt_expiring_soon(jwt_token):
                jwt_token = get_jwt_token(nid, fmt)
                if not jwt_token:
                    writer.writerow([uuid, nid, file_type, 'CAPTCHA_FAILED',
                                     'Could not obtain JWT', datetime.now().isoformat()])
                    log_f.flush()
                    n_fail += 1
                    break
            ok, refresh, code, detail = attempt_download(nid, jwt_token, uuid, fmt)
            time.sleep(0.5)
            if ok:
                conn.execute(
                    f'UPDATE "{DB_TABLE}" SET "{DB_FLAG_COL}" = TRUE WHERE "{DB_UUID_COL}" = ?',
                    [uuid])
                n_ok += 1
                print(f"[{i}/{len(missing)}] OK   {uuid}")
                break
            if refresh:
                jwt_token = None
                continue
            writer.writerow([uuid, nid, file_type, code, detail, datetime.now().isoformat()])
            log_f.flush()
            n_fail += 1
            print(f"[{i}/{len(missing)}] FAIL {uuid}  {code}")
            break

    log_f.close()
    conn.close()
    print(f"\nDone. recovered={n_ok}  still_failing={n_fail}")
    print(f"Failure log: {FAILURE_LOG_PATH}")


if __name__ == '__main__':
    main()
