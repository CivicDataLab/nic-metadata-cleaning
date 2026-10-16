"""Shared data.gov.in DMS download helpers.

Importable, side-effect free. Both dataset-download.py and
aikosh_dataset_download.py can reuse these instead of duplicating the
captcha -> JWT -> file-download flow.

Every function takes an explicit `session` and destination, so nothing here
depends on module-level globals or writes anything at import time.
"""

import os
import json
import requests
import captcha

CAPTCHA_TOKEN_URL = 'https://www.data.gov.in/backend/dms/v1/ogdp/captcha/refresh/image/download_purpose?_format=json'
CAPTCHA_IMAGE_GEN = 'https://www.data.gov.in/backend/dms/v1/image-captcha-generate/{}/{}'
DOWNLOAD_LINK_GENERATOR = 'https://www.data.gov.in/backend/dms/v1/ogdp/download_purpose?_format=json'
DATASET_DOWNLOADER_URL = 'https://www.data.gov.in/backend/dms/v1/ogdp/resource/file/download/{}/{}'


def new_session():
    """A requests.Session with the header the DMS backend expects."""
    session = requests.Session()
    session.headers.update({'User-Agent': 'PostmanRuntime/7.51.1'})
    return session


def fetch_captcha_token(session):
    response = session.get(CAPTCHA_TOKEN_URL)
    data = json.loads(response.text)
    return data['token'], data['sid']


def get_captcha_input(session, sid, token, captcha_image_path):
    captcha_image_url = CAPTCHA_IMAGE_GEN.format(sid, token)
    try:
        with open(captcha_image_path, 'wb') as file:
            file.write(session.get(captcha_image_url).content)
    except Exception as e:
        print(f"Error downloading captcha image: {e}")
        return None
    return captcha.solve_captcha(captcha_image_path).strip().upper()


def get_jwt_token(session, token, sid, captcha_response, resource_id, file_format):
    file_type = file_format.split('/')[-1]
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
    response = session.post(DOWNLOAD_LINK_GENERATOR, json=payload)
    try:
        return response.json().get('jwt_access_token')
    except (ValueError, json.JSONDecodeError):
        # Wrong captcha / bad resource -> server returns a 500 HTML page, not JSON.
        print(f"No JWT (status {response.status_code}); likely wrong captcha. Will retry.")
        return None


def _real_extension(head):
    """Guess a file extension from the leading bytes, or None to keep as-is."""
    if head[:4] == b'\xd0\xcf\x11\xe0':      # OLE2 compound file
        return 'xls'
    if head[:2] == b'PK':                     # zip container
        return 'xlsx'
    return None


def download_dataset(session, resource_id, jwt_token, dest_path):
    """Stream the resource to dest_path.

    - Rejects auth/token-error bodies the server returns as HTTP 200
      (asks the caller to retry with a fresh token).
    - Fixes the extension when the real content is Excel, not the requested type.

    Returns (success, should_retry, error_msg).
    """
    download_url = DATASET_DOWNLOADER_URL.format(resource_id, jwt_token)
    try:
        response = session.get(download_url, stream=True, timeout=300)
        if response.status_code == 200:
            head = b''
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not head:
                        head = chunk
                    f.write(chunk)

            # HTTP 200 but the body is an auth/token error page, not data.
            low = head.lower()
            if b'not authoris' in low or b'token expired' in low or b'download token' in low:
                os.remove(dest_path)
                return (False, True, "Auth/token error body instead of data")

            # Correct the extension if the bytes say Excel but we named it .csv, etc.
            real_ext = _real_extension(head)
            final_path = dest_path
            if real_ext:
                base, cur_ext = os.path.splitext(dest_path)
                if cur_ext.lower().lstrip('.') != real_ext:
                    final_path = f"{base}.{real_ext}"
                    os.replace(dest_path, final_path)

            print(f"Downloaded: {final_path}")
            return (True, False, "")
        elif response.status_code == 401:
            return (False, True, "JWT token expired/unauthorized")
        else:
            return (False, False, f"HTTP error - Status: {response.status_code}")
    except Exception as e:
        return (False, False, f"Error: {e}")
