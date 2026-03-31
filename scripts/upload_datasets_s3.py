import logging
import boto3
from botocore.exceptions import ClientError
import os
import duckdb
import csv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database and folder paths
DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
DOWNLOADS_FOLDER = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads"
LOG_FILE_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/s3_upload_log.csv"

# S3 configuration
S3_BUCKET = "nic-ogdp-datasets"
S3_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"  # Base path in S3


def get_batch_mapping():
    """Query the database to get UUID to batch mapping."""
    try:
        conn = duckdb.connect(DB_PATH)
        result = conn.execute("""
            SELECT uuid, batch FROM raw_metadata_with_batch
        """).fetchall()
        conn.close()
        
        batch_mapping = {str(row[0]): row[1] for row in result}
        logging.info(f"Loaded batch mapping for {len(batch_mapping)} datasets")
        return batch_mapping
    except Exception as e:
        logging.error(f"Failed to query database: {e}")
        return {}


def upload_file(file_path, bucket, object_name):
    """Upload a file to S3 bucket."""
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(file_path, bucket, object_name)
        logging.info(f"Uploaded {object_name} to s3://{bucket}")
        return True
    except ClientError as e:
        logging.error(f"Failed to upload {object_name}: {e}")
        return False


def extract_uuid_from_filename(filename):
    """Extract UUID from filename (UUID is the part before the extension)."""
    return os.path.splitext(filename)[0]


def get_processed_files():
    """Load already-processed files from the log."""
    processed = set()
    if os.path.exists(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('status') == 'success':
                        processed.add(row.get('filename', ''))
        except Exception as e:
            logging.warning(f"Could not read log file: {e}")
    return processed


def log_upload(filename, uuid, batch, status, detail=""):
    """Log upload attempt to CSV file."""
    log_exists = os.path.exists(LOG_FILE_PATH)
    with open(LOG_FILE_PATH, 'a', newline='') as f:
        writer = csv.writer(f)
        if not log_exists:
            writer.writerow(['filename', 'uuid', 'batch', 'status', 'detail'])
        writer.writerow([filename, uuid, batch, status, detail])


if __name__ == "__main__":
    # Get batch mapping from database
    batch_mapping = get_batch_mapping()
    
    if not batch_mapping:
        logging.error("No batch mapping found. Exiting.")
        exit(1)
    
    # Get already processed files
    processed_files = get_processed_files()
    
    # Get list of files to upload (exclude only the log file)
    if not os.path.exists(DOWNLOADS_FOLDER):
        logging.error(f"Downloads folder not found: {DOWNLOADS_FOLDER}")
        exit(1)
    
    files_to_upload = [f for f in os.listdir(DOWNLOADS_FOLDER) 
                      if os.path.isfile(os.path.join(DOWNLOADS_FOLDER, f)) 
                      and f != os.path.basename(LOG_FILE_PATH)]
    
    logging.info(f"Found {len(files_to_upload)} files to upload")
    
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    # Upload each file
    for i, filename in enumerate(files_to_upload):
        if filename in processed_files:
            logging.info(f"Skipping {filename} (already uploaded)")
            skipped_count += 1
            continue
        
        uuid = extract_uuid_from_filename(filename)
        batch = batch_mapping.get(uuid)
        
        if batch is None:
            logging.warning(f"No batch found for {filename} (UUID: {uuid})")
            log_upload(filename, uuid, "N/A", "failed", "UUID not found in batch mapping")
            failed_count += 1
            continue
        
        # Create S3 object path with batch folder structure
        object_name = f"{S3_PREFIX}/batch_{batch}/{filename}"
        file_path = os.path.join(DOWNLOADS_FOLDER, filename)
        
        # Upload file to S3
        if upload_file(file_path, S3_BUCKET, object_name):
            log_upload(filename, uuid, batch, "success")
            success_count += 1
            if (i + 1) % 100 == 0:
                logging.info(f"Progress: {i + 1}/{len(files_to_upload)} files processed")
        else:
            log_upload(filename, uuid, batch, "failed", "Upload error")
            failed_count += 1
    
    logging.info(f"\n✓ Upload complete:")
    logging.info(f"  - {success_count} successful")
    logging.info(f"  - {failed_count} failed")
    logging.info(f"  - {skipped_count} skipped (already uploaded)")