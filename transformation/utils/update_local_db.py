import logging
import re
import boto3
from botocore.exceptions import ClientError
import os
import duckdb
import tempfile

SNAPSHOT_PATTERN = re.compile(r"^\d{8}_\d{6}$")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = "transformation/metadata.db"

S3_BUCKET = "nic-ogdp-datasets"
S3_PREFIX = "metadata"


def get_s3_client():
    return boto3.client('s3')


def get_latest_snapshot_prefix(s3_client) -> str | None:
    """Return the S3 prefix for the most recent timestamped snapshot folder."""
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{S3_PREFIX}/",
            Delimiter="/"
        )
        prefixes = [cp["Prefix"] for cp in response.get("CommonPrefixes", [])]
        snapshot_prefixes = [
            p for p in prefixes
            if SNAPSHOT_PATTERN.match(p[len(S3_PREFIX) + 1:].rstrip("/"))
        ]
        if not snapshot_prefixes:
            logging.error("No timestamped snapshot folders found in S3.")
            return None

        # Folder names are timestamps (YYYYMMDD_HHMMSS), so lexicographic max = latest
        latest = sorted(snapshot_prefixes)[-1]
        logging.info(f"Latest snapshot: s3://{S3_BUCKET}/{latest}")
        return latest
    except ClientError as e:
        logging.error(f"Failed to list S3 prefixes: {e}")
        return None


def list_parquet_files(s3_client, prefix: str) -> list[str]:
    """List all parquet object keys under the given prefix."""
    try:
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        keys = [obj["Key"] for obj in response.get("Contents", []) if obj["Key"].endswith(".parquet")]
        logging.info(f"Found {len(keys)} parquet file(s) in snapshot.")
        return keys
    except ClientError as e:
        logging.error(f"Failed to list parquet files: {e}")
        return []


def download_file(s3_client, key: str, local_path: str) -> bool:
    try:
        s3_client.download_file(S3_BUCKET, key, local_path)
        logging.info(f"✓ Downloaded s3://{S3_BUCKET}/{key}")
        return True
    except ClientError as e:
        logging.error(f"✗ Failed to download {key}: {e}")
        return False


def load_parquet_to_table(con: duckdb.DuckDBPyConnection, local_path: str, table_name: str) -> bool:
    try:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{local_path}')")
        row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        logging.info(f"✓ Loaded {table_name} ({row_count:,} rows) from parquet")
        return True
    except Exception as e:
        logging.error(f"✗ Failed to load {table_name}: {e}")
        return False


def update_local_db():
    logging.info("=" * 60)
    logging.info("Starting local DB update from S3...")
    logging.info("=" * 60)

    s3_client = get_s3_client()

    latest_prefix = get_latest_snapshot_prefix(s3_client)
    if not latest_prefix:
        return False

    keys = list_parquet_files(s3_client, latest_prefix)
    if not keys:
        logging.error("No parquet files found in latest snapshot. Exiting.")
        return False

    with tempfile.TemporaryDirectory() as temp_dir:
        logging.info(f"Using temporary directory: {temp_dir}")

        success_count = 0
        failed_count = 0

        con = duckdb.connect(DB_PATH)

        for key in keys:
            filename = os.path.basename(key)
            table_name = filename.replace(".parquet", "")
            local_path = os.path.join(temp_dir, filename)

            if not download_file(s3_client, key, local_path):
                failed_count += 1
                continue

            if load_parquet_to_table(con, local_path, table_name):
                success_count += 1
            else:
                failed_count += 1

        con.close()

    logging.info("=" * 60)
    logging.info(f"✓ Local DB update complete:")
    logging.info(f"  - {success_count} table(s) successfully updated")
    logging.info(f"  - {failed_count} table(s) failed")
    logging.info(f"  - DB location: {DB_PATH}")
    logging.info("=" * 60)

    return success_count > 0 and failed_count == 0


if __name__ == "__main__":
    try:
        success = update_local_db()
        exit(0 if success else 1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        exit(1)
