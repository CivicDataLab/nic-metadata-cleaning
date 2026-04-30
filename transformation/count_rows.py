"""
Count rows in UUID-named CSV files and store results in dublin_core_metadata.

For each UUID in the table, locates the matching CSV in first_batch_downloads,
counts rows via `wc -l` (subprocess), and writes the result to the row_count
column. Missing files are stored as NULL. Uses multiprocessing for speed.

Usage:
  python count_rows.py                   # process all rows
  python count_rows.py --dry-run         # preview stats, no DB writes
  python count_rows.py --batch 1         # only process rows where batch=1
  python count_rows.py --workers 8       # override CPU count
  python count_rows.py --data-dir PATH   # override data directory
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


def count_rows_worker(args):
    """Count rows for a batch of UUIDs in a single wc -l call."""
    uuids, data_dir = args
    path_to_uuid = {}
    for uuid in uuids:
        path = os.path.join(data_dir, f"{uuid}.csv")
        if os.path.exists(path):
            path_to_uuid[path] = uuid

    results = {uuid: None for uuid in uuids}  # default NULL for missing

    if not path_to_uuid:
        return results

    try:
        result = subprocess.run(
            ["wc", "-l"] + list(path_to_uuid.keys()),
            capture_output=True,
            text=True,
            timeout=120,
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
        uuids = [row[0] for row in conn.execute(query).fetchall()]

        print(f"UUIDs to process : {len(uuids):,}")
        print(f"Workers          : {args.workers}")
        print(f"Data dir         : {args.data_dir}")
        if args.dry_run:
            print("Mode             : DRY RUN (no DB writes)")
        print()

        # Split UUIDs into chunks so each worker handles WC_CHUNK files per wc call
        chunks = [uuids[i : i + WC_CHUNK] for i in range(0, len(uuids), WC_CHUNK)]
        worker_args = [(chunk, args.data_dir) for chunk in chunks]

        found = 0
        missing = 0
        results = []
        processed = 0

        with multiprocessing.Pool(processes=args.workers) as pool:
            for batch_results in pool.imap_unordered(count_rows_worker, worker_args, chunksize=10):
                for uuid, count in batch_results.items():
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
        print(f"Elapsed          : {elapsed:.1f}s")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
