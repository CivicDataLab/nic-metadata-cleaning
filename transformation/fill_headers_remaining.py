#!/usr/bin/env python3
"""
Fill "Conforms To" (comma-joined cleaned headers) + headers_cleaned on
dublin_core_remaining, resumably.

Fixes over the ad-hoc scripts that crashed on 2026-08-06:
  1. ONE os.scandir() pass builds {stem: path}; the previous version ran
     Path.glob(f"{uuid}.*") per UUID = a full directory scan 108k times.
  2. Unbuffered/flushed progress. Block-buffered stdout through `tee` made a
     working script look hung, and it got killed twice.
  3. Batched UPDATE ... FROM a temp table with bound parameters, instead of
     108k autocommit single-row UPDATEs with hand-escaped SQL. Faster, and
     the per-batch commit gives periodic checkpoints (the pattern that
     survived in count_rows.py per metadata-db-corruption-recovery.md).

Idempotent: only touches rows whose "Conforms To" is still NULL/blank, so it
can be re-run after any interruption and will pick up where it left off.

2026-08-14: three additions after the first pass left 7,749 rows unfilled.
  4. Scans every download directory, not just final_batch_downloads. A small
     tail of these datasets landed in sample_downloaded_files (uuid stems) and
     aikosh_downloads (nid stems, invisible to any uuid lookup).
  5. Writes header_count in the same UPDATE. Nothing in the repo maintained it
     for this table — add_header_count.py hardcodes dublin_core_metadata — so
     the counts went stale against headers filled later.
  6. Logs the UUIDs it could not read to a CSV. They were previously counted
     and dropped, leaving no way to tell "unreadable" from "never downloaded".
"""
import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import duckdb
import pandas as pd

REPO = "/media/aak/246AF1266AF0F580/nic-metadata-cleaning"
DB_PATH = f"{REPO}/transformation/metadata.db"
TABLE = "dublin_core_remaining"

# Searched in order; the first hit wins. `key` is the table column holding the
# filename stem — data/aikosh_downloads is the one nid-stemmed collection
# (scripts/aikosh_dataset_download.py), everything else is uuid.
DOWNLOAD_DIRS = [
    (f"{REPO}/data/final_batch_downloads", "uuid"),
    (f"{REPO}/data/sample_downloaded_files", "uuid"),
    (f"{REPO}/data/first_batch_downloads", "uuid"),
    (f"{REPO}/data/first_batch_datasets", "uuid"),
    (f"{REPO}/data/aikosh_downloads", "nid"),
]


def log(msg):
    print(msg, flush=True)


def get_headers_csv(path):
    """First CSV record; handles UTF-16, tab-delimited .csv, quoted multiline."""
    with open(path, "rb") as f:
        head = f.read(4)
    encodings = ["utf-8", "latin-1", "iso-8859-1", "cp1252"]
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        encodings = ["utf-16"] + encodings
    for encoding in encodings:
        try:
            with open(path, newline="", encoding=encoding) as f:
                sample = f.readline()
                delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
                f.seek(0)
                return next(csv.reader(f, delimiter=delimiter))
        except (UnicodeDecodeError, StopIteration, UnicodeError):
            continue
    raise ValueError(f"could not decode: {path}")


def get_headers_json(path):
    """Field names of the first record of a JSON dataset.

    Handles the two shapes these downloads come in: a bare top-level array of
    records, and a wrapper object whose payload is an array under some key
    ({"MMI Irrigation Projects": [...]}, {"code":"200","hospitalList":[...]}).
    """
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            doc = json.loads(raw.decode(encoding))
            break
        except (UnicodeDecodeError, UnicodeError, json.JSONDecodeError):
            continue
    else:
        raise ValueError(f"not parseable as JSON: {path}")

    def keys_of(records):
        for r in records:
            if isinstance(r, dict):
                return list(r.keys())
        return None

    if isinstance(doc, list):
        keys = keys_of(doc)
        if keys:
            return keys
    elif isinstance(doc, dict):
        for value in doc.values():
            if isinstance(value, list):
                keys = keys_of(value)
                if keys:
                    return keys
        # No nested record array — the object itself is the record
        return list(doc.keys())
    raise ValueError(f"no records found in JSON: {path}")


def looks_like_json(path):
    """Sniff content, not extension: some JSON payloads are named .csv."""
    try:
        with open(path, "rb") as f:
            head = f.read(4).lstrip(b"\xef\xbb\xbf").lstrip()
    except OSError:
        return False
    return head[:1] in (b"[", b"{")


def get_headers(path):
    with open(path, "rb") as f:
        if f.read(5) == b"%PDF-":
            # Read as CSV a PDF yields the header "%PDF1.4"; some are saved
            # as .html, so sniff content rather than trust the extension.
            raise ValueError(f"PDF has no header row: {path}")
    if path.endswith((".xls", ".xlsx")):
        try:
            return pd.read_excel(path, nrows=0).columns.tolist()
        except ValueError:
            # Some "xls" downloads are really plain CSV text
            return get_headers_csv(path)
    if looks_like_json(path):
        # Without this, csv.reader splits a single-line JSON document on its
        # commas and yields thousands of "headers" (one row reached 129,550).
        return get_headers_json(path)
    return get_headers_csv(path)


def scan_dirs():
    """-> ({uuid_stem: path}, {nid_stem: path})"""
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
                target[stem] = e.path
                n += 1
        log(f"  {os.path.basename(path)}: {n:,} files ({key} stems)")
    return by_uuid, by_nid


def extract(job):
    """-> (uuid, joined_headers, was_cleaned, count) or (uuid, None, reason, None)."""
    uuid, path = job
    try:
        headers = get_headers(path)
    except Exception as exc:
        return (uuid, None, f"{type(exc).__name__}: {exc}"[:200], None)
    cleaned, changed = [], False
    for h in headers:
        c = re.sub(r"[^a-zA-Z0-9_%. /]", "", str(h))
        cleaned.append(c)
        if c != str(h):
            changed = True
    # header_count counts non-blank fields, matching add_header_count.py
    count = sum(1 for c in cleaned if c.strip())
    if count == 0:
        # The file's first record is empty (or cleaning stripped every name).
        # Writing "" here would leave the row matching the NULL/blank pending
        # predicate, so every re-run would rewrite it forever. Report it as a
        # failure instead — it lands in the log and the row stays unfilled.
        return (uuid, None, "empty header row", None)
    return (uuid, ",".join(cleaned), changed, count)


def flush_batch(con, rows):
    """One bulk UPDATE ... FROM a bound temp table."""
    if not rows:
        return
    con.execute("CREATE OR REPLACE TEMP TABLE _hdr"
                "(uuid VARCHAR, hdrs VARCHAR, cleaned BOOLEAN, cnt INTEGER)")
    con.executemany("INSERT INTO _hdr VALUES (?, ?, ?, ?)", rows)
    con.execute(f'''
        UPDATE {TABLE} AS d
        SET "Conforms To" = t.hdrs,
            headers_cleaned = t.cleaned,
            header_count = t.cnt
        FROM _hdr AS t
        WHERE d."Identifier[UUID]" = t.uuid
    ''')
    con.execute("DROP TABLE _hdr")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8,
                    help="header-reader threads (disk-bound; keep modest)")
    ap.add_argument("--batch-size", type=int, default=5000,
                    help="rows per bulk UPDATE + commit")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N datasets (for a trial run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract headers but write nothing")
    ap.add_argument("--refill-uuids",
                    help="path to a file of UUIDs (one per line) to re-extract "
                         "even though they already have headers — for redoing "
                         "rows filled by an older, buggier extractor")
    args = ap.parse_args()

    log("scanning download directories ...")
    by_uuid, by_nid = scan_dirs()

    con = duckdb.connect(DB_PATH)
    if args.refill_uuids:
        with open(args.refill_uuids) as f:
            wanted = [line.strip() for line in f if line.strip()]
        con.execute("CREATE OR REPLACE TEMP TABLE _refill(uuid VARCHAR)")
        con.executemany("INSERT INTO _refill VALUES (?)", [(u,) for u in wanted])
        pending = con.execute(
            f'SELECT d."Identifier[UUID]", d.nid FROM {TABLE} AS d '
            f'JOIN _refill AS r ON d."Identifier[UUID]" = r.uuid'
        ).fetchall()
        log(f"\n  --refill-uuids: {len(wanted):,} requested, "
            f"{len(pending):,} matched in {TABLE}")
    else:
        pending = con.execute(
            f'SELECT "Identifier[UUID]", nid FROM {TABLE} '
            f'WHERE "Conforms To" IS NULL OR TRIM("Conforms To") = \'\''
        ).fetchall()
        log(f"\n  {len(pending):,} rows still need headers")

    jobs = []
    for uuid, nid in pending:
        path = by_uuid.get(uuid)
        if path is None and nid is not None:
            path = by_nid.get(str(nid).strip())
        if path is not None:
            jobs.append((uuid, path))
    log(f"  {len(jobs):,} of those have a file on disk "
        f"({len(pending) - len(jobs):,} never downloaded)")
    if args.limit:
        jobs = jobs[:args.limit]
        log(f"  --limit: trimmed to {len(jobs):,}")
    if not jobs:
        log("nothing to do")
        con.close()
        return

    done = 0
    batch, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (uuid, hdrs, cleaned, count) in enumerate(pool.map(extract, jobs), 1):
            if hdrs is None:
                failures.append((uuid, cleaned))  # cleaned carries the reason
            else:
                batch.append((uuid, hdrs, cleaned, count))
            if len(batch) >= args.batch_size:
                if not args.dry_run:
                    flush_batch(con, batch)
                done += len(batch)
                batch = []
                log(f"  {i:,}/{len(jobs):,} scanned | {done:,} written "
                    f"| {len(failures):,} unreadable")
    if batch:
        if not args.dry_run:
            flush_batch(con, batch)
        done += len(batch)

    if failures:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fail_path = f"{REPO}/transformation/header_extract_failures_{stamp}.csv"
        with open(fail_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Identifier[UUID]", "reason"])
            w.writerows(failures)
        log(f"unreadable UUIDs -> {fail_path}")

    log(f"\n{'DRY RUN - ' if args.dry_run else ''}written={done:,} "
        f"unreadable={len(failures):,}")
    con.close()
    log("closed cleanly (WAL checkpointed)")


if __name__ == "__main__":
    main()
