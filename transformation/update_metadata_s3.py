import logging
import boto3
from botocore.exceptions import ClientError
import os
import duckdb
import tempfile
from datetime import datetime


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

S3_BUCKET = "nic-ogdp-datasets"
S3_PREFIX = "metadata"  # Base path in S3


def get_s3_client():
    return boto3.client('s3')


def upload_file(file_path, bucket, object_name):
    s3_client = get_s3_client()
    try:
        s3_client.upload_file(file_path, bucket, object_name)
        logging.info(f"Uploaded {object_name} to s3://{bucket}")
        return True
    except ClientError as e:
        logging.error(f"Failed to upload {object_name}: {e}")
        return False


def get_tables_from_db():
    try:
        conn = duckdb.connect(DB_PATH)
        result = conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main'
        """).fetchall()
        conn.close()

        tables = [row[0] for row in result]
        logging.info(f"Found {len(tables)} tables in database: {tables}")
        return tables
    except Exception as e:
        logging.error(f"Failed to get tables from database: {e}")
        return []


def export_table_to_parquet(table_name, output_path):
    try:
        conn = duckdb.connect(DB_PATH)

        # Get row count for logging
        count_result = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchall()
        row_count = count_result[0][0]

        # Export to parquet
        conn.execute(f"COPY (SELECT * FROM {table_name}) TO '{output_path}' (FORMAT PARQUET)")
        conn.close()

        logging.info(f" Exported {table_name} ({row_count:,} rows) to {output_path}")
        return True
    except Exception as e:
        logging.error(f"✗ Failed to export {table_name}: {e}")
        return False


def upload_metadata_to_s3():
    logging.info("=" * 60)
    logging.info("Starting metadata export to S3...")
    logging.info("=" * 60)

    # Get list of tables
    tables = get_tables_from_db()

    if not tables:
        logging.error("No tables found in database. Exiting.")
        return False

    # Create temporary directory for parquet files
    with tempfile.TemporaryDirectory() as temp_dir:
        logging.info(f"Using temporary directory: {temp_dir}")

        success_count = 0
        failed_count = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Export each table and upload to S3
        for table_name in tables:
            try:
                # Export table to parquet
                parquet_filename = f"{table_name}.parquet"
                local_path = os.path.join(temp_dir, parquet_filename)

                if not export_table_to_parquet(table_name, local_path):
                    failed_count += 1
                    continue

                # Upload to S3
                s3_object_name = f"{S3_PREFIX}/{timestamp}/{parquet_filename}"

                if upload_file(local_path, S3_BUCKET, s3_object_name):
                    success_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                logging.error(f"✗ Error processing table {table_name}: {e}")
                failed_count += 1

        # Summary
        logging.info("=" * 60)
        logging.info(f"Export complete:")
        logging.info(f"  - {success_count} tables successfully uploaded")
        logging.info(f"  - {failed_count} tables failed")
        logging.info(f"  - S3 location: s3://{S3_BUCKET}/{S3_PREFIX}/{timestamp}/")
        logging.info("=" * 60)

        return success_count > 0 and failed_count == 0


if __name__ == "__main__":
    try:
        success = upload_metadata_to_s3()
        exit(0 if success else 1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        exit(1)
