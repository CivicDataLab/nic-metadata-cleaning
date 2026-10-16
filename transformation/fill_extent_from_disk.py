#!/usr/bin/env python3
"""
Set "Extent" on dublin_core_remaining to the true on-disk byte count of the
downloaded file, replacing the API-reported value inherited from
`remaining-raw-datasets.file_size` (see metdata_transform_dublin.py:16, where
"Extent" is a plain rename of `file_size` — no script has ever stat()ed a file
to populate it).

Two deliberate choices:
  1. Rows with NO file on disk keep their existing API-reported "Extent".
     Overwriting them would NULL out ~7.7k rows that currently carry a usable
     number, which is data loss, not a fill.
  2. Only rows whose stored "Extent" actually disagrees with disk are written.
     Writing all ~110k matched rows would produce a byte-identical table for
     ~104k of them; the narrower UPDATE is the same result for less churn on a
     database file that has corrupted twice under bulk UPDATEs.

Old values are snapshotted to a CSV next to this script before anything is
written, per the metadata.db corruption history.

Idempotent: re-running after the first pass finds nothing left to change.
"""
import argparse
import csv
import os
from datetime import datetime

import duckdb

REPO = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning"
DB_PATH = f"{REPO}/transformation/metadata.db"
TABLE = "dublin_core_remaining"

# Searched in order; THE ORDER IS LOAD-BEARING — the first hit wins, and
# final_batch_downloads is the directory that partitions 1:1 with this table.
# `key` is the table column whose value is the filename stem — data/aikosh_downloads is the one nid-stemmed
# collection (scripts/aikosh_dataset_download.py), everything else is uuid.
DOWNLOAD_DIRS = [
    (f"{REPO}/data/final_batch_downloads", "uuid"),
    (f"{REPO}/data/sample_downloaded_files", "uuid"),
    (f"{REPO}/data/first_batch_downloads", "uuid"),
    (f"{REPO}/data/first_batch_datasets", "uuid"),
    (f"{REPO}/data/aikosh_downloads", "nid"),
]


def log(msg):
    print(msg, flush=True)


def scan_dirs():
    """-> ({uuid_stem: (size, dir)}, {nid_stem: (size, dir)})"""
    by_uuid, by_nid = {}, {}
    for path, key in DOWNLOAD_DIRS:
        if not os.path.isdir(path):
            log(f"  {os.path.basename(path)}: missing, skipped")
            continue
        target = by_uuid if key == "uuid" else by_nid
        n = 0
        with os.scandir(path) as it:
            for e in it:
                if not e.is_file():
                    continue
                stem = os.path.splitext(e.name)[0]
                if stem in target:  # earlier directory wins
                    continue
                try:
                    target[stem] = (e.stat().st_size, os.path.basename(path))
                except OSError:
                    continue
                n += 1
        log(f"  {os.path.basename(path)}: {n:,} files ({key} stems)")
    return by_uuid, by_nid


def flush_batch(con, rows, set_file_present):
    """One bulk UPDATE ... FROM a bound temp table (pattern from
    fill_headers_remaining.flush_batch)."""
    if not rows:
        return
    con.execute("CREATE OR REPLACE TEMP TABLE _ext(uuid VARCHAR, sz VARCHAR)")
    con.executemany("INSERT INTO _ext VALUES (?, ?)", rows)
    extra = ", file_present = TRUE" if set_file_present else ""
    con.execute(f'''
        UPDATE "{TABLE}" AS d
        SET "Extent" = t.sz{extra}
        FROM _ext AS t
        WHERE d."Identifier[UUID]" = t.uuid
    ''')
    con.execute("DROP TABLE _ext")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=5000,
                    help="rows per bulk UPDATE + commit")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the snapshot CSV but not the database")
    ap.add_argument("--fix-file-present", action="store_true",
                    help="also set file_present = TRUE on rows found on disk "
                         "(the flag is stale: TRUE on far fewer rows than "
                         "there are files)")
    args = ap.parse_args()

    log("scanning download directories ...")
    by_uuid, by_nid = scan_dirs()
    log(f"  {len(by_uuid):,} uuid-stemmed + {len(by_nid):,} nid-stemmed files total")

    con = duckdb.connect(DB_PATH)
    rows = con.execute(
        f'SELECT "Identifier[UUID]", nid, "Extent" FROM "{TABLE}"'
    ).fetchall()
    log(f"\n{len(rows):,} rows in {TABLE}")

    pending, snapshot = [], []
    same = no_file = 0
    for uuid, nid, extent in rows:
        hit = by_uuid.get(uuid)
        if hit is None and nid is not None:
            hit = by_nid.get(str(nid).strip())
        if hit is None:
            no_file += 1
            continue
        size, src = hit
        old = "" if extent is None else str(extent).strip()
        if old == str(size):
            same += 1
            continue
        pending.append((uuid, str(size)))
        snapshot.append((uuid, old, size, src))

    log(f"  {same:,} already equal to on-disk bytes")
    log(f"  {len(pending):,} to correct")
    log(f"  {no_file:,} with no file on disk (API-reported Extent kept as-is)")

    if not pending:
        log("nothing to do")
        con.close()
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_path = f"{REPO}/transformation/extent_from_disk_snapshot_{stamp}.csv"
    with open(snap_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Identifier[UUID]", "old_Extent", "new_Extent_bytes", "found_in"])
        w.writerows(snapshot)
    log(f"\nsnapshot of old values -> {snap_path}")

    written = 0
    for i in range(0, len(pending), args.batch_size):
        batch = pending[i:i + args.batch_size]
        if not args.dry_run:
            flush_batch(con, batch, args.fix_file_present)
        written += len(batch)
        log(f"  {written:,}/{len(pending):,} written")

    log(f"\n{'DRY RUN - ' if args.dry_run else ''}corrected={written:,} "
        f"unchanged={same:,} no_file={no_file:,}")
    con.close()
    log("closed cleanly (WAL checkpointed)")


if __name__ == "__main__":
    main()
