"""Simple AI Kosh dataset downloader.

Reads an input CSV, walks the nid column, and downloads each dataset using the
shared captcha -> JWT -> file-download flow from download_core.py (the same
flow dataset-download.py uses).

Configure the three variables in the CONFIG block below:
    INPUT_CSV_PATH  - path to the input CSV
    NID_COLUMN      - name of the column holding the nid / resource id
    FILE_FORMAT     - MIME format to request (e.g. 'text/csv')
"""

import os
import csv
import time
import re

from download_core import (
    new_session,
    fetch_captcha_token,
    get_captcha_input,
    get_jwt_token,
    download_dataset,
)

# ---------------------------------------------------------------------------
# CONFIG - edit these
# ---------------------------------------------------------------------------
INPUT_CSV_PATH = '/home/aakash/NIC/Newfolder/ai_kosh_datasets_without_dates.csv'
NID_COLUMN = 'nid'
FILE_FORMAT = 'text/csv'

DOWNLOADS_FOLDER = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/aikosh_downloads'
CAPTCHA_IMAGE_PATH = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/scripts/captcha.jpeg'
LOG_FILE_PATH = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/aikosh_download_log.csv'
# ---------------------------------------------------------------------------


def dest_path_for(nid):
    ext = FILE_FORMAT.split('/')[-1] if FILE_FORMAT else 'csv'
    ext = ext.replace('geo+json', 'geojson').replace('vnd.ms-excel', 'xls')
    return os.path.join(DOWNLOADS_FOLDER, f"{nid}.{ext}")


if __name__ == "__main__":
    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
    session = new_session()
    # Load nids from the input CSV
    with open(INPUT_CSV_PATH, newline='') as f:
        reader = csv.DictReader(f)
        if NID_COLUMN not in reader.fieldnames:
            raise ValueError(f"Column '{NID_COLUMN}' not found in {INPUT_CSV_PATH}. "
                             f"Found: {reader.fieldnames}")
        nids = [str(r[NID_COLUMN]).strip() for r in reader if r.get(NID_COLUMN)]

    # Resume support: collect nids already logged as success
    logged_success = set()
    log_exists = os.path.exists(LOG_FILE_PATH)
    if log_exists:
        with open(LOG_FILE_PATH, newline='') as f:
            for row in csv.DictReader(f):
                if row.get('status') == 'success':
                    logged_success.add(row.get('nid'))

    # Snapshot nids already present as files in the downloads folder
    files_on_disk = {
        fname.split('.', 1)[0] for fname in os.listdir(DOWNLOADS_FOLDER)
    }

    def already_downloaded(nid):
        """True if the nid is logged as success AND the file is on disk."""
        return nid in logged_success and nid in files_on_disk

    log_file = open(LOG_FILE_PATH, 'a', newline='')
    log_writer = csv.writer(log_file)
    if not log_exists:
        log_writer.writerow(['nid', 'status', 'detail'])
        log_file.flush()

    jwt_token = None
    token = None
    sid = None

    for nid in nids:
        if already_downloaded(nid):
            print(f"Skipping {nid}: already downloaded")
            continue

        if not re.fullmatch(r'\d+', nid):
            print(f"Skipping {nid}: malformed nid")
            log_writer.writerow([nid, 'skipped', 'Malformed nid'])
            log_file.flush()
            continue

        while True:
            if jwt_token is None:
                token, sid = fetch_captcha_token(session)
                captcha_response = get_captcha_input(session, sid, token, CAPTCHA_IMAGE_PATH)
                if not captcha_response:
                    log_writer.writerow([nid, 'failed', 'Captcha input failed'])
                    log_file.flush()
                    break
                jwt_token = get_jwt_token(session, token, sid, captcha_response, nid, FILE_FORMAT)
                if not jwt_token:
                    print("Failed to get JWT token. Retrying captcha...")
                    continue

            success, should_retry, error_msg = download_dataset(session, nid, jwt_token, dest_path_for(nid))
            time.sleep(0.5)
            if success:
                log_writer.writerow([nid, 'success', ''])
                log_file.flush()
                break
            elif should_retry:
                print("JWT token expired. Getting new token...")
                jwt_token = None
            else:
                print(f"Skipping {nid} due to: {error_msg}")
                log_writer.writerow([nid, 'failed', error_msg])
                log_file.flush()
                break

    log_file.close()
