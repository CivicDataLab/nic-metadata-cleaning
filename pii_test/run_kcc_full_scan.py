"""Scan every row of the KCC transcript corpus, not the first 250 of each file.

run_kcc_scan.py read --max-rows 250 rows per quarterly file: 318,459 of the
corpus's ~23 million. A farmer's PM-KISAN status pasted into an answer can sit
on any row, so that run could say which files had personal data in their
first rows and nothing about the rest. This is the same scan with the row
limit lifted. Two things had to change around it, and they are all this file
holds:

* **The 250-row results stay.** run_kcc_scan writes each folder's
  pii_detections.csv beside the data, which would overwrite the ones the
  September classification and the public-contact override were built on.
  ``stage`` links the non-empty files into a folder of their own and the scan
  reads that.
* **One state is too much to lose.** The scan holds a folder's results in
  memory and resumes per folder. A big state is hours of work and millions of
  rows, so the staged folders are one state-year each (``KERALA__2021``): four
  files, written and resumable every few minutes.
* **It is run by several workers at once.** See ``scan``.

The scan itself is run_kcc_scan's, which is run_pii_s3's. Each file's cell
texts are deduplicated before the models see them (batch_analyze_cells), which
is what makes 23 million rows affordable: KCC answers repeat heavily.

Nothing is written to metadata.db or S3, and no script-side PII file is edited.

    python pii_test/run_kcc_full_scan.py stage
    python pii_test/run_kcc_full_scan.py scan --gpu --worker w1     # and w2, w3 beside it
    python pii_test/run_kcc_full_scan.py merge
"""

import argparse
import glob
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII_TEST_DIR = os.path.join(REPO_ROOT, "pii_test")
sys.path.insert(0, PII_TEST_DIR)

SOURCE_ROOT = os.path.join(PII_TEST_DIR, "kcc", "kcc-transcripts")
STAGE_ROOT = os.path.join(REPO_ROOT, "data", "kcc_full_stage")
OUT_DIR = os.path.join(PII_TEST_DIR, "kcc", "full")
SUMMARY_PATH = os.path.join(OUT_DIR, "kcc_full_scan_summary.csv")
CLAIM_DIR = os.path.join(OUT_DIR, "claims")

ALL_ROWS = 10 ** 9
DETECTIONS_NAME = "pii_detections.csv"


def stage(_args):
    """Link every non-empty quarterly file into STAGE_ROOT/<STATE>__<YEAR>/."""
    linked, empty = Counter(), 0
    for state in sorted(os.listdir(SOURCE_ROOT)):
        state_dir = os.path.join(SOURCE_ROOT, state)
        if not os.path.isdir(state_dir):
            continue
        for name in sorted(os.listdir(state_dir)):
            path = os.path.join(state_dir, name)
            if name == DETECTIONS_NAME or not name.lower().endswith(".csv"):
                continue
            if os.path.getsize(path) == 0:
                empty += 1
                continue
            folder = f"{state}__{name[:4]}"            # 2021_Q3.csv -> KERALA__2021
            os.makedirs(os.path.join(STAGE_ROOT, folder), exist_ok=True)
            target = os.path.join(STAGE_ROOT, folder, name)
            if not os.path.lexists(target):
                os.symlink(path, target)
            linked[folder] += 1
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"staged {sum(linked.values())} file(s) in {len(linked)} folder(s) under {STAGE_ROOT}")
    print(f"left out: {empty} empty file(s)")


def scanned_folders():
    """Folders recorded in any worker's summary, or in the merged one."""
    import pandas as pd
    done = set()
    for path in glob.glob(os.path.join(OUT_DIR, "kcc_full_scan_summary*.csv")):
        try:
            done |= set(pd.read_csv(path, usecols=["label"])["label"].astype(str))
        except (ValueError, pd.errors.EmptyDataError):
            pass
    return done


def folder_bytes(folder):
    folder_dir = os.path.join(STAGE_ROOT, folder)
    return sum(os.path.getsize(os.path.join(folder_dir, name))
               for name in os.listdir(folder_dir) if name != DETECTIONS_NAME)


def scan(args):
    """One worker: take the next unscanned folder, scan every row, write, repeat.

    Several of these run side by side. The scan is CPU-bound (one core each,
    the GPU mostly idle), so the box's four cores are the limit, and its RAM:
    each worker holds its own models, ~2.5-3.3GB RSS. A folder is claimed with
    an atomic mkdir, so two workers never take the same one, and each worker
    appends to a summary and a log of its own -- ``merge`` puts the summaries
    together. A worker that dies leaves its claim behind: once no worker is
    running, clear CLAIM_DIR and start one again to pick up what is left.
    """
    import logging
    import time

    import run_kcc_scan as kcc
    import torch

    kcc.CORPUS_ROOT = STAGE_ROOT
    kcc.LOG_PATH = os.path.join(OUT_DIR, f"kcc_full_scan.{args.worker}.log")
    kcc.SUMMARY_PATH = os.path.join(OUT_DIR, f"kcc_full_scan_summary.{args.worker}.csv")
    kcc.configure_logging()
    R = kcc.R

    device = "cuda" if args.gpu and torch.cuda.is_available() else "cpu"
    R._max_rows = ALL_ROWS
    R._ner_batch_size = args.ner_batch_size
    started = time.time()
    R._analyzer, R._gpu_ner = R.build_analyzer(
        include_transformer_recognizer=True, device=device)
    logging.info(f"{args.worker}: models loaded on {device} in {time.time() - started:.1f}s")

    os.makedirs(CLAIM_DIR, exist_ok=True)
    folders = [d for d in os.listdir(STAGE_ROOT)
               if os.path.isdir(os.path.join(STAGE_ROOT, d))]
    if args.folders:
        wanted = {f.strip() for f in args.folders.split(",") if f.strip()}
        folders = [f for f in folders if f in wanted]
    # Largest first, so no worker is left alone with a big state at the end.
    folders.sort(key=folder_bytes, reverse=True)

    scanned = 0
    for folder in folders:
        if folder in scanned_folders():
            continue
        try:
            os.mkdir(os.path.join(CLAIM_DIR, folder))
        except FileExistsError:
            continue
        folder_dir = os.path.join(STAGE_ROOT, folder)
        paths = kcc.state_files(folder_dir)
        folder_started = time.time()
        results = kcc.scan_state(folder, paths)
        R.write_folder_detections(folder_dir, paths, results)
        kcc.append_summary(kcc.summary_rows(folder, paths, results))
        scanned += 1
        logging.info(
            f"{folder}: done in {(time.time() - folder_started) / 60:.1f} min | "
            f"files={len(results)} pii={sum(1 for r in results if r['pii_found'])} "
            f"errors={sum(1 for r in results if r['error'])}")
    logging.info(f"{args.worker}: finished, {scanned} folder(s) in "
                 f"{(time.time() - started) / 3600:.2f} h")


def merge(_args):
    """Put every worker's summary rows into kcc_full_scan_summary.csv."""
    import pandas as pd
    parts = [pd.read_csv(path, dtype=str, keep_default_na=False)
             for path in sorted(glob.glob(os.path.join(OUT_DIR, "kcc_full_scan_summary*.csv")))]
    merged = pd.concat(parts, ignore_index=True).drop_duplicates()
    twice = merged.file[merged.file.duplicated()].tolist()
    if twice:
        raise SystemExit(f"{len(twice)} file(s) scanned twice with different results: {twice[:5]}")
    merged.sort_values("file").to_csv(SUMMARY_PATH, index=False)
    staged = sum(1 for _d, _s, names in os.walk(STAGE_ROOT)
                 for name in names if name != DETECTIONS_NAME)
    print(f"{len(merged)} of {staged} staged file(s) in {merged.label.nunique()} folder(s) "
          f"-> {SUMMARY_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stage", help="link the non-empty files into state-year folders")
    p_scan = sub.add_parser("scan", help="one scan worker over the unscanned folders")
    p_scan.add_argument("--gpu", action="store_true")
    p_scan.add_argument("--worker", default="w1",
                        help="name for this worker's summary and log (default: %(default)s)")
    p_scan.add_argument("--folders", help="comma-separated staged folders; default all")
    p_scan.add_argument("--ner-batch-size", type=int, default=64,
                        help="GPU NER batch size; a worker holds 2.5-4GB of VRAM at 64 "
                             "(default: %(default)s)")
    sub.add_parser("merge", help="combine the workers' summaries into one")
    args = parser.parse_args()
    return {"stage": stage, "scan": scan, "merge": merge}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
