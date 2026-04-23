"""
Pipeline orchestrator for NIC metadata cleaning.

Usage:
  python main.py --step <name> [--batch N] [--dry-run] [options]

Steps (in order):
  import             Load Excel into raw_metadata table
  transform          Transform raw_metadata -> dublin_core_metadata
  create-enhancement Create metadata_enhancement table
  dataset-merge      Detect and flag mergeable datasets
  batch-classify     Send metadata to OpenAI Batch API (long-running)
  update-dublin      Merge LLM results back into dublin_core_metadata
  status             Generate curation status report
  export-s3          Export all tables to S3 as Parquet

Composite steps:
  pre-classify       Steps 0-3 (everything before batch-classify)
  post-classify      Steps 5-7 (everything after batch-classify)
  all                Steps 0-3 + 5-7 (skips batch-classify)
"""

import argparse
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

TRANSFORM_DIR = os.path.dirname(os.path.abspath(__file__))

STEPS = {
    "import": {
        "script": "import_csv.py",
        "description": "Load Excel into raw_metadata table",
        "accepts_batch": False,
        "accepts_dry_run": False,
    },
    "transform": {
        "script": "metdata_transform_dublin.py",
        "description": "Transform raw_metadata -> dublin_core_metadata",
        "accepts_batch": True,
        "accepts_dry_run": False,
    },
    "create-enhancement": {
        "script": "utils/create_metadata_enhancement.py",
        "description": "Create metadata_enhancement table",
        "accepts_batch": True,
        "accepts_dry_run": False,
    },
    "dataset-merge": {
        "script": "dataset_merge.py",
        "description": "Detect and flag mergeable datasets",
        "accepts_batch": True,
        "accepts_dry_run": True,
    },
    "batch-classify": {
        "script": "llm_batch_classifier.py",
        "description": "Send metadata to OpenAI Batch API (long-running)",
        "accepts_batch": True,
        "accepts_dry_run": False,
    },
    "update-dublin": {
        "script": "utils/update_dublin_metadata.py",
        "description": "Merge LLM results back into dublin_core_metadata",
        "accepts_batch": True,
        "accepts_dry_run": True,
    },
    "status": {
        "script": "curation_status.py",
        "description": "Generate curation status report",
        "accepts_batch": False,
        "accepts_dry_run": False,
    },
    "export-s3": {
        "script": "update_metadata_s3.py",
        "description": "Export all tables to S3 as Parquet",
        "accepts_batch": False,
        "accepts_dry_run": False,
    },
}

STEP_ORDER = [
    "import",
    "transform",
    "create-enhancement",
    "dataset-merge",
    "batch-classify",
    "update-dublin",
    "status",
    "export-s3",
]

PRE_CLASSIFY = ["import", "transform", "create-enhancement", "dataset-merge"]
POST_CLASSIFY = ["update-dublin", "status", "export-s3"]


def run_step(step_name: str, batch: int | None = None,
             dry_run: bool = False, extra_args: list[str] | None = None) -> None:
    step = STEPS[step_name]
    script_path = os.path.join(TRANSFORM_DIR, step["script"])

    cmd = [sys.executable, script_path]

    if batch is not None and step["accepts_batch"]:
        cmd.extend(["--batch", str(batch)])

    if dry_run and step["accepts_dry_run"]:
        cmd.append("--dry-run")

    if extra_args:
        cmd.extend(extra_args)

    logging.info(f"[{step_name}] {step['description']}")
    logging.info(f"  Command: {' '.join(cmd)}")
    start = time.time()

    result = subprocess.run(cmd, cwd=TRANSFORM_DIR)

    elapsed = time.time() - start
    if result.returncode != 0:
        logging.error(f"[{step_name}] FAILED (exit code {result.returncode}) after {elapsed:.1f}s")
        sys.exit(result.returncode)

    logging.info(f"[{step_name}] Done in {elapsed:.1f}s")


def run_steps(steps: list[str], batch: int | None = None,
              dry_run: bool = False, skip_import: bool = False,
              extra_args: list[str] | None = None) -> None:
    for step_name in steps:
        if skip_import and step_name == "import":
            logging.info(f"[{step_name}] Skipped (--skip-import)")
            continue
        run_step(step_name, batch=batch, dry_run=dry_run, extra_args=extra_args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NIC metadata cleaning pipeline orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step", required=True,
        choices=list(STEPS.keys()) + ["pre-classify", "post-classify", "all"],
        help="Pipeline step to run",
    )
    parser.add_argument("--batch", type=int, default=None,
                        help="Process only this batch number")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without modifying the database")
    parser.add_argument("--skip-import", action="store_true",
                        help="Skip the import step in composite runs")
    parser.add_argument("--limit", type=int, default=None,
                        help="Row limit (forwarded to batch-classify)")
    parser.add_argument("--chunk-size", type=int, default=None,
                        help="Chunk size (forwarded to batch-classify)")
    parser.add_argument("--batch-id", type=str, default=None,
                        help="Resume polling an OpenAI batch by ID")

    args = parser.parse_args()

    # Build extra args for batch-classify
    extra_args = []
    if args.limit is not None:
        extra_args.extend(["--limit", str(args.limit)])
    if args.chunk_size is not None:
        extra_args.extend(["--chunk-size", str(args.chunk_size)])
    if args.batch_id is not None:
        extra_args.extend(["--poll", args.batch_id])

    step = args.step

    if step == "pre-classify":
        run_steps(PRE_CLASSIFY, batch=args.batch, dry_run=args.dry_run,
                  skip_import=args.skip_import)
    elif step == "post-classify":
        run_steps(POST_CLASSIFY, batch=args.batch, dry_run=args.dry_run)
    elif step == "all":
        run_steps(PRE_CLASSIFY, batch=args.batch, dry_run=args.dry_run,
                  skip_import=args.skip_import)
        logging.info("Skipping batch-classify (run manually: python main.py --step batch-classify)")
        run_steps(POST_CLASSIFY, batch=args.batch, dry_run=args.dry_run)
    else:
        run_step(step, batch=args.batch, dry_run=args.dry_run,
                 extra_args=extra_args if step == "batch-classify" else None)


if __name__ == "__main__":
    main()
