"""Step-by-step diagnostic for copy_metadata_to_ducklake.py.

Every step prints before and after with an elapsed time and an explicit flush,
so a hang is distinguishable from an exception from buffered output. Prints no
credential values -- only whether each source resolved.

Run:  python3 -u _ducklake_diag.py
"""
import json
import os
import shutil
import subprocess
import sys
import time

from copy_metadata_to_ducklake import (
    LAKE_NAME, METADATA_DB_PATH, PG_CONN, S3_DATA_PATH, S3_REGION,
)


def step(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label} ...", flush=True)
    return time.time()


def ok(t0, extra=""):
    print(f"    OK ({time.time() - t0:.1f}s) {extra}", flush=True)


def fail(t0, e):
    print(f"    FAIL ({time.time() - t0:.1f}s) {type(e).__name__}: {str(e)[:400]}", flush=True)


print(f"python   {sys.version.split()[0]}", flush=True)
t = step("import duckdb")
try:
    import duckdb
    ok(t, duckdb.__version__)
except Exception as e:
    fail(t, e); sys.exit(1)

con = duckdb.connect()

t = step("INSTALL/LOAD ducklake, postgres, httpfs")
try:
    for ext in ("ducklake", "postgres", "httpfs"):
        con.execute(f"INSTALL {ext}"); con.execute(f"LOAD {ext}")
    ok(t)
except Exception as e:
    fail(t, e); sys.exit(1)

t = step("locate aws CLI")
aws = shutil.which("aws")
print(f"    shutil.which('aws') -> {aws!r}", flush=True)
if not aws:
    print("    PATH =", os.environ.get("PATH", ""), flush=True)
ok(t)

t = step("aws configure export-credentials")
creds_ok = False
try:
    r = subprocess.run(["aws", "configure", "export-credentials", "--format", "process"],
                       capture_output=True, text=True, timeout=60, check=True)
    c = json.loads(r.stdout)
    os.environ["AWS_ACCESS_KEY_ID"] = c["AccessKeyId"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = c["SecretAccessKey"]
    if c.get("SessionToken"):
        os.environ["AWS_SESSION_TOKEN"] = c["SessionToken"]
    creds_ok = True
    ok(t, f"keys present, expires {c.get('Expiration', 'n/a')}")
except Exception as e:
    fail(t, e)

t = step("CREATE SECRET nic_s3")
try:
    con.execute(f"""CREATE OR REPLACE SECRET nic_s3 (
        TYPE s3, PROVIDER credential_chain, CHAIN 'env', REGION '{S3_REGION}')""")
    ok(t)
except Exception as e:
    fail(t, e)

t = step(f"S3 read probe {S3_DATA_PATH}")
try:
    n = con.execute(f"SELECT count(*) FROM glob('{S3_DATA_PATH}**')").fetchone()[0]
    ok(t, f"{n} objects visible under data path")
except Exception as e:
    fail(t, e)

con.execute("SET http_timeout=300000")
con.execute("SET http_retries=10")
con.execute("SET http_retry_backoff=4")
con.execute("SET http_retry_wait_ms=500")

t = step("ATTACH Neon catalog (this is the usual hang point)")
try:
    con.execute(f"ATTACH 'ducklake:postgres:{PG_CONN}' AS {LAKE_NAME} "
                f"(DATA_PATH '{S3_DATA_PATH}', AUTOMATIC_MIGRATION TRUE)")
    ok(t)
except Exception as e:
    fail(t, e); sys.exit(1)

t = step(f"ATTACH {METADATA_DB_PATH} (read-only)")
try:
    con.execute(f"ATTACH '{METADATA_DB_PATH}' AS src (READ_ONLY)")
    ok(t)
except Exception as e:
    fail(t, e); sys.exit(1)

t = step("list tables in lake")
try:
    rows = con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = ? ORDER BY 1",
                       [LAKE_NAME]).fetchall()
    ok(t, f"{len(rows)} tables")
    for (x,) in rows:
        print(f"      {x}", flush=True)
except Exception as e:
    fail(t, e)

print("\nDiagnostic complete -- nothing was written.", flush=True)
