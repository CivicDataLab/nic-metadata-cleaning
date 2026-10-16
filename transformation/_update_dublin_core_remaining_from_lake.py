"""
One-off: refresh the local dublin_core_remaining table from the DuckLake
lakehouse (catalog on Neon Postgres, data on S3).

Mirrors the AWS-credential bridging in copy_metadata_to_ducklake.py, since
this machine's `aws` CLI resolves creds via a "login" provider that DuckDB's
credential_chain can't see directly without CHAIN 'env'.
"""

import json
import os
import subprocess

import duckdb
from dotenv import load_dotenv

load_dotenv()

METADATA_DB_PATH = "metadata.db"

PG_CONN = (
    "dbname=neondb "
    "host=ep-summer-mountain-atxg8au1-pooler.c-9.us-east-1.aws.neon.tech "
    "user=neondb_owner "
    f"password={os.environ['NEON_PG_PASSWORD']} "  # from .env
    "sslmode=require "
    "connect_timeout=15"
)

S3_DATA_PATH = "s3://nic-ogdp-datasets/metadata/ducklake/"
S3_REGION = "ap-south-1"

LAKE_NAME = "metadata_lake"


def _load_aws_creds_into_env():
    result = subprocess.run(
        ["aws", "configure", "export-credentials", "--format", "process"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    creds = json.loads(result.stdout)
    os.environ["AWS_ACCESS_KEY_ID"] = creds["AccessKeyId"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = creds["SecretAccessKey"]
    if creds.get("SessionToken"):
        os.environ["AWS_SESSION_TOKEN"] = creds["SessionToken"]


def main():
    con = duckdb.connect(METADATA_DB_PATH)

    for ext in ("ducklake", "postgres", "httpfs"):
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")

    _load_aws_creds_into_env()
    con.execute(
        f"""
        CREATE OR REPLACE SECRET nic_s3 (
            TYPE s3,
            PROVIDER credential_chain,
            CHAIN 'env',
            REGION '{S3_REGION}'
        )
        """
    )

    con.execute("SET http_timeout=300000")
    con.execute("SET http_retries=10")
    con.execute("SET http_retry_backoff=4")
    con.execute("SET http_retry_wait_ms=500")

    con.execute(
        f"ATTACH 'ducklake:postgres:{PG_CONN}' AS {LAKE_NAME} "
        f"(DATA_PATH '{S3_DATA_PATH}', READ_ONLY)"
    )

    lake_count = con.execute(
        f"SELECT COUNT(*) FROM {LAKE_NAME}.dublin_core_remaining"
    ).fetchone()[0]
    print(f"Lake dublin_core_remaining row count: {lake_count}")

    local_count_before = con.execute(
        "SELECT COUNT(*) FROM dublin_core_remaining"
    ).fetchone()[0]
    print(f"Local dublin_core_remaining row count before: {local_count_before}")

    con.execute(
        f"CREATE OR REPLACE TABLE dublin_core_remaining AS "
        f"SELECT * FROM {LAKE_NAME}.dublin_core_remaining"
    )

    local_count_after = con.execute(
        "SELECT COUNT(*) FROM dublin_core_remaining"
    ).fetchone()[0]
    print(f"Local dublin_core_remaining row count after: {local_count_after}")

    con.execute(f"DETACH {LAKE_NAME}")
    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
