import boto3
import duckdb
import tempfile
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configure these ---
S3_BUCKET = "nic-ogdp-datasets"
S3_KEY = "metadata/CHANGEME/dublin_core_metadata.parquet"  # S3 key (path after the bucket name)
TABLE_NAME = "dublin_metadata_pii"               # Table name to create in the local DB
DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
# -----------------------

def main():
    s3 = boto3.client("s3")

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        logging.info(f"Downloading s3://{S3_BUCKET}/{S3_KEY}")
        s3.download_file(S3_BUCKET, S3_KEY, tmp_path)
        logging.info("Download complete")

        conn = duckdb.connect(DB_PATH)
        conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
        conn.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM read_parquet('{tmp_path}')")
        count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        conn.close()

        logging.info(f"Loaded {count} rows into table '{TABLE_NAME}' in {DB_PATH}")
    finally:
        os.unlink(tmp_path)

if __name__ == "__main__":
    main()