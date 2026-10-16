"""
Copy every table from the local metadata.db (DuckDB file) into the DuckLake
lakehouse (catalog on Neon Postgres, data on S3). Run this AFTER
setup_ducklake.py has attached an empty lake.

Idempotent: each table is loaded via CREATE OR REPLACE TABLE ... AS SELECT *,
so re-running overwrites the lake copy with the current metadata.db contents.

Usage:
    python copy_metadata_to_ducklake.py                        # every table
    python copy_metadata_to_ducklake.py dublin_core_remaining  # only these
"""

import json
import os
import subprocess
import sys

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
    import os

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
    con = duckdb.connect()

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

    # A wide 116k-row table goes out as one long-lived PUT, and the default 30s
    # http_timeout kills it ~6 min in with "SSL connect error" on this network
    # (the same WSL2 link that intermittently firewalls Neon's 5432).
    con.execute("SET http_timeout=300000")
    con.execute("SET http_retries=10")
    con.execute("SET http_retry_backoff=4")
    con.execute("SET http_retry_wait_ms=500")

    con.execute(
        f"ATTACH 'ducklake:postgres:{PG_CONN}' AS {LAKE_NAME} "
        f"(DATA_PATH '{S3_DATA_PATH}', AUTOMATIC_MIGRATION TRUE)"
    )
    con.execute(f"ATTACH '{METADATA_DB_PATH}' AS src (READ_ONLY)")

    tables = [
        r[0]
        for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'src'"
        ).fetchall()
    ]
    print(f"Found {len(tables)} tables in {METADATA_DB_PATH}: {tables}")

    # Optional table filter: refresh just the named tables instead of the lot.
    wanted = sys.argv[1:]
    if wanted:
        missing = [t for t in wanted if t not in tables]
        if missing:
            sys.exit(f"not in {METADATA_DB_PATH}: {missing}")
        tables = wanted
        print(f"Filtered to {len(tables)}: {tables}")

    for name in tables:
        qname = f'"{name}"'
        src_count = con.execute(f"SELECT COUNT(*) FROM src.main.{qname}").fetchone()[0]
        print(f"Copying {name} ({src_count} rows)...", flush=True)
        con.execute(
            f"CREATE OR REPLACE TABLE {LAKE_NAME}.{qname} AS "
            f"SELECT * FROM src.main.{qname}"
        )
        dst_count = con.execute(f"SELECT COUNT(*) FROM {LAKE_NAME}.{qname}").fetchone()[0]
        status = "OK" if dst_count == src_count else "MISMATCH"
        print(f"  -> {dst_count} rows in lake [{status}]", flush=True)

    print("Done.")


if __name__ == "__main__":
    main()
