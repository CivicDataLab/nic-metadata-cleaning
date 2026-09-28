"""
Add spatial coverage columns to the AIKosh metadata CSV.

CSV-only sibling of Spatial_script.py: same detection logic, but nothing is
read from or written to metadata.db. The input CSV is rewritten in place (after
a .bak_<stamp> copy) with the six spatial columns appended.

Evidence per row, in this order:

  1. data/spatial_extract_cache.jsonl  - the 110k-record cache the DB pipeline
     already built, keyed by UUID. ~3k of the CSV's uuids are in it, for free.
  2. data/aikosh_downloads/{nid}.{ext} - the 644 files downloaded for AIKosh,
     scanned here into their own cache. These are keyed by NID (the filename
     stem is the nid, not a uuid), so they are kept in a SEPARATE dict and a
     SEPARATE cache file - mixing nid-keyed records into the uuid-keyed cache
     would corrupt the gazetteer of the next DB run.
  3. the Title, always - the closed State/UT list plus "<District> of <State>".

The gazetteer (district -> State, sub-district -> district) is always built
from the FULL shared cache, never from the AIKosh subset: its edges need
MIN_PAIR_COUNT support, which a 3k-file corpus cannot give.

Usage:
    python Spatial_script_aikosh.py --dry-run     # resolve + stats, no write
    python Spatial_script_aikosh.py --scan        # scan aikosh_downloads first
    python Spatial_script_aikosh.py               # resolve + write the CSV
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from Spatial_script import (                      # noqa: E402
    CACHE_PATH,
    SPATIAL_COLS,
    build_gazetteer,
    load_cache,
    process_file,
)

# =========================================================
# CONFIG
# =========================================================

ROOT = HERE.parent.parent          # repo root, derived from this file

INPUT_CSV = ROOT / (
    "ai-kosh metadata fields added - ai-kosh metadata fields added.csv"
)

DOWNLOADS_FOLDER = ROOT / "data/aikosh_downloads"

# nid-keyed, deliberately NOT the uuid-keyed CACHE_PATH of the DB pipeline
AIKOSH_CACHE = ROOT / "data/aikosh_spatial_extract_cache.jsonl"

NID_COL = "nid"
UUID_COL = "uuid"
TITLE_COL = "Title"

VALID_EXT = (".csv", ".xls", ".xlsx", ".xlsm", ".xlsb")
MAX_WORKERS = 6

# =========================================================
# PHASE 1: SCAN THE AIKOSH DOWNLOADS  (nid-keyed)
# =========================================================


def list_aikosh_files(nids):
    """{nid: path} for every wanted nid that has a file on disk."""
    found = {}

    with os.scandir(DOWNLOADS_FOLDER) as it:
        for entry in it:
            if not entry.name.lower().endswith(VALID_EXT):
                continue
            stem = entry.name.split(".", 1)[0]
            if stem in nids:
                found[stem] = entry.path

    return found


def run_scan(nids, workers, refresh):
    done = set() if refresh else set(load_cache(str(AIKOSH_CACHE)))
    paths = list_aikosh_files(nids)

    todo = [(n, p) for n, p in paths.items() if n not in done]

    print(
        f"aikosh files matching a CSV nid: {len(paths)}  "
        f"(cached {len(paths) - len(todo)}, to scan {len(todo)})"
    )

    if not todo:
        return

    started = time.time()
    ok = err = 0
    mode = "w" if refresh else "a"

    with open(AIKOSH_CACHE, mode, encoding="utf8") as out, \
            ProcessPoolExecutor(max_workers=workers) as pool:

        futures = {pool.submit(process_file, p): n for n, p in todo}

        for fut in as_completed(futures):
            nid = futures[fut]
            try:
                rec = fut.result()
            except Exception as exc:
                rec = {"error": f"worker: {exc}"[:200]}

            # process_file stamps the FILENAME STEM as "uuid"; for these files
            # that stem is the nid. Relabel it so nothing downstream can mistake
            # this record for a uuid-keyed one.
            rec["uuid"] = nid

            if rec.get("error"):
                err += 1
            else:
                ok += 1

            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"scan done: {ok} readable, {err} failed, "
        f"{(time.time() - started) / 60:.1f} min -> {AIKOSH_CACHE}"
    )

# =========================================================
# PHASE 2: RESOLVE + WRITE THE CSV
# =========================================================


def read_csv_rows(path):
    """(header, rows) with csv.reader - the file has a blank column name at
    index 5 that pandas would rename to 'Unnamed: 5' on round-trip."""
    with open(path, newline="", encoding="utf8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = [r for r in reader]
    return header, rows


def backup_csv(path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(str(path))
    dest = f"{base}.bak_{stamp}{ext}"
    shutil.copy2(path, dest)
    print(f"backed up: {dest}")
    return dest


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--scan", action="store_true",
                    help="scan data/aikosh_downloads before resolving")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and print stats; write nothing")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--refresh", action="store_true",
                    help="ignore + overwrite the aikosh scan cache")
    args = ap.parse_args()

    header, rows = read_csv_rows(INPUT_CSV)
    print(f"CSV rows: {len(rows)}")

    idx = {name: i for i, name in enumerate(header)}
    for col in (NID_COL, UUID_COL, TITLE_COL):
        if col not in idx:
            sys.exit(f"column {col!r} not in the CSV header: {header}")

    def cell(row, col):
        i = idx[col]
        return row[i].strip() if i < len(row) else ""

    nids = {cell(r, NID_COL) for r in rows}
    nids.discard("")

    if args.scan:
        run_scan(nids, args.workers, args.refresh)

    # ---- evidence ----
    shared = load_cache(CACHE_PATH)
    by_uuid = {u: r for u, r in shared.items() if not r.get("error")}
    print(f"shared cache: {len(shared)} records, {len(by_uuid)} readable")

    aikosh = load_cache(str(AIKOSH_CACHE))
    by_nid = {n: r for n, r in aikosh.items() if not r.get("error")}
    print(f"aikosh cache: {len(aikosh)} records, {len(by_nid)} readable")

    # gazetteer from the FULL shared corpus - its edges need MIN_PAIR_COUNT
    # support, which the aikosh subset alone could not provide.
    gaz = build_gazetteer(by_uuid)

    # resolve_one is imported late: it reads module-level gazetteer-free state
    # only, but keeping the import next to its use documents the dependency.
    from Spatial_script import resolve_one            # noqa: E402

    # ---- resolve, row by row (never join on nid: 8,706 distinct nids across
    # 9,324 rows, so a merge would multiply rows) ----
    resolved = []
    from_uuid = from_nid = no_content = 0

    for row in rows:
        uuid = cell(row, UUID_COL)
        nid = cell(row, NID_COL)
        title = cell(row, TITLE_COL)

        rec = by_uuid.get(uuid)
        if rec:
            from_uuid += 1
        else:
            rec = by_nid.get(nid)
            if rec:
                from_nid += 1
            else:
                no_content += 1

        resolved.append(resolve_one(uuid, title, rec, gaz))

    assert len(resolved) == len(rows)

    levels = Counter(r["spatial_level"] for r in resolved)
    sources = Counter(r["spatial_source"] for r in resolved)
    filled = sum(1 for r in resolved if r["spatial_coverage"])
    finer = sum(
        1 for r in resolved
        if r["spatial_coverage"] and r["spatial_coverage"] != "India"
    )

    print(
        f"\nevidence: {from_uuid} rows matched the shared cache by uuid, "
        f"{from_nid} matched an aikosh download by nid, "
        f"{no_content} title-only"
    )
    print(f"levels : {dict(levels)}")
    print(f"sources: {dict(sources)}")
    print(
        f"spatial_coverage filled: {filled}/{len(rows)}  "
        f"({finer} State-or-finer, {filled - finer} plain 'India')"
    )

    if args.dry_run:
        seen = Counter()
        print("\n-- sample: up to 5 rows per level --")
        for r, row in zip(resolved, rows):
            lvl = r["spatial_level"]
            if seen[lvl] >= 5:
                continue
            seen[lvl] += 1
            print(
                f"  {lvl:<12} | {str(r['spatial_coverage']):<42} | "
                f"{r['spatial_source']:<7} | {cell(row, TITLE_COL)[:56]}"
            )
        print("\nDRY RUN - nothing written")
        return

    backup_csv(INPUT_CSV)

    # already-present spatial columns are overwritten, not duplicated
    keep = [i for i, name in enumerate(header) if name not in SPATIAL_COLS]
    out_header = [header[i] for i in keep] + SPATIAL_COLS

    tmp = str(INPUT_CSV) + ".tmp"
    with open(tmp, "w", newline="", encoding="utf8") as fh:
        writer = csv.writer(fh)
        writer.writerow(out_header)
        for row, r in zip(rows, resolved):
            padded = row + [""] * (len(header) - len(row))
            writer.writerow(
                [padded[i] for i in keep]
                + [r[c] if r[c] is not None else "" for c in SPATIAL_COLS]
            )

    written = sum(1 for _ in open(tmp, newline="", encoding="utf8")) - 1
    os.replace(tmp, INPUT_CSV)

    print(f"\nDONE - {len(out_header)} columns, {len(rows)} rows -> {INPUT_CSV}")
    if written != len(rows):
        print(f"  note: {written} physical lines counted (embedded newlines)")


if __name__ == "__main__":
    main()
