import pandas as pd
import requests
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

def download_file(download_url, output_folder, index):
    try:
        filename = os.path.basename(download_url) or f"downloaded_file_{index}"
        file_path = os.path.join(output_folder, filename)
        resp = requests.get(download_url, stream=True)
        resp.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        print(f"Downloaded: {filename}")
    except Exception as e:
        print(f"Failed {download_url}: {e}")

def download_files_from_dataframe(df, link_column, output_folder, max_workers=8):
    os.makedirs(output_folder, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {
            exe.submit(download_file, row[link_column], output_folder, idx): idx
            for idx, row in df.iterrows()
        }
        for fut in as_completed(futures):
            pass  # all logging is inside download_file

if __name__ == "__main__":
    df = pd.read_csv('nic_sample_dataset.csv')
    download_files_from_dataframe(df, 'datafile', 'sample_downloaded_files', max_workers=16)
