"""
Count rows in UUID-named CSV files and store results in dublin_core_metadata.

For each UUID in the table, locates the matching CSV in first_batch_downloads,
counts rows via `wc -l` (subprocess), and writes the result to the row_count
column. Missing files are stored as NULL. Uses multiprocessing for speed.

Usage:
  python count_rows.py                   # only process rows where row_count is missing ('<NA>'/NULL/blank)
  python count_rows.py --dry-run         # preview stats, no DB writes
  python count_rows.py --batch 1         # only process rows where batch=1
  python count_rows.py --workers 8       # override CPU count
  python count_rows.py --data-dir PATH   # override data directory
  python count_rows.py --recheck-low     # only recheck rows where row_count <= 5
"""

import argparse
import os
import subprocess
import time
import duckdb
import multiprocessing

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"
DEFAULT_DATA_DIR = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/data/first_batch_downloads"
BATCH_SIZE = 1000
WC_CHUNK = 100  # files per wc -l call
WC_TIMEOUT = 120  # seconds per wc -l call

# A file that exists but could not be counted (wc timed out or errored) is NOT the
# same as a file that isn't there. Writing NULL for the former silently destroys the
# distinction and makes a timeout look like a missing download, so those rows are
# left untouched in the DB and reported separately instead.
FAILED = "__FAILED__"


def count_rows_worker(args):
    """Count rows for a batch of UUIDs in a single wc -l call."""
    uuids, data_dir, timeout = args
    path_to_uuid = {}
    results = {}
    for uuid in uuids:
        path = os.path.join(data_dir, f"{uuid}.csv")
        if os.path.exists(path):
            path_to_uuid[path] = uuid
        else:
            results[uuid] = None  # genuinely absent -> NULL

    if not path_to_uuid:
        return results

    # Present files start as FAILED; a successful wc line below overwrites each one.
    for uuid in path_to_uuid.values():
        results[uuid] = FAILED

    try:
        result = subprocess.run(
            ["wc", "-l"] + list(path_to_uuid.keys()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[1] != "total":
                uuid = path_to_uuid.get(parts[1])
                if uuid:
                    results[uuid] = max(0, int(parts[0]) - 1)
    except Exception:
        pass

    return results


def main():
    parser = argparse.ArgumentParser(description="Count CSV rows and store in DB")
    parser.add_argument("--dry-run", action="store_true", help="Preview stats without writing to DB")
    parser.add_argument("--batch", type=int, default=None, help="Only process rows where batch=N")
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="Number of parallel workers")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Directory containing UUID CSV files")
    parser.add_argument("--recheck-low", action="store_true", help="Only recheck rows where row_count <= 5")
    parser.add_argument("--nid", help="Comma-separated list of nids to (re)process, ignoring row_count state")
    parser.add_argument("--merge-method", help="Only process rows with this merge_method")
    parser.add_argument("--wc-chunk", type=int, default=WC_CHUNK, help=f"Files per wc -l call (default {WC_CHUNK})")
    parser.add_argument("--wc-timeout", type=int, default=WC_TIMEOUT,
                        help=f"Seconds allowed per wc -l call (default {WC_TIMEOUT}). Raise it for very "
                             "large files — a timeout leaves those rows uncounted.")
    args = parser.parse_args()

    start = time.time()
    conn = duckdb.connect(DB_PATH)

    try:
        # Add column if not present
        conn.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN IF NOT EXISTS row_count BIGINT')

        # Fetch UUIDs
        query = f'SELECT "Identifier[UUID]" FROM "{TABLE}" WHERE "Identifier[UUID]" IS NOT NULL'
        if args.batch is not None:
            query += f" AND batch = {args.batch}"
        if args.merge_method:
            query += f" AND merge_method = '{args.merge_method}'"
        if args.nid:
            nids = ", ".join(f"'{n.strip()}'" for n in args.nid.split(","))
            query += f" AND nid IN ({nids})"
        elif args.recheck_low:
            query += " AND row_count IS NOT NULL AND row_count <= 5"
        else:
            # Only (re)process datasets whose row_count is still missing.
            # The column is VARCHAR and missing values are stored as the
            # literal '<NA>' (from an xlsx round-trip), NULL, or blank.
            query += " AND (row_count IS NULL OR trim(row_count) IN ('', '<NA>'))"
        uuids = [row[0] for row in conn.execute(query).fetchall()]

        print(f"UUIDs to process : {len(uuids):,}")
        print(f"Workers          : {args.workers}")
        print(f"Data dir         : {args.data_dir}")
        if args.dry_run:
            print("Mode             : DRY RUN (no DB writes)")
        print()

        # Split UUIDs into chunks so each worker handles --wc-chunk files per wc call
        chunks = [uuids[i : i + args.wc_chunk] for i in range(0, len(uuids), args.wc_chunk)]
        worker_args = [(chunk, args.data_dir, args.wc_timeout) for chunk in chunks]

        found = 0
        missing = 0
        failed = 0
        results = []
        processed = 0

        with multiprocessing.Pool(processes=args.workers) as pool:
            for batch_results in pool.imap_unordered(count_rows_worker, worker_args, chunksize=10):
                for uuid, count in batch_results.items():
                    if count == FAILED:
                        # File is present but uncountable — leave the DB value alone.
                        failed += 1
                        continue
                    results.append((count, uuid))
                    if count is None:
                        missing += 1
                    else:
                        found += 1
                processed += len(batch_results)
                if processed % 10000 == 0:
                    elapsed = time.time() - start
                    print(f"  {processed:,}/{len(uuids):,} processed — {elapsed:.1f}s elapsed")

        if not args.dry_run:
            # Batch UPDATE
            updated = 0
            for chunk_start in range(0, len(results), BATCH_SIZE):
                chunk = results[chunk_start : chunk_start + BATCH_SIZE]
                conn.executemany(
                    f'UPDATE "{TABLE}" SET row_count = ? WHERE "Identifier[UUID]" = ?',
                    chunk,
                )
                updated += len(chunk)

            print(f"\nDB updated       : {updated:,} rows")

        elapsed = time.time() - start
        print(f"\nFiles found      : {found:,}")
        print(f"Files missing    : {missing:,} (stored as NULL)")
        if failed:
            print(f"Files uncounted  : {failed:,} (present but wc timed out — DB left unchanged; "
                  f"retry with a larger --wc-timeout or a smaller --wc-chunk)")
        print(f"Elapsed          : {elapsed:.1f}s")

    finally:
        conn.close()


if __name__ == "__main__":
    main()






