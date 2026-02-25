import requests
import json
import os
from PIL import Image
import pandas as pd
import time
import captcha
import logging
resource_info_metadata = 'https://www.data.gov.in/backend/dms/v1/resource/{}?_format=json'
captcha_token_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
captcha_image_gen = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
download_link_generator = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
dataset_downloader_url = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'

metadata_csv_path = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/sample_datasets_metadata/nic_sample_dataset.csv'
downloads_folder = '/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/sample_downloaded_files'
captcha_image_path = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/scripts/captcha.jpeg"

os.makedirs(downloads_folder, exist_ok=True)

df = pd.read_csv(metadata_csv_path)




def fetch_captcha_token():
    response = requests.get(captcha_token_url)
    response = json.loads(response.text)
    token = response['token']
    sid = response['sid']
    print(f"Captcha Token: {token}, Captcha SID: {sid}")
    return token, sid

def get_captcha_input(sid, token):
    captcha_image_url = captcha_image_gen.format(sid, token)
    print(f"Captcha Image URL: {captcha_image_url}")
    try:
        with open(captcha_image_path, "wb") as file:
            file.write(requests.get(captcha_image_url).content)
        print(f"Captcha image saved to: {captcha_image_path}")
    except Exception as e:
        print(f"Error downloading captcha image: {e}")
        return None

    captcha_response = captcha.solve_captcha(captcha_image_path).strip().upper()
    return captcha_response




def get_jwt_token(token, sid, captcha_response, resource_id, file_format):


    payload = {
        "name":[{"value":"Aakash Gandhi "}],
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
        "email":[{"value":"akashgandhi622@gmail.com"}],
        "catalog_id":[{"target_id":""}],
        "resource_id":[{"target_id":str(resource_id)}],
        "parameters":{}
    }

    response = requests.post(download_link_generator, json=payload)
    response = json.loads(response.text)
    jwt_token = response.get('jwt_access_token')
    return jwt_token





def download_dataset(resource_id, jwt_token, uuid, file_format):
    logging.basicConfig(filename="dataset-dataset-status.log", level=logging.INFO)
    download_url = dataset_downloader_url.format(resource_id, jwt_token)
    file_extension = file_format.split('/')[-1] if file_format else 'csv'
    file_extension = file_extension.replace('geo+json', 'geojson')

    if file_extension == 'geojson':
        skip_msg = f"Skipped GeoJSON format"
        print(f"Skipping {uuid}: {skip_msg}")
        logging.info(f"UUID: {uuid} | Resource: {resource_id} | {skip_msg}")
        return (False, False, skip_msg)

    filename = f"{uuid}.{file_extension}"
    filepath = os.path.join(downloads_folder, filename)

    try:
        response = requests.get(download_url, stream=True, timeout=300)

        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded: {filename}")
            return (True, False, "")

        # JWT token expiration - should retry
        elif response.status_code in [401]:
            error_msg = f"JWT token expired/unauthorized - Status: {response.status_code}"
            print(f"JWT auth error for {uuid}: {error_msg}")
            return (False, True, error_msg)

        # Server errors - skip and log
        elif response.status_code in [500, 502, 503, 504]:
            error_msg = f"Server error - Status: {response.status_code}"
            print(f"Server error for {uuid}: {error_msg}")
            logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
            return (False, False, error_msg)

        # Other HTTP errors (400, 404, etc.) - skip and log
        else:
            error_msg = f"HTTP error - Status: {response.status_code}"
            print(f"HTTP error for {uuid}: {error_msg}")
            logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
            return (False, False, error_msg)

    except requests.exceptions.SSLError as e:
        error_msg = f"SSL Certificate Error: {str(e)}"
        print(f"SSL error for {uuid}: {error_msg}")
        logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
        return (False, False, error_msg)

    except requests.exceptions.Timeout as e:
        error_msg = f"Timeout Error: {str(e)}"
        print(f"Timeout error for {uuid}: {error_msg}")
        logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
        return (False, False, error_msg)

    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection Error: {str(e)}"
        print(f"Connection error for {uuid}: {error_msg}")
        logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
        return (False, False, error_msg)

    except Exception as e:
        error_msg = f"Unexpected Error: {str(e)}"
        print(f"Unexpected error for {uuid}: {error_msg}")
        logging.error(f"UUID: {uuid} | Resource: {resource_id} | {error_msg}")
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

    for index, row in df.iterrows():
        resource_id = row.get('nid')
        uuid = row.get('uuid')
        file_format = row.get('file_format')
        print(file_format.split('/')[-1])
        field_resource_type = row.get('field_resource_type')

        if pd.isna(resource_id) or pd.isna(uuid):
            print(f"Skipping row {index}: Missing resource_id or uuid")
            continue

        if str(field_resource_type) == '5':
            print(f"Skipping row {index}: field_resource_type is 5")
            continue

        resource_id = str(int(resource_id))

        while True:
            if jwt_token is None:
                token, sid = fetch_captcha_token()
                captcha_response = get_captcha_input(sid, token)
                if not captcha_response:
                    print("Failed to get captcha input. Exiting.")
                    break
                jwt_token = get_jwt_token(token, sid, captcha_response, resource_id, file_format)
                if not jwt_token:
                    print("Failed to get JWT token. Retrying captcha...")
                    continue

            success, should_retry, error_msg = download_dataset(resource_id, jwt_token, uuid, file_format)
            time.sleep(2)

            if success:
                break
            elif should_retry:
                print("JWT token may have expired. Getting new token...")
                jwt_token = None
            else:
                # Server/network error - skip this dataset
                print(f"Skipping dataset due to: {error_msg}")
                break
