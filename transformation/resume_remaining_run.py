"""
Resilient driver for `llm_batch_classifier.py --source remaining`.

This machine's network intermittently drops HTTPS connections mid-poll
(SSL: UNEXPECTED_EOF_WHILE_READING), killing the classifier process while
its in-flight OpenAI batches keep running server-side untouched. Restarting
naively from a freshly computed offset would resubmit those same nids while
the stranded batches are still (or already) completed, producing duplicate
rows — merge_and_save is append-only, no dedup on nid.

This wrapper, on each (re)start: parses the log for the last submitted
window's batch ids, recovers any that finished server-side via
resume_poll() (same as `--poll`), recomputes the offset from the actual
DB row count, then relaunches the classifier as a subprocess. Repeats until
the DB row count reaches TOTAL.
"""
import re
import subprocess
import sys
import time

import duckdb

import llm_batch_classifier as bc

TOTAL = 116111
LOG_PATH = "../full_run.log"


def current_offset() -> int:
    con = duckdb.connect(bc.DB_PATH, read_only=True)
    n = con.execute(f"SELECT COUNT(*) FROM {bc.RESULTS_TABLE}").fetchone()[0]
    con.close()
    return n


def recover_stranded_batches() -> None:
    """Find the most recent 'in flight' batch ids in the log and merge any
    that completed server-side but never got downloaded locally."""
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return

    for line in reversed(lines):
        m = re.search(r"in flight.*?: \[(.*?)\]", line)
        if not m:
            continue
        batch_ids = re.findall(r"'([^']+)'", m.group(1))
        for bid in batch_ids:
            try:
                batch = bc.client.batches.retrieve(bid)
            except Exception as e:
                print(f"  couldn't check {bid}: {e}")
                continue
            if batch.status == "completed":
                print(f"  recovering stranded completed batch {bid}")
                try:
                    bc.resume_poll(bid, source="remaining")
                except Exception as e:
                    print(f"  recovery of {bid} failed: {e}")
            else:
                print(f"  {bid} status={batch.status} — not done yet, leaving in flight")
        return  # only the most recent window matters


def main() -> None:
    while True:
        offset = current_offset()
        if offset >= TOTAL:
            print(f"Done: {offset}/{TOTAL} rows in {bc.RESULTS_TABLE}.")
            return

        print(f"Checking for stranded batches from a previous crash...")
        recover_stranded_batches()

        offset = current_offset()
        if offset >= TOTAL:
            print(f"Done: {offset}/{TOTAL} rows in {bc.RESULTS_TABLE}.")
            return

        print(f"Resuming classifier at offset {offset} ({TOTAL - offset} rows left)...")
        subprocess.run(
            [sys.executable, "llm_batch_classifier.py", "--source", "remaining",
             "--offset", str(offset)]
        )
        time.sleep(5)


if __name__ == "__main__":
    main()
