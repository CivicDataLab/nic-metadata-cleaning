import argparse
import logging
import boto3
from botocore.exceptions import ClientError
import os
import re
import duckdb
import csv
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Repo root, so the paths below work on any checkout
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database and folder paths
DB_PATH = os.path.join(REPO_ROOT, "transformation/metadata.db")
DOWNLOADS_FOLDER = os.path.join(REPO_ROOT, "data/lot3_downloads")
LOG_FILE_PATH = os.path.join(REPO_ROOT, "s3_upload_lot3_log.csv")

# Ministry mode paths (remaining-raw-datasets live in the final batch folder)
MINISTRY_DOWNLOADS_FOLDER = os.path.join(REPO_ROOT, "data/final_batch_downloads")
MINISTRY_LOG_FILE_PATH = os.path.join(REPO_ROOT, "s3_upload_ministry_log.csv")

# S3 configuration
S3_BUCKET = "nic-ogdp-datasets"
S3_PREFIX = "downloaded-datasets/downloaded-datasets-lot-3"  # Base path in S3
S3_MINISTRY_PREFIX = "downloaded-datasets"  # Ministry folders are created under this


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


def slugify_ministry(name):
    """Turn a ministry name into a lowercase-hyphen S3 folder name."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug or "unknown-ministry"


def get_ministries_from_db():
    """Query remaining-raw-datasets for ministry -> {uuids} of downloaded files."""
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = conn.execute("""
            SELECT ministry_department, uuid
            FROM "remaining-raw-datasets"
            WHERE file_present AND ministry_department IS NOT NULL
              AND TRIM(ministry_department) <> ''
            ORDER BY ministry_department
        """).fetchall()
        conn.close()

        ministries = defaultdict(set)
        for ministry, uuid in result:
            ministries[ministry.strip()].add(str(uuid))

        logging.info(f"Loaded {len(ministries)} ministries from database")
        return ministries
    except Exception as e:
        logging.error(f"Failed to query database: {e}")
        return {}


def get_lot3_uuids_from_db():
    """Query dublin_core_lot3 for the UUIDs whose file was downloaded."""
    try:
        conn = duckdb.connect(DB_PATH, read_only=True)
        result = conn.execute("""
            SELECT "Identifier[UUID]"
            FROM dublin_core_lot3
            WHERE file_present
        """).fetchall()
        conn.close()

        uuids = {str(row[0]) for row in result}
        logging.info(f"Loaded {len(uuids)} downloaded lot-3 UUIDs from database")
        return uuids
    except Exception as e:
        logging.error(f"Failed to query database: {e}")
        return set()


def get_uploaded_uuids_by_batch():
    """Load successfully uploaded UUIDs grouped by batch from the log."""
    return _get_uploaded_uuids(LOG_FILE_PATH, 'batch')


def get_uploaded_uuids_by_ministry():
    """Load successfully uploaded UUIDs grouped by ministry from the ministry log."""
    return _get_uploaded_uuids(MINISTRY_LOG_FILE_PATH, 'ministry')


def _get_uploaded_uuids(log_path, group_field):
    """Load successfully uploaded UUIDs grouped by the given column from a log."""
    uploaded = defaultdict(set)
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('status') == 'success':
                        group = row.get(group_field)
                        uuid = row.get('uuid', '')
                        if group and uuid:
                            uploaded[group].add(uuid)
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
            # Split on the first dot: some extensions carry dots of their own
            # (e.g. .vnd.android.package-archive), which splitext would keep.
            uuid = filename.split('.', 1)[0]
            index[uuid] = filename
    return index


def run_batch_mode(dry_run=False):
    """Upload files into batch_<n> folders, driven by raw_metadata."""
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

    s3_client = None if dry_run else boto3.client('s3')
    success_count = 0
    failed_count = 0
    skipped_batches = 0

    # In dry-run nothing is recorded, so send log rows to /dev/null
    log_exists = dry_run or os.path.exists(LOG_FILE_PATH)
    log_fh = open(os.devnull if dry_run else LOG_FILE_PATH, 'a', newline='')
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

                if dry_run:
                    logging.info(f"[dry-run] {file_path} -> s3://{S3_BUCKET}/{object_name}")
                    success_count += 1
                elif upload_file(s3_client, file_path, S3_BUCKET, object_name):
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


def run_lot3_mode(dry_run=False):
    """Upload lot-3 files flat under S3_PREFIX, driven by dublin_core_lot3.

    Lot 3 carries no batch numbers (dublin_core_lot3.batch is NULL throughout),
    so there is no batch_<n> layout to reproduce here.
    """
    db_uuids = get_lot3_uuids_from_db()

    if not db_uuids:
        logging.error("No lot-3 data found. Exiting.")
        exit(1)

    if not os.path.exists(DOWNLOADS_FOLDER):
        logging.error(f"Downloads folder not found: {DOWNLOADS_FOLDER}")
        exit(1)

    uuid_to_file = build_filename_index(DOWNLOADS_FOLDER)
    logging.info(f"Found {len(uuid_to_file)} files in {DOWNLOADS_FOLDER}")

    already_uploaded = _get_uploaded_uuids(LOG_FILE_PATH, 'lot').get('lot3', set())
    pending = sorted(db_uuids - already_uploaded)
    logging.info(f"{len(pending)} of {len(db_uuids)} files to upload "
                 f"({len(already_uploaded)} already logged as uploaded)")

    unknown = set(uuid_to_file) - db_uuids
    if unknown:
        logging.warning(f"{len(unknown)} files in the folder are not file_present "
                        f"in dublin_core_lot3 (not uploaded)")

    if not pending:
        logging.info("Nothing to do.")
        return

    s3_client = None if dry_run else boto3.client('s3')
    success_count = 0
    failed_count = 0

    log_exists = dry_run or os.path.exists(LOG_FILE_PATH)
    log_fh = open(os.devnull if dry_run else LOG_FILE_PATH, 'a', newline='')
    log_writer = csv.writer(log_fh)
    if not log_exists:
        log_writer.writerow(['filename', 'uuid', 'lot', 'status', 'detail'])

    try:
        for i, uuid in enumerate(pending, 1):
            filename = uuid_to_file.get(uuid)
            if filename is None:
                logging.warning(f"No file found for UUID {uuid}")
                log_upload(log_writer, f"{uuid}.(missing)", uuid, 'lot3', "failed",
                           "File not found in downloads folder")
                failed_count += 1
                continue

            object_name = f"{S3_PREFIX}/{filename}"
            file_path = os.path.join(DOWNLOADS_FOLDER, filename)

            if dry_run:
                logging.info(f"[dry-run] {file_path} -> s3://{S3_BUCKET}/{object_name}")
                success_count += 1
            elif upload_file(s3_client, file_path, S3_BUCKET, object_name):
                log_upload(log_writer, filename, uuid, 'lot3', "success")
                success_count += 1
            else:
                log_upload(log_writer, filename, uuid, 'lot3', "failed", "Upload error")
                failed_count += 1

            if i % 250 == 0:
                log_fh.flush()
                logging.info(f"{i}/{len(pending)} processed "
                             f"(success: {success_count}, failed: {failed_count})")
    finally:
        log_fh.close()

    logging.info(f"\nUpload complete:")
    logging.info(f"  - {success_count} files uploaded successfully")
    logging.info(f"  - {failed_count} files failed")


def run_ministry_mode(dry_run=False):
    """Upload files into one folder per ministry, driven by remaining-raw-datasets."""
    db_ministries = get_ministries_from_db()

    if not db_ministries:
        logging.error("No ministry data found. Exiting.")
        exit(1)

    uploaded_by_ministry = get_uploaded_uuids_by_ministry()

    if not os.path.exists(MINISTRY_DOWNLOADS_FOLDER):
        logging.error(f"Downloads folder not found: {MINISTRY_DOWNLOADS_FOLDER}")
        exit(1)

    uuid_to_file = build_filename_index(MINISTRY_DOWNLOADS_FOLDER)
    logging.info(f"Found {len(uuid_to_file)} files in {MINISTRY_DOWNLOADS_FOLDER}")

    s3_client = None if dry_run else boto3.client('s3')
    success_count = 0
    failed_count = 0
    skipped_ministries = 0

    log_exists = dry_run or os.path.exists(MINISTRY_LOG_FILE_PATH)
    log_fh = open(os.devnull if dry_run else MINISTRY_LOG_FILE_PATH, 'a', newline='')
    log_writer = csv.writer(log_fh)
    if not log_exists:
        log_writer.writerow(['filename', 'uuid', 'ministry', 'status', 'detail'])

    try:
        for ministry in sorted(db_ministries.keys()):
            ministry_uuids = db_ministries[ministry]
            already_uploaded = uploaded_by_ministry.get(ministry, set())
            folder = slugify_ministry(ministry)

            if ministry_uuids <= already_uploaded:
                logging.info(f"{ministry}: all {len(ministry_uuids)} files already uploaded, skipping")
                skipped_ministries += 1
                continue

            pending = ministry_uuids - already_uploaded
            logging.info(f"{ministry} -> {folder}/: {len(pending)} of {len(ministry_uuids)} files to upload")

            for uuid in pending:
                filename = uuid_to_file.get(uuid)
                if filename is None:
                    logging.warning(f"{ministry}: no file found for UUID {uuid}")
                    log_upload(log_writer, f"{uuid}.(missing)", uuid, ministry, "failed", "File not found in downloads folder")
                    failed_count += 1
                    continue

                object_name = f"{S3_MINISTRY_PREFIX}/{folder}/{filename}"
                file_path = os.path.join(MINISTRY_DOWNLOADS_FOLDER, filename)

                if dry_run:
                    logging.info(f"[dry-run] {file_path} -> s3://{S3_BUCKET}/{object_name}")
                    success_count += 1
                elif upload_file(s3_client, file_path, S3_BUCKET, object_name):
                    log_upload(log_writer, filename, uuid, ministry, "success")
                    success_count += 1
                else:
                    log_upload(log_writer, filename, uuid, ministry, "failed", "Upload error")
                    failed_count += 1

            log_fh.flush()
            logging.info(f"{ministry}: done (running totals — success: {success_count}, failed: {failed_count})")

    finally:
        log_fh.close()

    # Files sitting in the folder with no row in remaining-raw-datasets
    known_uuids = set().union(*db_ministries.values())
    unknown = set(uuid_to_file) - known_uuids
    if unknown:
        logging.warning(f"{len(unknown)} files in the folder have no ministry in remaining-raw-datasets (not uploaded)")

    logging.info(f"\nUpload complete:")
    logging.info(f"  - {skipped_ministries} ministries skipped (fully uploaded)")
    logging.info(f"  - {success_count} files uploaded successfully")
    logging.info(f"  - {failed_count} files failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Upload downloaded datasets to S3, grouped by batch or by ministry."
    )
    parser.add_argument(
        '--by-ministry',
        action='store_true',
        help="Upload remaining-raw-datasets files into one S3 folder per ministry_department "
             f"under {S3_MINISTRY_PREFIX}/, instead of the default batch_<n> layout.",
    )
    parser.add_argument(
        '--lot3',
        action='store_true',
        help="Upload the downloaded lot-3 files (dublin_core_lot3 where file_present) flat "
             f"under {S3_PREFIX}/. Lot 3 has no batch numbers, so batch mode does not apply.",
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Print the S3 keys that would be written without uploading or logging.",
    )
    args = parser.parse_args()

    if args.by_ministry and args.lot3:
        parser.error("--by-ministry and --lot3 are mutually exclusive")

    if args.lot3:
        run_lot3_mode(dry_run=args.dry_run)
    elif args.by_ministry:
        run_ministry_mode(dry_run=args.dry_run)
    else:
        run_batch_mode(dry_run=args.dry_run)
