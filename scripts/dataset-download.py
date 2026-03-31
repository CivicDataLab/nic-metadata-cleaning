import requests
import json
import os
import base64
from datetime import datetime, timezone
import csv
import pandas as pd
import time
import re
import captcha
import openpyxl

resource_info_metadata = 'https://www.data.gov.in/backend/dms/v1/resource/{}?_format=json'
captcha_token_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
captcha_image_gen = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
download_link_generator = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
dataset_downloader_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'

metadata_csv_path = '/home/aakash/NIC/Newfolder/ResourceList_DoFHW/ResourceList_Department-of-Health-and-Family-Welfare.xlsx'
downloads_folder = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads'
#downloads_folder = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/sample_downloaded_files'
captcha_image_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/scripts/captcha.jpeg"

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

    jwt_token = None
    token = None
    sid = None

    # Load already-processed UUIDs from existing log to allow resuming
    processed_uuids = set()
    log_exists = os.path.exists(log_file_path)
    if log_exists:
        with open(log_file_path, 'r', newline='') as existing_log:
            reader = csv.DictReader(existing_log)
            for log_row in reader:
                if log_row.get('uuid'):
                    processed_uuids.add(log_row['uuid'])
        print(f"Resuming: {len(processed_uuids)} already-processed entries found in log.")

    # Initialize CSV log file
    log_file = open(log_file_path, 'a', newline='')
    log_writer = csv.writer(log_file)
    if not log_exists:
        log_writer.writerow(['uuid', 'file_type', 'status', 'detail'])
        log_file.flush()

    for index, row in df.iterrows():
        resource_id = row.get('nid')
        uuid = row.get('uuid')
        file_format = row.get('file_format')
        file_type = file_format.split('/')[-1] if file_format else 'unknown'
        print(file_type)
        field_resource_type = row.get('field_resource_type')

        if str(uuid) in processed_uuids:
            print(f"Skipping row {index}: already processed ({uuid})")
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



