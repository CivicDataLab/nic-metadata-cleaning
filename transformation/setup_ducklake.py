"""
Set up the DuckLake catalog: Postgres (Neon) as the metadata catalog, S3 as the
parquet data store. This ONLY sets up / attaches the lake — it does NOT copy or
create any tables from metadata.db. Run it once to initialise the catalog.

Prereqs:
  - DuckDB extensions: ducklake, postgres, httpfs (auto-installed below).
  - S3 auth: this machine's `aws` CLI uses a non-standard "login" credential
    source (not env/file/IMDS), which DuckDB's credential_chain can't see
    directly. We bridge it in-process via `aws configure export-credentials`
    (JSON to a pipe, parsed in Python, never printed) and hand DuckDB the
    resulting short-lived keys through the env chain. Nothing is written to
    disk or stdout.
  - Outbound TCP 5432 to the Neon host must be reachable (intermittent on this
    network — retry if the ATTACH times out).
"""

import json
import os
import subprocess

import duckdb
from dotenv import load_dotenv

load_dotenv()


def _load_aws_creds_into_env():
    """Bridge the AWS CLI's 'login' credential source into env vars for this
    process only, via the CLI's own export-credentials command. Values are
    parsed from JSON and never printed/logged."""
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

# --- Catalog (Postgres / Neon) -------------------------------------------------
PG_CONN = (
    "dbname=neondb "
    "host=ep-summer-mountain-atxg8au1-pooler.c-9.us-east-1.aws.neon.tech "
    "user=neondb_owner "
    f"password={os.environ['NEON_PG_PASSWORD']} "  # from .env
    "sslmode=require "
    "connect_timeout=15"
)

# --- Data store (S3) -----------------------------------------------------------
S3_DATA_PATH = "s3://nic-ogdp-datasets/metadata/ducklake/"
S3_REGION = "ap-south-1"

LAKE_NAME = "metadata_lake"


def main():
    con = duckdb.connect()  # in-memory; the real state lives in Postgres + S3

    for ext in ("ducklake", "postgres", "httpfs"):
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")

    # S3 creds: bridge this machine's AWS CLI "login" credentials into env vars
    # (in-process only, never printed), then point DuckDB's credential_chain at
    # the env source specifically. This is only needed for S3 *writes* (at COPY
    # time); the catalog ATTACH below does not touch S3, so we don't hard-fail
    # if the AWS login is momentarily unavailable.
    try:
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
        s3_ok = True
    except Exception as e:  # noqa: BLE001 - report and continue; catalog is what matters here
        s3_ok = False
        print(f"WARN: S3 secret not created (AWS login unavailable?): {e}")
        print("      Catalog will still attach. Re-run after `aws sts get-caller-identity`")
        print("      returns quickly to enable S3 writes at COPY time.")

    # Attach the lake: Postgres holds the catalog, S3 holds the parquet/data files.
    # DuckLake stores ALL metadata in Postgres; DATA_PATH is just a recorded
    # string until the first data write, so this succeeds without S3 auth.
    con.execute(
        f"ATTACH 'ducklake:postgres:{PG_CONN}' AS {LAKE_NAME} "
        f"(DATA_PATH '{S3_DATA_PATH}', AUTOMATIC_MIGRATION TRUE)"
    )

    # Sanity check — the lake attaches with zero tables (nothing copied yet).
    con.execute(f"USE {LAKE_NAME}")
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Attached '{LAKE_NAME}': catalog=Neon Postgres, data={S3_DATA_PATH}")
    print(f"S3 secret ready: {s3_ok}")
    print(f"Tables in lake: {len(tables)} {tables if tables else '(empty — expected)'}")


if __name__ == "__main__":
    main()
