import logging
import boto3
from botocore.exceptions import ClientError
import os
import duckdb
import csv
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database and folder paths
DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
DOWNLOADS_FOLDER = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads"
LOG_FILE_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/s3_upload_log.csv"

# S3 configuration
S3_BUCKET = "nic-ogdp-datasets"
S3_PREFIX = "downloaded-datasets/downloaded-datasets-mohfw"  # Base path in S3


def get_batches_from_db():
    """Query the database to get batches with their UUIDs and total counts."""
    try:
        conn = duckdb.connect(DB_PATH)
        result = conn.execute("""
            SELECT batch, uuid FROM raw_metadata ORDER BY batch
        """).fetchall()
        conn.close()

        batches = defaultdict(set)
        for batch, uuid in result:
            batches[batch].add(str(uuid))

        logging.info(f"Loaded {len(batches)} batches from database")
        return batches
    except Exception as e:
        logging.error(f"Failed to query database: {e}")
        return {}


def get_uploaded_uuids_by_batch():
    """Load successfully uploaded UUIDs grouped by batch from the log."""
    uploaded = defaultdict(set)
    if os.path.exists(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('status') == 'success':
                        batch = row.get('batch')
                        uuid = row.get('uuid', '')
                        if batch and uuid:
                            uploaded[batch].add(uuid)
        except Exception as e:
            logging.warning(f"Could not read log file: {e}")
    return uploaded


def upload_file(s3_client, file_path, bucket, object_name):
    """Upload a file to S3 bucket."""
    try:
        s3_client.upload_file(file_path, bucket, object_name)
        return True
    except ClientError as e:
        logging.error(f"Failed to upload {object_name}: {e}")
        return False


def log_upload(log_writer, filename, uuid, batch, status, detail=""):
    """Log upload attempt to CSV file."""
    log_writer.writerow([filename, uuid, batch, status, detail])


def build_filename_index(downloads_folder):
    """Build a uuid -> filename map for all files in the downloads folder."""
    index = {}
    for filename in os.listdir(downloads_folder):
        if os.path.isfile(os.path.join(downloads_folder, filename)):
            uuid = os.path.splitext(filename)[0]
            index[uuid] = filename
    return index


if __name__ == "__main__":
    # Load batch -> {uuids} from DB (one query, no repeated lookups)
    db_batches = get_batches_from_db()

    if not db_batches:
        logging.error("No batch data found. Exiting.")
        exit(1)

    # Load already-uploaded uuids per batch from the log (one pass)
    uploaded_by_batch = get_uploaded_uuids_by_batch()

    if not os.path.exists(DOWNLOADS_FOLDER):
        logging.error(f"Downloads folder not found: {DOWNLOADS_FOLDER}")
        exit(1)

    # Build a uuid -> filename index once so we never re-scan the folder
    uuid_to_file = build_filename_index(DOWNLOADS_FOLDER)
    logging.info(f"Found {len(uuid_to_file)} files in downloads folder")

    s3_client = boto3.client('s3')
    success_count = 0
    failed_count = 0
    skipped_batches = 0

    log_exists = os.path.exists(LOG_FILE_PATH)
    log_fh = open(LOG_FILE_PATH, 'a', newline='')
    log_writer = csv.writer(log_fh)
    if not log_exists:
        log_writer.writerow(['filename', 'uuid', 'batch', 'status', 'detail'])

    try:
        for batch in sorted(db_batches.keys()):
            batch_uuids = db_batches[batch]
            already_uploaded = uploaded_by_batch.get(str(batch), set())

            # Skip entire batch if all UUIDs are already logged as success
            if batch_uuids <= already_uploaded:
                logging.info(f"Batch {batch}: all {len(batch_uuids)} files already uploaded, skipping")
                skipped_batches += 1
                continue

            pending = batch_uuids - already_uploaded
            logging.info(f"Batch {batch}: {len(pending)} of {len(batch_uuids)} files to upload")

            for uuid in pending:
                filename = uuid_to_file.get(uuid)
                if filename is None:
                    logging.warning(f"Batch {batch}: no file found for UUID {uuid}")
                    log_upload(log_writer, f"{uuid}.(missing)", uuid, batch, "failed", "File not found in downloads folder")
                    failed_count += 1
                    continue

                object_name = f"{S3_PREFIX}/batch_{batch}/{filename}"
                file_path = os.path.join(DOWNLOADS_FOLDER, filename)

                if upload_file(s3_client, file_path, S3_BUCKET, object_name):
                    log_upload(log_writer, filename, uuid, batch, "success")
                    success_count += 1
                else:
                    log_upload(log_writer, filename, uuid, batch, "failed", "Upload error")
                    failed_count += 1

            log_fh.flush()
            logging.info(f"Batch {batch}: done (running totals — success: {success_count}, failed: {failed_count})")
    finally:
        log_fh.close()

    logging.info(f"\nUpload complete:")
    logging.info(f"  - {skipped_batches} batches skipped (fully uploaded)")
    logging.info(f"  - {success_count} files uploaded successfully")
    logging.info(f"  - {failed_count} files failed")