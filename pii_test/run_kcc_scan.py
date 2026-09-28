"""Run the LOT 2 PII scan over the KCC transcript corpus, one state at a time.

The corpus is ~1,900 non-empty quarterly CSVs across 37 state folders. On this
box the scan has to run on CPU -- the GPU is held by the Tier 3 judge -- which
costs about 25s per file, so a single pass is a ~13 hour job. Two things follow
from that, and they are the only reasons this wrapper exists rather than a bare
``run_pii_s3.py --path kcc/kcc-transcripts --no-gpu``:

* **Results land per state, not at the end.** The folder run in run_pii_s3
  holds every result in memory and writes once it has scanned everything; a
  fault at hour ten discards ten hours of work. Here each state's
  ``pii_detections.csv`` and its summary rows are written as that state
  finishes.
* **It resumes.** A state already present in the summary CSV is skipped, so
  an interrupted run continues by being started again. Pass --force to rescan
  regardless. The summary is the record of what ran -- *not* the per-state
  ``pii_detections.csv``, which write_folder_detections only creates for
  folders that actually had a detection. Keying resume off that file would
  rescan every clean state and append its rows to the summary twice.

The scan itself is not reimplemented: the models, column selection, filters and
flag all come from run_pii_s3, so a file scanned here gets the same answer as
``run_pii_s3.py --path <that file>``.

Each process needs ~3.3GB RSS whether it runs on GPU or CPU (the HF weights
move to VRAM, but spaCy, pandas and the interpreter do not), and RSS grows by
roughly 20% over a long run. RAM, not VRAM, is what limits --workers on this
box: one T4 holds ~1.1GB per worker and would fit many, while 15GB of RAM with
no swap fits two at a squeeze. Re-measure free memory before raising it; an
OOM kill loses the state in flight.

Usage:
    python pii_test/run_kcc_scan.py --gpu
    python pii_test/run_kcc_scan.py --gpu --workers 2
    python pii_test/run_kcc_scan.py --states KERALA,PUNJAB --force
"""

import argparse
import logging
import multiprocessing as mp
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII_TEST_DIR = os.path.join(REPO_ROOT, "pii_test")
os.chdir(REPO_ROOT)
sys.path.insert(0, PII_TEST_DIR)

import pandas as pd  # noqa: E402

import run_pii_s3 as R  # noqa: E402  (repoints the root logger; undone below)

CORPUS_ROOT = os.path.join(PII_TEST_DIR, "kcc", "kcc-transcripts")
LOG_PATH = os.path.join(PII_TEST_DIR, "kcc", "kcc_scan.log")
SUMMARY_PATH = os.path.join(PII_TEST_DIR, "kcc", "kcc_scan_summary.csv")


def configure_logging():
    """Take the root logger back from run_pii_s3.

    Importing it calls its configure_logging(force=True), which would append
    this run's ~1,900 file lines to pii_test/pii_s3.log -- already 65MB of LOT 1
    history that the frequency blocklist build reads. This run gets its own file.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)


def state_files(state_dir):
    """Every CSV in one state folder, excluding this script's own output.

    Empty files are kept rather than filtered: they cost a failed read each and
    they keep the summary's row count equal to the corpus file count, so
    "scanned everything" is checkable rather than asserted.
    """
    out = []
    for fname in sorted(os.listdir(state_dir)):
        if fname == R.FOLDER_DETECTIONS_FILENAME or fname.endswith("_pii_detections.csv"):
            continue
        path = os.path.join(state_dir, fname)
        if os.path.isfile(path) and fname.lower().endswith(R.TABULAR_EXTENSIONS):
            out.append(path)
    return out


def completed_states():
    """States already recorded in the summary CSV."""
    if not os.path.exists(SUMMARY_PATH):
        return set()
    try:
        return set(pd.read_csv(SUMMARY_PATH, usecols=["label"])["label"].astype(str))
    except (ValueError, pd.errors.EmptyDataError):
        return set()


def append_summary(rows):
    """Append this state's summary rows, writing the header only once."""
    df = pd.DataFrame(rows)
    header = not os.path.exists(SUMMARY_PATH)
    df.to_csv(SUMMARY_PATH, mode="a", header=header, index=False)


def summary_rows(state, paths, results):
    """Same columns as run_pii_s3.write_folder_summary, with state as the label."""
    rows = []
    for path, result in zip(paths, results):
        rows.append({
            "file": os.path.relpath(path, CORPUS_ROOT),
            "label": state,
            "rows_scanned": result["rows_scanned"],
            "pii_found": result["pii_found"],
            "pii_flag_reason": result.get("pii_flag_reason"),
            "entity_count": result["entity_count"],
            "pii_types": ",".join(result["pii_types"]),
            "columns_scanned": len(result.get("columns_scanned") or []),
            "columns_skipped": len(result.get("columns_skipped") or []),
            "degraded": result.get("degraded", False),
            "error": result["error"],
        })
    return rows


def scan_state(state, paths, pool=None):
    """Scan one state's files, logging each. With a pool the per-file timings
    would overlap and mean nothing, so only the state total is reported."""
    if pool is not None:
        results = pool.map(R.scan_local_file, paths)
        for path, result in zip(paths, results):
            if result["error"]:
                logging.warning(f"[{state}] {os.path.basename(path)}: {result['error']}")
            else:
                logging.info(
                    f"[{state}] {os.path.basename(path)} | "
                    f"rows={result['rows_scanned']} pii={result['pii_found']} "
                    f"types={result['pii_types']} entities={result['entity_count']} "
                    f"reason={result.get('pii_flag_reason')}"
                )
        return results

    results = []
    for i, path in enumerate(paths, 1):
        started = time.time()
        result = R.scan_local_file(path)
        results.append(result)
        if result["error"]:
            logging.warning(f"[{state} {i}/{len(paths)}] {os.path.basename(path)}: {result['error']}")
            continue
        logging.info(
            f"[{state} {i}/{len(paths)}] {os.path.basename(path)} | "
            f"rows={result['rows_scanned']} pii={result['pii_found']} "
            f"types={result['pii_types']} entities={result['entity_count']} "
            f"reason={result.get('pii_flag_reason')} | {time.time() - started:.1f}s"
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=CORPUS_ROOT)
    parser.add_argument("--max-rows", type=int, default=250,
                        help="Max rows read per CSV (run_pii_s3's default)")
    parser.add_argument("--ner-batch-size", type=int, default=64)
    parser.add_argument("--states", default=None,
                        help="Comma-separated state folders; default is all of them")
    parser.add_argument("--force", action="store_true",
                        help="Rescan states already present in the summary CSV")
    parser.add_argument("--gpu", action="store_true",
                        help="Run the NER models on the GPU (~7x faster per file)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Worker processes. Each loads its own models and needs "
                             "~3.3GB RSS; see the module docstring before raising this.")
    args = parser.parse_args()

    configure_logging()

    states = sorted(d for d in os.listdir(args.root)
                    if os.path.isdir(os.path.join(args.root, d)))
    if args.states:
        wanted = [s.strip() for s in args.states.split(",") if s.strip()]
        missing = [s for s in wanted if s not in states]
        if missing:
            parser.error(f"No such state folder(s) under {args.root}: {', '.join(missing)}")
        states = wanted

    import torch
    use_gpu = args.gpu and torch.cuda.is_available()
    if args.gpu and not use_gpu:
        logging.warning("--gpu requested but CUDA is unavailable; falling back to CPU")
    device = "cuda" if use_gpu else "cpu"

    R._max_rows = args.max_rows
    R._ner_batch_size = args.ner_batch_size
    started = time.time()

    pool = None
    if args.workers > 1:
        mp.set_start_method("spawn", force=True)
        pool = mp.Pool(
            processes=args.workers,
            initializer=R._init_worker,
            initargs=(use_gpu, args.max_rows, args.ner_batch_size, LOG_PATH),
        )
    else:
        R._analyzer, R._gpu_ner = R.build_analyzer(
            include_transformer_recognizer=True, device=device
        )
    logging.info(f"Models loaded on {device} in {time.time() - started:.1f}s | "
                 f"workers={args.workers} | max_rows={args.max_rows} | "
                 f"{len(states)} state(s)")

    done = set() if args.force else completed_states()
    total_files = total_pii = total_errors = 0
    for state in states:
        state_dir = os.path.join(args.root, state)
        if state in done:
            logging.info(f"{state}: already in {os.path.basename(SUMMARY_PATH)}; skipping")
            continue

        paths = state_files(state_dir)
        if not paths:
            logging.info(f"{state}: no data files")
            continue

        logging.info(f"{state}: scanning {len(paths)} file(s)")
        state_started = time.time()
        results = scan_state(state, paths, pool=pool)

        R.write_folder_detections(state_dir, paths, results)
        append_summary(summary_rows(state, paths, results))

        flagged = sum(1 for r in results if r["pii_found"])
        errors = sum(1 for r in results if r["error"])
        total_files += len(results)
        total_pii += flagged
        total_errors += errors
        logging.info(
            f"{state}: done in {(time.time() - state_started) / 60:.1f} min | "
            f"files={len(results)} pii={flagged} errors={errors}"
        )

    if pool is not None:
        pool.close()
        pool.join()

    logging.info("=" * 50)
    logging.info(f"KCC scan complete in {(time.time() - started) / 3600:.2f} h | "
                 f"files={total_files} pii={total_pii} errors={total_errors}")
    logging.info(f"Summary: {SUMMARY_PATH}")
    logging.info("=" * 50)


if __name__ == "__main__":
    main()
