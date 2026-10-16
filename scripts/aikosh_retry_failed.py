"""Retry the AI Kosh nids that are still marked 'failed' in the download log.

Reads the cleaned download log, collects every nid whose status is 'failed',
and re-runs the shared captcha -> JWT -> file-download flow from download_core.

On success: the file is written to the downloads folder and that nid's row in
the main log is flipped to 'success'.
On persistent failure: the nid is written to failed_log.csv.

Run from the scripts/ directory (so `import captcha` / `import download_core`
resolve):
    python aikosh_retry_failed.py
"""

import os
import csv
import time
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from download_core import (
    new_session,
    fetch_captcha_token,
    get_captcha_input,
    get_jwt_token,
    download_dataset,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_FILE_PATH = os.path.join(REPO, 'data', 'aikosh_download_log.csv')
FAILED_LOG_PATH = os.path.join(REPO, 'data', 'failed_log.csv')
DOWNLOADS_FOLDER = os.path.join(REPO, 'data', 'aikosh_downloads')
CAPTCHA_IMAGE_PATH = os.path.join(REPO, 'scripts', 'captcha.jpeg')

FILE_FORMAT = 'text/csv'
MAX_CAPTCHA_ATTEMPTS = 6   # per nid, before giving up
# ---------------------------------------------------------------------------


def dest_path_for(nid):
    ext = FILE_FORMAT.split('/')[-1] if FILE_FORMAT else 'csv'
    ext = ext.replace('geo+json', 'geojson').replace('vnd.ms-excel', 'xls')
    return os.path.join(DOWNLOADS_FOLDER, f"{nid}.{ext}")


def load_log(path):
    """Return (header, rows) where rows is a list of dicts."""
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def main():
    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)

    header, rows = load_log(LOG_FILE_PATH)
    failed_nids = [r['nid'] for r in rows if r.get('status') == 'failed']
    print(f"Failed nids to retry: {len(failed_nids)}")
    if not failed_nids:
        print("Nothing to retry.")
        return

    session = new_session()
    jwt_token = token = sid = None

    # nid -> (still_failed?, detail)
    outcome = {}

    for nid in failed_nids:
        if not re.fullmatch(r'\d+', nid):
            outcome[nid] = (True, 'Malformed nid')
            print(f"Skipping {nid}: malformed nid")
            continue

        attempts = 0
        while True:
            if jwt_token is None:
                attempts += 1
                if attempts > MAX_CAPTCHA_ATTEMPTS:
                    outcome[nid] = (True, 'Exhausted captcha/JWT attempts')
                    print(f"❌ {nid}: exhausted attempts")
                    break
                token, sid = fetch_captcha_token(session)
                captcha_response = get_captcha_input(session, sid, token, CAPTCHA_IMAGE_PATH)
                if not captcha_response:
                    continue
                jwt_token = get_jwt_token(session, token, sid, captcha_response, nid, FILE_FORMAT)
                if not jwt_token:
                    print(f"{nid}: no JWT, retrying captcha...")
                    continue

            success, should_retry, error_msg = download_dataset(
                session, nid, jwt_token, dest_path_for(nid)
            )
            time.sleep(0.5)
            if success:
                outcome[nid] = (False, '')
                print(f"✅ {nid}: downloaded")
                break
            elif should_retry:
                print(f"{nid}: token expired, refreshing...")
                jwt_token = None
            else:
                outcome[nid] = (True, error_msg)
                print(f"❌ {nid}: {error_msg}")
                break

    # --- update the main log: flip recovered nids to success --------------
    for r in rows:
        nid = r['nid']
        if nid in outcome and not outcome[nid][0]:   # recovered
            r['status'] = 'success'
            r['detail'] = ''
    with open(LOG_FILE_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)

    # --- write failed_log.csv with the still-failing nids -----------------
    still_failed = [(nid, det) for nid, (bad, det) in outcome.items() if bad]
    with open(FAILED_LOG_PATH, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['nid', 'detail'])
        for nid, det in still_failed:
            writer.writerow([nid, det])

    recovered = sum(1 for bad, _ in outcome.values() if not bad)
    print("\n===== RETRY SUMMARY =====")
    print(f"Retried        : {len(failed_nids)}")
    print(f"Recovered      : {recovered}")
    print(f"Still failed   : {len(still_failed)}")
    print(f"Main log       : {LOG_FILE_PATH}")
    print(f"Failed log     : {FAILED_LOG_PATH}")


if __name__ == "__main__":
    main()
