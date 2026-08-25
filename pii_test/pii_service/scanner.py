"""
The service's bridge into the LOT 2 scan pipeline.

Everything here exists so app.py can call the *same* code path as
``run_pii_s3.py --path``: same column selection, same NER models, same
filters, same flag. The service must give the same answer as the CLI on the
same file, so nothing about the scan is reimplemented -- the module globals
run_pii_s3 already uses (_analyzer, _gpu_ner, _max_rows, _ner_batch_size)
are set here exactly the way rescan_sample.py sets them.
"""

import logging
import os
import sys

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
PII_TEST_DIR = os.path.dirname(SERVICE_DIR)
REPO_ROOT = os.path.dirname(PII_TEST_DIR)
LOG_PATH = os.path.join(SERVICE_DIR, "pii_service.log")

# run_pii_s3 opens its LOT 1 log with a path relative to the repo root, and
# every other script in pii_test assumes it is run from there; pin the cwd
# so the service behaves the same no matter where it was launched from.
os.chdir(REPO_ROOT)
sys.path.insert(0, PII_TEST_DIR)

import run_pii_s3 as R  # noqa: E402  (repoints the root logger; undone below)


def configure_logging():
    """Take the root logger back from run_pii_s3.

    Importing run_pii_s3 calls its configure_logging(force=True), which sends
    *everything* -- including uvicorn's access log -- to pii_test/pii_s3.log
    with no console output. The service gets its own file plus stderr.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)


def load_models(device):
    """Build the analyzer + GPU NER once. Takes about a minute."""
    R._analyzer, R._gpu_ner = R.build_analyzer(
        include_transformer_recognizer=True, device=device
    )
    logging.info(f"Models loaded (device={device})")


def models_loaded():
    return R._analyzer is not None


def scan_one(path, max_rows, ner_batch_size=64):
    """Scan one local CSV. Caller must serialize calls (one GPU, one model).

    Returns run_pii_s3.scan_local_file's result dict; a failed read/scan
    comes back in its "error" key rather than as an exception.
    """
    R._max_rows = max_rows
    R._ner_batch_size = ner_batch_size
    return R.scan_local_file(path)
