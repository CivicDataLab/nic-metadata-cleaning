"""
Permanent record of every API run: one S3 folder per run.

    s3://<PII_RUNS_BUCKET>/<PII_RUNS_PREFIX>/<YYYY-MM-DD>/<run_id>/

holding the run directory as api_pipeline lays it out (input, request,
result, columns, detail/, run.log). The local copy is swept after a few
hours; this one is kept (no lifecycle rule on the prefix, by decision).

Credentials come from the instance role, as for every other script here.
The bucket encrypts at rest by default (SSE-S3).
"""

import logging
import mimetypes
import os
from datetime import datetime, timezone

import boto3
from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError

# upload_file wraps a failed PUT in boto3's S3UploadFailedError, which is not
# a botocore exception; catching only the botocore ones skips the retry.
UPLOAD_ERRORS = (Boto3Error, BotoCoreError, ClientError, OSError)

BUCKET = os.environ.get("PII_RUNS_BUCKET", "nic-ogdp-datasets")
PREFIX = os.environ.get("PII_RUNS_PREFIX", "pii-service-runs").strip("/")

README_KEY = f"{PREFIX}/README.txt"
README = """\
PII service runs -- written by pii_test/pii_service (the upload API).

One folder per run: <YYYY-MM-DD>/<run_id>/, run_id = <UTC time>_<random hex>.

  input/<file>.csv     the uploaded file, as received (contains PII)
  request.json         title / catalog title / description sent with it, options
  result.json          final class, one-line message, flagged columns
  columns.csv          the flagged columns as a table
  detail/              detections, Tier 1 rows, Tier 3 verdicts, final rows
  run.log              that run's log (no cell values)

Unrelated to pii-results/ and pii-results-lot2/, which hold the corpus scans.
"""

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def run_prefix(run_id, created):
    """Key prefix of one run's folder, with a trailing slash."""
    day = datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
    return f"{PREFIX}/{day}/{run_id}/"


def uri(prefix):
    return f"s3://{BUCKET}/{prefix}"


def upload_run(run_dir, prefix, retries=1):
    """Upload every file under run_dir to prefix. Returns the folder's URI.

    Re-uploads the whole folder on a retry -- a run is a few small files plus
    the input, and a half-uploaded folder is worse than a repeated PUT.
    """
    files = []
    for dirpath, _, names in os.walk(run_dir):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, run_dir).replace(os.sep, "/")
            files.append((path, prefix + rel))

    for attempt in range(retries + 1):
        try:
            for path, key in files:
                content_type = mimetypes.guess_type(path)[0] or "text/plain"
                client().upload_file(path, BUCKET, key,
                                     ExtraArgs={"ContentType": content_type})
            return uri(prefix)
        except UPLOAD_ERRORS as exc:
            if attempt == retries:
                raise
            logging.warning(f"S3 upload of {prefix} failed ({exc}); retrying")


def ensure_readme():
    """Put the README marker at the prefix root once, so the folder explains itself."""
    try:
        client().head_object(Bucket=BUCKET, Key=README_KEY)
        return False
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
            raise
    client().put_object(Bucket=BUCKET, Key=README_KEY, Body=README.encode("utf-8"),
                        ContentType="text/plain")
    logging.info(f"created {uri(README_KEY)}")
    return True


def problem():
    """Why runs cannot be stored right now, or None."""
    try:
        client().head_bucket(Bucket=BUCKET)
        return None
    except (BotoCoreError, ClientError) as exc:
        return f"s3://{BUCKET} unreachable ({exc})"
