"""One command for every PII test run: stage the files, scan them, classify them, report.

    python pii_test/pipeline/run.py RUN STEP [options]

RUN    lot2      the files of dublin_core_remaining (data/lot2_*)
       lot3      the files of dublin_core_lot3 (data/lot3_downloads, data/lot3_s3_downloads)
       kcc       the KCC call-centre transcripts, the first 250 rows of each file
       kccfull   the same transcripts, every row
       folder    any folder of tables (--path), such as the test corpus

STEP   stage     build the folder the scan reads
       scan      scan it; resumes a folder (shard, state) at a time
       repair    restage the files the scan could not parse        (lot2, lot3)
       classify  Tier 1 rules, then the Tier 3 judge on what they left undecided
       result    one row per catalogue row with its final class    (lot2, lot3)
       override  stopgap: KCC columns whose phone numbers are all public
                 contacts move from present to permissible         (kcc)
       merge     put the scan workers' summaries together          (kccfull)
       redact    write redacted copies of the columns classified present

    python pii_test/pipeline/run.py lot3 stage
    python pii_test/pipeline/run.py lot3 scan --gpu
    python pii_test/pipeline/run.py lot3 repair      # then scan again, if it moved any
    python pii_test/pipeline/run.py lot3 classify
    python pii_test/pipeline/run.py lot3 result
    python pii_test/pipeline/run.py kccfull scan --gpu --worker w1   # and w2, w3 beside it
    python pii_test/pipeline/run.py folder scan --path DATA_DIR --out-dir OUT
    python pii_test/pipeline/run.py folder classify --path DATA_DIR --out-dir OUT --no-llm

Everything a lot or KCC run writes goes under --out, in the same places
relative to it as in the repo, and --out defaults to pii_test/pipeline/out, so
a test run touches nothing real. Pass the repo root to write the real files.
What the pipeline never writes -- the downloads, metadata.db, the KCC
transcripts -- is always read from the repo. A folder run writes its
detections beside the data in --path (that is where classify looks for them)
and everything else to --out-dir.

Why each run is staged the way it is:

* lot2, lot3: **two folders, and formats the scan does not open.** The scan
  reads .csv/.xls/.xlsx. Thousands of files are JSON (the Karnataka crop
  surveys), hundreds of ".xls" files are CSV text, and some carry the wrong
  extension in other ways. A skipped file looks the same as a clean one, so
  ``stage`` builds one folder the scan can read in full: symlinks under the
  extension the content actually has, and for JSON the first HEADROWS records
  written out as CSV -- every row the scan would look at anyway. Shards of
  SHARD files, so the scan's results land and resume per shard.
* lot2: **the files arrived in waves** (a copy of the S3 folders, the retry
  of the undownloadable list, a long download from data.gov.in), so its
  ``stage`` only adds: a file already in the manifest keeps its shard, new
  files go to new shards, and the next ``scan`` reads just those. lot3's
  ``stage`` deals every shard out again; never re-run it on a scanned lot.
* lot2, lot3: **some CSVs are ragged.** A trailing comma or an unclosed quote
  makes pandas refuse the file. ``repair`` restages those with every row
  padded to one width, in a shard of their own, so the next ``scan`` reads them.
* lot2, lot3: **the files are named by UUID, so a file has no title.** The
  catalogue has one: ``classify`` hands Tier 1 and the judge the title,
  catalog title, description, publisher and sector of the table row.
* kccfull: **the 250-row results stay**, so its ``stage`` links the non-empty
  files into folders of their own (one state-year each, ``KERALA__2021``:
  four files, written and resumable every few minutes), and several
  ``scan --worker`` processes share them. A folder is claimed with an atomic
  mkdir, so two workers never take the same one. A worker that dies leaves its
  claim behind: once no worker is running, clear the claims folder and start
  one again to pick up what is left.

Memory: each scan process holds its own models, ~2.4-3.3GB RSS whether it
runs on GPU or CPU, and RSS grows ~20% over a long run. On this box (15GB, no
swap, the judge holding the GPU) three is the most that fits.

Nothing is written to metadata.db or S3.
"""

import argparse
import csv
import glob
import json
import logging
import multiprocessing as mp
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

import classify as tier1
import judge as tier3
from filters import phonedigits, phonekind

PIPELINE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(PIPELINE))
DB = os.path.join(REPO, "transformation", "metadata.db")
DATA = os.path.join(REPO, "data")

SHARD = 1200          # files per shard
HEADROWS = 250        # rows the scan reads per file; a JSON file is staged as this many records
JSONHEAD = 1 << 20    # bytes of a JSON file read first, for its head
REPAIRSHARD = "r00"
ALLROWS = 10 ** 9
MANIFEST = ["uuid", "source_file", "source_kind", "staged_as", "shard",
            "staged_file", "skip_reason"]

# Everything that differs between the runs. Paths are relative to --out.
RUNS = {
    "lot2": {
        "table": "dublin_core_remaining",
        "stage": "data/lot2_pii_stage",
        "dir": "pii_test/lot2",
        "log": "lot2_scan.log",
        "summary": "lot2_scan_summary.csv",
        "result": "lot2_pii_result.csv",
        "publisher": '"Publisher[ministry_department]"',
        "extra": ', "Format", archive',
        "add": True,                                  # stage only adds new files
        "shards": {"table": "s", "json": "s"}, "width": 3,
    },
    "lot3": {
        "table": "dublin_core_lot3",
        "stage": "data/lot3_pii_stage",
        "dir": "pii_test/lot3",
        "log": "lot3_scan.log",
        "summary": "lot3_scan_summary.csv",
        "result": "lot3_pii_result.csv",
        "publisher": 'coalesce("Publisher[state_department]", "Publisher[ministry_department]")',
        "extra": "",
        "add": False,                                 # stage deals every shard out again
        "shards": {"table": "t", "json": "j"}, "width": 2,
    },
    "kcc": {
        "stage": "pii_test/kcc/kcc-transcripts",
        "dir": "pii_test/kcc",
        "log": "kcc_scan.log",
        "summary": "kcc_scan_summary.csv",
    },
    "kccfull": {
        "stage": "data/kcc_full_stage",
        "dir": "pii_test/kcc/full",
        "log": "kcc_full_scan.log",
        "summary": "kcc_full_scan_summary.csv",
    },
    "folder": {"log": "scan.log", "summary": "scan_summary.csv"},
}
KCC = os.path.join(REPO, "pii_test", "kcc", "kcc-transcripts")


def where(run, args):
    """The run's settings with its paths made absolute."""
    cfg = dict(RUNS[run])
    if run == "folder":
        if not args.path or not args.outdir:
            sys.exit("a folder run needs --path DIR and --out-dir DIR")
        cfg["stage"], cfg["dir"] = os.path.abspath(args.path), os.path.abspath(args.outdir)
        cfg["classdir"] = cfg["dir"]
    else:
        out = os.path.abspath(args.out)
        cfg["stage"], cfg["dir"] = os.path.join(out, cfg["stage"]), os.path.join(out, cfg["dir"])
        cfg["classdir"] = os.path.join(cfg["dir"], "classification")
        cfg["manifest"] = os.path.join(cfg["dir"], "stage_manifest.csv")
    for name in ("log", "summary", "result"):
        if name in cfg:
            cfg[name] = os.path.join(cfg["dir"], cfg[name])
    return cfg


def catalog(table):
    """uuid -> the catalogue fields the tiers read, from the lot's table."""
    import duckdb
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute(f'''
        SELECT "Identifier[UUID]", nid, "Title", "Relation[Catalog Title]",
               "Description",
               coalesce("Publisher[state_department]", "Publisher[ministry_department]"),
               "Subject[sector]"
        FROM {table} ORDER BY nid''').fetchall()
    con.close()
    found = {}
    for uuid, nid, title, catalogtitle, description, publisher, sector in rows:
        # One identifier is on two rows; the first nid speaks for the file.
        found.setdefault(uuid, {
            "nid": nid, "title": title, "catalog_title": catalogtitle,
            "description": description, "ministry": publisher, "sector": sector})
    return found


def readcsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def downloads(path):
    """uuid -> (status, detail) from a dataset-download.py log; the last row wins."""
    rows = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    rows[row[0]] = (row[2], ",".join(row[3:]))
    return rows


def fileuuid(key):
    """The identifier behind a staged file key such as ``t03/<uuid>.csv``."""
    return os.path.splitext(os.path.basename(str(key)))[0]


# -- stage -------------------------------------------------------------------

def stage(run, cfg, args):
    """Build the folder the scan reads."""
    if run in ("kcc", "kccfull"):
        # Link every quarterly file; kccfull leaves out the empty ones and
        # groups the rest by state and year (2021_Q3.csv -> KERALA__2021).
        if run == "kcc" and os.path.realpath(cfg["stage"]) == os.path.realpath(KCC):
            print(f"{KCC} is scanned in place; nothing to stage")
            return
        linked, empty = Counter(), 0
        for state in sorted(os.listdir(KCC)):
            if not os.path.isdir(os.path.join(KCC, state)):
                continue
            for name in sorted(os.listdir(os.path.join(KCC, state))):
                path = os.path.join(KCC, state, name)
                if name == "pii_detections.csv" or not name.lower().endswith(".csv"):
                    continue
                if run == "kccfull" and os.path.getsize(path) == 0:
                    empty += 1
                    continue
                folder = f"{state}__{name[:4]}" if run == "kccfull" else state
                os.makedirs(os.path.join(cfg["stage"], folder), exist_ok=True)
                target = os.path.join(cfg["stage"], folder, name)
                if not os.path.lexists(target):
                    os.symlink(path, target)
                linked[folder] += 1
        os.makedirs(cfg["dir"], exist_ok=True)
        print(f"staged {sum(linked.values())} file(s) in {len(linked)} folder(s) under {cfg['stage']}")
        print(f"left out: {empty} empty file(s)")
        return

    table = cfg["table"]
    known = catalog(table)

    # Every file of the lot on disk: (uuid, path), sorted by uuid. A file in
    # the lot 2 download folder counts only once the download log calls it a
    # success: the download may still be running, and a file it is half-way
    # through writing is on disk too.
    if run == "lot2":
        copies = os.path.join(DATA, "lot2_s3_downloads")          # one folder per ministry
        folders = [os.path.join(copies, name) for name in sorted(os.listdir(copies))] \
            if os.path.isdir(copies) else []
        folders += [os.path.join(DATA, "lot2_retry_downloads"), os.path.join(DATA, "lot2_downloads")]
        finished = {uuid for uuid, (status, _) in
                    downloads(os.path.join(DATA, "lot2_download_log.csv")).items()
                    if status == "success"}
    else:
        folders = [os.path.join(DATA, "lot3_downloads"), os.path.join(DATA, "lot3_s3_downloads")]
        finished = None
    found = {}
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            uuid = name.split(".", 1)[0]
            if finished is not None and folder.endswith("lot2_downloads") and uuid not in finished:
                continue
            if uuid in found:
                raise SystemExit(f"{uuid} is in more than one source folder")
            if uuid not in known:
                raise SystemExit(f"{name} in {folder} is not a {table} identifier")
            found[uuid] = os.path.join(folder, name)

    manifest = readcsv(cfg["manifest"]) if cfg["add"] and os.path.exists(cfg["manifest"]) else []
    staged = {row["uuid"] for row in manifest}
    # A new shard per SHARD files, numbered on from the last one already used.
    counters = {prefix: 0 for prefix in cfg["shards"].values()}
    for row in manifest:
        prefix = row["shard"][:1]
        if prefix in counters and row["shard"][1:].isdigit():
            counters[prefix] = max(counters[prefix], (int(row["shard"][1:]) + 1) * SHARD)

    os.makedirs(cfg["dir"], exist_ok=True)
    added = []
    for uuid, path in sorted(found.items()):
        if uuid in staged:
            continue
        # What the file actually is, whatever its extension says.
        ext = os.path.splitext(path)[1].lower()
        if os.path.getsize(path) == 0:
            kind = "empty"
        else:
            with open(path, "rb") as handle:
                head = handle.read(4096)
            text = head.lstrip(b"\xef\xbb\xbf").lstrip()
            kind = ("xls" if head[:4] == b"\xd0\xcf\x11\xe0" else "zip" if head[:2] == b"PK"
                    else "json" if text[:1] in (b"[", b"{") else "markup" if text[:1] == b"<"
                    else "text")
        row = {"uuid": uuid, "source_file": os.path.relpath(path, REPO), "source_kind": kind,
               "staged_as": "", "shard": "", "staged_file": "", "skip_reason": ""}
        records, stagedext = None, None
        if kind == "json":
            records, why = jsonhead(path)
            if records is None:
                row["skip_reason"] = why
        elif kind == "text" and ext in (".csv", ".xls", ".xlsx", ".json"):
            stagedext = ".csv"
        elif kind == "xls" and ext in (".xls", ".xlsx"):
            stagedext = ".xls"
        elif kind == "zip" and ext in (".xls", ".xlsx"):
            stagedext = ".xlsx"
        else:
            row["skip_reason"] = f"not a table ({ext.lstrip('.') or 'no extension'}, {kind})"

        if not row["skip_reason"]:
            # lot3's JSON heads get shards of their own: thousands of files
            # with two schemas, worth being able to look at -- or rerun -- alone.
            prefix = cfg["shards"]["json" if records is not None else "table"]
            shard = f"{prefix}{counters[prefix] // SHARD:0{cfg['width']}d}"
            counters[prefix] += 1
            os.makedirs(os.path.join(cfg["stage"], shard), exist_ok=True)
            name = uuid + (".csv" if records is not None else stagedext)
            target = os.path.join(cfg["stage"], shard, name)
            if records is not None:
                columns = []
                for record in records:
                    columns += [key for key in record if key not in columns]
                with open(target, "w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(columns)
                    for record in records:
                        values = [record.get(key) for key in columns]
                        writer.writerow(["" if v is None else
                                         json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                                         else v for v in values])
                row["staged_as"] = f"first {len(records)} records as csv"
            else:
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(path, target)
                row["staged_as"] = "symlink"
            row["shard"], row["staged_file"] = shard, f"{shard}/{name}"
        added.append(row)

    with open(cfg["manifest"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST)
        writer.writeheader()
        writer.writerows(manifest + added)

    new = [r for r in added if r["staged_file"]]
    print(f"{table}: {len(known)} identifiers, {len(manifest) + len(added)} with a file "
          f"({len(manifest)} already in the manifest, {len(added)} new)")
    print(f"staged {len(new)} new file(s) in {len({r['shard'] for r in new})} shard(s) "
          f"under {cfg['stage']}")
    for how, count in Counter(
            ("csv head of JSON" if r["staged_as"].startswith("first") else
             os.path.splitext(r["source_file"])[1] + " -> " + os.path.splitext(r["staged_file"])[1])
            for r in new).most_common():
        print(f"  {count:>6}  {how}")
    print(f"not staged: {len(added) - len(new)}")
    for why, count in Counter(r["skip_reason"] for r in added if r["skip_reason"]).most_common():
        print(f"  {count:>6}  {why}")
    print(f"manifest: {cfg['manifest']}")


def jsonhead(path, limit=HEADROWS):
    """(first ``limit`` records, None), or (None, why the file holds no table).

    Nearly every file is one array of flat objects, read from the head of the
    file: the crop-survey files run to 108MB and only the head is used. A
    wrapped payload ({"status": ..., "data": [...]}) is rare and small enough
    to load whole.
    """
    with open(path, "rb") as handle:
        first = handle.read(64).lstrip(b"\xef\xbb\xbf").lstrip()[:1]
    if first == b"[":
        size, chunk = os.path.getsize(path), JSONHEAD
        while True:
            with open(path, "rb") as handle:
                text = handle.read(chunk).decode("utf-8", "replace").lstrip("﻿ \r\n\t")
            decoder, pos, records, short = json.JSONDecoder(), 1, [], False
            while len(records) < limit:
                while pos < len(text) and text[pos] in " \r\n\t,":
                    pos += 1
                if pos >= len(text):
                    short = True
                    break
                if text[pos] == "]":
                    break
                try:
                    record, pos = decoder.raw_decode(text, pos)
                except json.JSONDecodeError:
                    short = True
                    break
                records.append(record)
            if short and chunk < size:
                chunk *= 4
                continue
            break
    else:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, RecursionError) as exc:
            return None, f"unreadable JSON ({exc})"
        # {"metaData": [{"name": ...}], "rows": [...]}: the longest list is the data.
        lists = [v for v in payload.values()
                 if isinstance(v, list) and v and isinstance(v[0], dict)]
        if not lists:
            return None, f"JSON holds no table ({json.dumps(payload)[:60]})"
        records = max(lists, key=len)[:limit]

    if not records or not all(isinstance(r, dict) for r in records):
        return None, "JSON holds no table (not an array of objects)"
    return records, None


# -- scan --------------------------------------------------------------------

def scan(run, cfg, args):
    """Scan the staged folders, one at a time; a folder already in the summary is skipped.

    A folder's results land as it finishes -- its ``pii_detections.csv`` and
    its summary rows -- so a fault ten hours in loses one folder, and an
    interrupted run continues by being started again (--force rescans). The
    summary is the record of what ran, not ``pii_detections.csv``, which only
    exists for folders that had a detection. A folder run is one folder,
    scanned in full every time, its summary written fresh.
    """
    import scan as scanner     # torch, transformers and presidio: only this step needs them

    # kccfull's workers each keep a summary and a log of their own; the done
    # set is read from all of them, and from the merged summary.
    worker = f".{args.worker}" if run == "kccfull" else ""
    summary = cfg["summary"].replace(".csv", f"{worker}.csv")
    log = cfg["log"].replace(".log", f"{worker}.log")
    summaries = (lambda: glob.glob(cfg["summary"].replace(".csv", "*.csv"))) \
        if run == "kccfull" else (lambda: [summary] if os.path.exists(summary) else [])
    os.makedirs(cfg["dir"], exist_ok=True)
    scanner.logto(log)
    root = cfg["stage"]

    def tables(folder, recursive=False):
        walk = sorted(os.walk(folder)) if recursive else [(folder, None, os.listdir(folder))]
        found = []
        for dirpath, _, names in walk:
            for name in sorted(names):
                path = os.path.join(dirpath, name)
                if name in (scanner.DETECTIONS, os.path.basename(summary)) \
                        or name.endswith("_pii_detections.csv"):
                    continue
                if name.lower().endswith(scanner.TABULAR) and (recursive or os.path.isfile(path)):
                    found.append(path)
        return found

    if run == "folder":
        folders = {os.path.basename(root) or "scan": tables(root, recursive=True)[:args.maxfiles or None]}
        done = set()
        if os.path.exists(summary):
            os.remove(summary)
    else:
        names = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
        if args.folders:
            wanted = [f.strip() for f in args.folders.split(",") if f.strip()]
            missing = [f for f in wanted if f not in names]
            if missing:
                sys.exit(f"no such folder(s) under {root}: {', '.join(missing)}")
            names = wanted
        if run == "kccfull":
            # Largest first, so no worker is left alone with a big state at the end.
            names.sort(key=lambda d: sum(os.path.getsize(p) for p in tables(os.path.join(root, d))),
                       reverse=True)
        folders = {name: None for name in names}
        done = set()
        if not args.force:
            for path in summaries():
                try:
                    done |= {r["label"] for r in readcsv(path)}
                except (KeyError, csv.Error):
                    pass

    rows = ALLROWS if run == "kccfull" else args.maxrows
    started = time.time()
    pool = None
    if args.workers > 1:
        mp.set_start_method("spawn", force=True)
        pool = mp.Pool(processes=args.workers, initializer=scanner.start,
                       initargs=(args.gpu, rows, args.nerbatch, log))
    else:
        scanner.start(args.gpu, rows, args.nerbatch)
    logging.info(f"models loaded in {time.time() - started:.1f}s | workers={args.workers} "
                         f"| max_rows={rows} | {len(folders)} folder(s)")

    claims = os.path.join(cfg["dir"], "claims")
    total = flagged = errors = 0
    for label, paths in folders.items():
        if label in done:
            logging.info(f"{label}: already in {os.path.basename(cfg['summary'])}; skipping")
            continue
        if run == "kccfull":
            if label in {r["label"] for p in summaries() for r in readcsv(p)}:
                continue
            os.makedirs(claims, exist_ok=True)
            try:
                os.mkdir(os.path.join(claims, label))
            except FileExistsError:
                continue
        if paths is None:
            paths = tables(os.path.join(root, label))
        if not paths:
            logging.info(f"{label}: no data files")
            continue

        logging.info(f"{label}: scanning {len(paths)} file(s)")
        began = time.time()
        results = pool.map(scanner.scanfile, paths) if pool else []
        for i, path in enumerate(paths, 1):
            if pool is None:
                tic = time.time()
                results.append(scanner.scanfile(path))
            result = results[i - 1]
            tag = f"[{label} {i}/{len(paths)}] {os.path.basename(path)}"
            if result["error"]:
                logging.warning(f"{tag}: {result['error']}")
                continue
            logging.info(
                f"{tag} | rows={result['rows_scanned']} pii={result['pii_found']} "
                f"types={result['pii_types']} entities={result['entity_count']} "
                f"reason={result.get('pii_flag_reason')}"
                + (f" | {time.time() - tic:.1f}s" if pool is None else ""))

        scanner.writedetections(paths, results)
        new = not os.path.exists(summary)
        with open(summary, "a", newline="", encoding="utf-8") as handle:
            lines = scanner.summaryrows(root, paths, results)
            # "\n", as the pandas writer the old scan used; repair rewrites
            # the whole file with the csv module's "\r\n", as the old one did.
            writer = csv.DictWriter(handle, fieldnames=list(lines[0]), lineterminator="\n")
            if new:
                writer.writeheader()
            writer.writerows(lines)
        hits = sum(1 for r in results if r["pii_found"])
        fails = sum(1 for r in results if r["error"])
        total, flagged, errors = total + len(results), flagged + hits, errors + fails
        logging.info(f"{label}: done in {(time.time() - began) / 60:.1f} min | "
                             f"files={len(results)} pii={hits} errors={fails}")

    if pool is not None:
        pool.close()
        pool.join()
    logging.info("=" * 50)
    logging.info(f"scan complete in {(time.time() - started) / 3600:.2f} h | "
                         f"files={total} pii={flagged} errors={errors}")
    logging.info(f"summary: {summary}")


# -- repair ------------------------------------------------------------------

def repair(run, cfg, args):
    """Restage the files the scan could not parse and drop their error rows.

    The csv module reads what pandas' tokenizer rejects: a row with more
    fields than the header gets extra ``Unnamed: N`` columns, and an unclosed
    quote swallows the rest of the file into one cell. Columns can end up
    shifted on such rows, but all of the text is there for the scan.
    """
    with open(cfg["summary"], newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields, summary = reader.fieldnames, list(reader)
    manifest = readcsv(cfg["manifest"])
    bystaged = {r["staged_file"]: r for r in manifest if r["staged_file"]}

    folder = os.path.join(cfg["stage"], REPAIRSHARD)
    moved = set()
    for row in summary:
        if not row["error"] or row["label"] == REPAIRSHARD:
            continue
        staged = os.path.join(cfg["stage"], row["file"])
        # Header and first HEADROWS rows, every row padded to the widest.
        lines = []
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                with open(staged, newline="", encoding=encoding,
                          errors="strict" if encoding == "utf-8-sig" else "replace") as handle:
                    lines = []
                    for line in csv.reader(handle):
                        if any(cell.strip() for cell in line):
                            lines.append(line)
                        if len(lines) > HEADROWS:
                            break
                break
            except UnicodeDecodeError:
                continue
        if len(lines) < 2:
            print(f"left as an error (no rows to pad): {row['file']} -- {row['error'].strip()}")
            continue
        width = max(len(line) for line in lines)
        header = [name.strip() or f"Unnamed: {i}" for i, name in enumerate(lines[0])]
        header += [f"Unnamed: {i}" for i in range(len(header), width)]
        lines = [header] + [line + [""] * (width - len(line)) for line in lines[1:]]

        os.makedirs(folder, exist_ok=True)
        name = fileuuid(row["file"]) + ".csv"
        with open(os.path.join(folder, name), "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(lines)
        os.remove(staged)
        bystaged[row["file"]].update(
            shard=REPAIRSHARD, staged_file=f"{REPAIRSHARD}/{name}",
            staged_as=f"ragged rows padded, first {len(lines) - 1} rows as csv")
        moved.add(row["file"])

    if not moved:
        print("nothing to repair")
        return
    with open(cfg["manifest"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST)
        writer.writeheader()
        writer.writerows(manifest)
    # A shard is done once it is in the summary, so a half-written repair
    # shard must not be: drop its rows along with the errors it replaces.
    kept = [r for r in summary if r["file"] not in moved and r["label"] != REPAIRSHARD]
    with open(cfg["summary"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)
    print(f"restaged {len(moved)} file(s) in {folder}; run scan again to read them")


# -- classify ----------------------------------------------------------------

def finalclass(summary, datasets):
    """Scan-summary rows with the final per-file class appended.

    Summary ``file`` paths and dataset uuids are both relative to the scanned
    folder, so they line up. Returns (rows, number of files with detections
    but no verdict).
    """
    byfile = {d["uuid"]: d for d in datasets}
    rows = readcsv(summary)
    unmatched = 0
    for row in rows:
        verdict = byfile.get(row.get("file", "").replace(os.sep, "/"))
        if verdict:
            row["final_pii_class"] = verdict["pii_class"]
            row["class_columns"] = verdict["n_columns"]
            row["class_rule_ids"] = verdict["rule_ids"]
            continue
        if row.get("error"):
            row["final_pii_class"] = "scan_error"
        else:
            row["final_pii_class"] = "no_detections"
            if str(row.get("entity_count") or "0") not in ("0", ""):
                unmatched += 1
        row["class_columns"] = 0
        row["class_rule_ids"] = ""
    return rows, unmatched


def classify(run, cfg, args):
    """Tier 1, then Tier 3 on what it left undecided, then the per-file result.

    Writes to the run's classification folder (a folder run: --out-dir):

        tier1_column_class.csv   Tier 1 verdict per (file, column)
        tier1_report.txt         Tier 1 class / rule / context breakdown
        tier3_judged.jsonl       every Tier 3 verdict as it arrived; a rerun skips these
        tier3_verdicts.csv       the model's verdict and reasoning per undecided pair
        column_class.csv         final verdict per (file, column), after both tiers
        dataset_class.csv        final verdict per file: the loudest column decides
        file_summary.csv         the scan summary plus the final class (pii_result.csv
                                 is the same file, under the name ``result`` reads)

    Tier 3 needs the vLLM judge serving on --endpoint. The server is checked
    before any pair is sent, and if it is down the Tier 1 outputs are still
    written and this exits 2 -- rerun once the server is up, or pass --no-llm
    to finish on Tier 1 alone (undecided pairs then stay undecided).

    --per-folder (on for kcc) is for folders that each hold one dataset split
    into files, like KCC's per-state quarterly exports: Tier 3 judges each
    (folder, column, header row) once and gives every file in it that verdict.
    Tier 1 still runs per file. Do not use it where a folder mixes unrelated
    datasets.
    """
    root, outdir = cfg["stage"], cfg["classdir"]
    if os.path.commonpath([os.path.abspath(outdir), root]) == root:
        sys.exit(f"{outdir} is inside the scanned folder {root}; a rescan would read "
                 f"the outputs as data")
    os.makedirs(outdir, exist_ok=True)

    def out(name):
        return os.path.join(outdir, name)

    # -- Tier 1 --
    detections, metadata = tier1.load([root])
    print(f"Tier 1: {len(detections)} detections over {len(metadata)} files", file=sys.stderr)
    known = catalog(cfg["table"]) if "table" in cfg and not args.nocatalog else {}
    for key, meta in metadata.items():
        entry = known.get(fileuuid(key))
        if entry:
            meta.update(title=entry["title"], catalog_title=entry["catalog_title"],
                        description=entry["description"])
    rows = []
    if detections:
        rows = tier1.withcontext(tier1.classify(detections, metadata), metadata)
        report = tier1.summarise(rows)
        tier1.writecsv(out("tier1_column_class.csv"), rows)
        with open(out("tier1_report.txt"), "w", encoding="utf-8") as handle:
            handle.write(report + "\n")
        print(report)
    else:
        print("nothing to classify", file=sys.stderr)

    # -- Tier 3 --
    final = rows
    pairs = tier3.topairs(rows, args.limit) if rows else []
    for pair in pairs:
        entry = known.get(fileuuid(pair["uuid"]))
        if entry:
            pair.update(catalog_title=entry["catalog_title"], description=entry["description"],
                        ministry=entry["ministry"], sector=entry["sector"])
    if pairs and not args.nollm:
        parts = urllib.parse.urlsplit(args.endpoint)
        models = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))
        try:
            with urllib.request.urlopen(models, timeout=5) as response:
                served = [m.get("id") for m in json.load(response).get("data", [])]
            problem = (f"{models} serves {', '.join(served)}, not --model {args.model}"
                       if served and args.model not in served else None)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            problem = f"no LLM server at {models} ({exc})"
        if problem:
            print(f"\nTier 3 not run: {problem}.\nTier 1 results are in {outdir}. Start "
                  f"the judge and rerun, or pass --no-llm to finish with {len(pairs)} "
                  f"pair(s) undecided.", file=sys.stderr)
            return 2

        real = sum(1 for p in pairs if p["headers_source"] != "detected_columns")
        print(f"\nTier 3: {len(pairs)} undecided pair(s) ({real} with the file's header row)",
              file=sys.stderr)
        perfolder = args.perfolder or run == "kcc"
        if perfolder:
            pairs = tier3.group(pairs)
            print(f"judging them as {len(pairs)} (folder, column) group(s)", file=sys.stderr)
        client = tier3.Client(args.endpoint, args.model, args.maxtokens, penalty=args.penalty)

        def progress(i, total, result):
            mark = result["verdict"] or f"UNDECIDED ({result['error']})"
            what = (f"{result['group']} ({len(result['members'])} files)"
                    if "members" in result else result["uuid"])
            print(f"[{i}/{total}] {what[:40]:<40} {result['column'][:30]:<30} {mark}",
                  file=sys.stderr, flush=True)

        try:
            results = tier3.judge(pairs, client, progress=progress,
                                  keep=out("tier3_judged.jsonl"), workers=args.judgeworkers)
        except tier3.ServerGaveUp as exc:
            print(f"\nTier 3 aborted: {exc}\nTier 1 results are in {outdir}.", file=sys.stderr)
            return 1
        print()
        print(tier3.summarise(results))
        if perfolder:
            results = tier3.expand(results)
        tier3.writeverdicts(out("tier3_verdicts.csv"), results)
        final = tier3.apply(rows, tier3.torows(results))
    elif pairs:
        print(f"\n--no-llm: {len(pairs)} pair(s) left undecided", file=sys.stderr)
    elif rows:
        print("\nTier 1 left nothing undecided; Tier 3 not needed", file=sys.stderr)

    # -- Final outputs --
    datasets = tier1.rollup(final) if final else []
    if final:
        tier1.writecsv(out("column_class.csv"), final)
        tier1.writecsv(out("dataset_class.csv"), datasets)
    if os.path.exists(cfg["summary"]):
        summary, unmatched = finalclass(cfg["summary"], datasets)
        if summary:
            tier1.writecsv(out("file_summary.csv"), summary)
            tier1.writecsv(out("pii_result.csv"), summary)
        if unmatched:
            print(f"\nwarning: {unmatched} file(s) in {cfg['summary']} have detections but "
                  f"no verdict", file=sys.stderr)

    print("\nFinal class per file")
    for name, count in Counter(d["pii_class"] for d in datasets).most_common():
        print(f"  {name:<16} {count:>6}")
    print(f"outputs in {outdir}", file=sys.stderr)
    return 0


# -- result ------------------------------------------------------------------

def result(run, cfg, args):
    """One row per table row, with the final class or why there is none."""
    import duckdb
    lot2 = run == "lot2"
    con = duckdb.connect(DB, read_only=True)
    table = con.execute(f'''
        SELECT nid, "Identifier[UUID]", "Title", "Relation[Catalog Title]",
               {cfg["publisher"]}{cfg["extra"]}
        FROM {cfg["table"]} ORDER BY nid''').fetchall()
    con.close()

    manifest = {r["uuid"]: r for r in readcsv(cfg["manifest"])}
    pipeline = os.path.join(cfg["classdir"], "pii_result.csv")
    scanned = {r["file"]: r for r in readcsv(pipeline)} if os.path.exists(pipeline) else {}
    attempts = {}
    if lot2:
        # The retry log covers the undownloadable list; the download log everything else.
        attempts = downloads(os.path.join(DATA, "lot2_retry_download_log.csv"))
        attempts.update(downloads(os.path.join(DATA, "lot2_download_log.csv")))

    fields = (["nid", "uuid", "title", "catalog_title", "publisher"]
              + (["format", "archive"] if lot2 else [])
              + ["source_file", "pii_status", "final_pii_class", "class_columns",
                 "class_rule_ids", "rows_scanned", "entity_count", "pii_types", "note"])
    rows = []
    for nid, uuid, title, catalogtitle, publisher, *extra in table:
        row = dict.fromkeys(fields, "")
        row.update(nid=nid, uuid=uuid, title=title, catalog_title=catalogtitle,
                   publisher=publisher)
        if lot2:
            row.update(format=extra[0], archive="true" if extra[1] else "")
        staged = manifest.get(uuid)
        if staged is None:
            status, detail = attempts.get(uuid, ("", ""))
            if status in ("failed", "skipped"):
                row.update(pii_status="not_scanned_download_failed", note=detail)
            elif status == "success":
                row["pii_status"] = "not_scanned_pending"
            else:
                row["pii_status"] = "not_scanned_no_file"
        elif not staged["staged_file"]:
            row.update(source_file=staged["source_file"],
                       pii_status="not_scanned_not_a_table", note=staged["skip_reason"])
        elif staged["staged_file"] not in scanned:
            row.update(source_file=staged["source_file"], pii_status="not_scanned_pending")
        else:
            hit = scanned[staged["staged_file"]]
            row.update(
                source_file=staged["source_file"], pii_status=hit["final_pii_class"],
                final_pii_class=hit["final_pii_class"],
                class_columns=hit["class_columns"], class_rule_ids=hit["class_rule_ids"],
                rows_scanned=hit["rows_scanned"], entity_count=hit["entity_count"],
                pii_types=hit["pii_types"],
                note=hit["error"] or (staged["staged_as"] if staged["staged_as"] != "symlink" else ""))
        rows.append(row)

    tier1.writecsv(cfg["result"], rows, fields)
    print(f"{cfg['table']}: {len(rows)} rows")
    for status, count in Counter(r["pii_status"] for r in rows).most_common():
        print(f"  {status:<28} {count:>6}")
    print(f"result: {cfg['result']}")


# -- override ----------------------------------------------------------------

# A stopgap until a KCC rule in Tier 1 replaces it. KCC answers routinely quote
# who the farmer should call -- the block ADO, a KVK scientist, the district
# JDA's office, a helpline -- and Tier 1's R11-personal-channel reads any such
# number as a personal channel: on the KCC run it put 652 files in present on
# phone numbers alone.
OVERRIDERULE = "KCC-public-contact"
PUBLICWINDOW = 120    # characters before a number searched for officer cues
PRIVATEWINDOW = 70    # a record field sits right beside its value
AFTER = 40            # characters after a number, for both
RECURRING = 3         # files a number recurs in before it is a public line
STRONG = ("FARMER_REGISTRATION_ID", "AADHAAR_NUMBER")

PRIVATECUES = re.compile(
    r"\b[a-z]{2}\d{9}\b|registration\s*(no|number|id)|date\s*of\s*registration|"
    r"father|spouse|guardian|name\s*of\s*(the\s*)?farmer|farmer'?s?\s*name|"
    r"aadh?aa?r|account|ifsc|utr\b|credit\s*date|beneficiary|date\s*of\s*birth|\bdob\b|"
    r"bank\s*name|loan\s*(type|account|amount)|kcc\s*account|"
    r"पंजीकरण\s*(संख्या|नंबर|क्रमांक)|पिता|आधार|खाता|अकाउंट|ऋण|बैंक\s*का\s*नाम|लाभार्थी",
    re.I)

PUBLICCUES = re.compile(
    r"contact|contect|officer|\bado\b|\bao\b|\ba\.?o\b|\bada\b|\bdda\b|\bjda\b|\bdao\b|"
    r"\bbao\b|\bsdao\b|\bsao\b|\bheo\b|\bhdo\b|director|deputy|assistant|scientist|"
    r"specialist|professor|\bdr\b|\bdr\.|\bsh\.|\bshri\b|\bsmt\b|\bmrs?\b\.?|b\.?\s?sc|"
    r"kvk|krishi|vigyan|bhavan|bhawan|university|\bdept|department|office|\bo/o\b|"
    r"helpline|toll|market|\bfarm\b|seed|cent(re|er)|institute|station|horticultur|"
    r"extension|project|accountant|secretary|enterprises?|traders?|agency|agencies|"
    r"dealer|\bshop\b|society|nursery|\bbank\b|call\b|\bph\b|phone|mob(ile)?\b|"
    r"\brsk\b|raitha|\bnumbers?\b|suggest|"
    # Tamil, Telugu, Kannada, Bengali, Odia: officer / contact / phone / agriculture
    r"அதிகாரி|அணுகவும்|போன்|அலைபேசி|தொடர்பு|வேளாண்|நிலையம்|அலுவலர்|"
    r"సంప్రదించ|అధికారి|ఫోన్|ಸಂಪರ್ಕ|ಅಧಿಕಾರಿ|যোগাযোগ|আধিকারিক|ଯୋଗାଯୋଗ|"
    # Hindi / Marathi, Gujarati
    r"नर्सरी|कांटेक्ट|कॉन्टैक्ट|नंबर|संपर्क|सम्पर्क|अधिकारी|डॉ|डॉक्टर|वैज्ञानिक|विभाग|"
    r"केंद्र|केन्द्र|कृषि|एडीओ|कार्यालय|સંપર્ક|અધિકારી|ડૉ|કેન્દ્ર|ખેતીવાડી",
    re.I)


def around(cell, text, before):
    """The part of a cell around ``text``: ``before`` characters back, AFTER on."""
    i = cell.find(text)
    if i < 0:
        return cell
    return cell[max(0, i - before): i + len(text) + AFTER]


def override(run, cfg, args):
    """Move KCC columns from present to permissible when every phone number is public.

    A number is judged from the text around it in the source file (the
    detection CSVs keep the row index), in this order -- the first match
    decides:

      private   a farmer-record field right beside it: PM-Kisan / KCC-loan
                blocks ("UTR No:", "Mobile No" under "Father/Spouse/Guardian",
                a registration ID such as KL987654321, bank name, loan account)
      public    an STD-coded landline -- an office line
      public    the same number in RECURRING+ files -- a farmer's own number
                does not recur across quarters and states
      public    an officer / institution cue nearby: contact, ADO/AO/JDA, Dr.,
                KVK, scientist, department, dealer, helpline ... in English and
                the Indic scripts the corpus uses
      unknown   none of these

    A column moves only if it has at least one phone number, every one is
    public, it holds no farmer registration ID or Aadhaar, and no name or
    email in it sits beside a farmer-record cue. Unknown numbers keep the
    column present: this errs towards leaving a verdict loud.

    Rewrites column_class.csv, dataset_class.csv and file_summary.csv (the
    originals are kept once as *.before_override.csv) and writes
    public_contact_override.csv: every moved column with its numbers and why.
    tier1_column_class.csv and tier3_verdicts.csv stay as the tiers wrote them.
    Re-running classify drops the override.
    """
    import pandas as pd
    rundir, root = cfg["classdir"], cfg["stage"]
    columnpath = os.path.join(rundir, "column_class.csv")
    classes = pd.read_csv(columnpath, dtype=str, keep_default_na=False)
    present = classes[classes["pii_class"] == "present"]
    keys = set(zip(present["uuid"], present["column"]))

    # The detections of those columns, each with its source cell.
    frames = []
    for path in tier1.finddetections([root]):
        found = pd.read_csv(path, dtype={"entity_text": str})
        folder = os.path.relpath(os.path.dirname(path), root).replace(os.sep, "/")
        found["uuid"] = [f"{folder}/{f}" if folder != "." else f for f in found["file"]]
        frames.append(found[[(u, c) in keys for u, c in zip(found["uuid"], found["column"])]])
    det = pd.concat(frames, ignore_index=True)
    det["entity_text"] = det["entity_text"].fillna("")
    cells = {}
    for uuid, group in det.groupby("uuid"):
        source = pd.read_csv(os.path.join(root, uuid), dtype=str, on_bad_lines="skip",
                             nrows=int(group["row_index"].max()) + 1)
        for row, column in set(zip(group["row_index"], group["column"])):
            ok = row < len(source) and column in source.columns
            cells[(uuid, row, column)] = str(source.iloc[row][column]) if ok else ""
    det["cell"] = [cells[k] for k in zip(det["uuid"], det["row_index"], det["column"])]

    phones = det[det["entity_type"] == "PHONE_NUMBER"].copy()
    phones["digits"] = phones["entity_text"].map(phonedigits)
    phones["kind"] = phones["entity_text"].map(phonekind)
    phones = phones.join(phones.groupby("digits")["uuid"].nunique().rename("files"), on="digits")
    judged = []
    for cell, text, kind, files in zip(phones["cell"], phones["entity_text"],
                                       phones["kind"], phones["files"]):
        if PRIVATECUES.search(around(cell, text, PRIVATEWINDOW)):
            judged.append("private")
        elif kind == "landline":
            judged.append("public:landline")
        elif files >= RECURRING:
            judged.append("public:recurring")
        elif PUBLICCUES.search(around(cell, text, PUBLICWINDOW)):
            judged.append("public:cue")
        else:
            judged.append("unknown")
    phones["judged"] = judged

    others = det[det["entity_type"].isin(["PERSON", "EMAIL_ADDRESS"])]
    blocked = {(u, c) for u, c, cell, t in zip(others["uuid"], others["column"],
                                              others["cell"], others["entity_text"])
               if PRIVATECUES.search(around(cell, t, PRIVATEWINDOW))}

    moves = {}
    for (uuid, column), group in phones.groupby(["uuid", "column"]):
        row = present[(present["uuid"] == uuid) & (present["column"] == column)].iloc[0]
        if any(t in row["entity_types"] for t in STRONG):
            continue
        if (uuid, column) in blocked or not group["judged"].str.startswith("public").all():
            continue
        moves[(uuid, column)] = group

    print(f"present columns: {len(present)} | moving to permissible: {len(moves)}")
    print("phone numbers behind present columns:",
          phones.drop_duplicates(["uuid", "column", "digits"])["judged"].value_counts().to_dict())
    if args.dryrun:
        return 0

    for name in ("column_class.csv", "dataset_class.csv", "file_summary.csv"):
        path = os.path.join(rundir, name)
        backup = path.replace(".csv", ".before_override.csv")
        if os.path.exists(path) and not os.path.exists(backup):
            shutil.copy2(path, backup)

    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    audit = []
    for index, row in classes.iterrows():
        group = moves.get((row["uuid"], row["column"]))
        if group is None:
            continue
        numbers = group.drop_duplicates("digits")
        evidence = json.loads(row["evidence_json"] or "{}")
        evidence["override"] = {
            "previous_class": row["pii_class"], "previous_tier": row["tier"],
            "previous_rule_id": row["rule_id"],
            "numbers": {n: j for n, j in zip(numbers["entity_text"], numbers["judged"])},
        }
        classes.loc[index, ["pii_class", "tier", "rule_id", "rule_strength",
                            "reason", "evidence_json", "classified_at"]] = [
            "permissible", "override", OVERRIDERULE, "override",
            "every phone number is a public or officer contact (stopgap until a KCC rule)",
            json.dumps(evidence, ensure_ascii=False), now]
        audit.append({
            "uuid": row["uuid"], "column": row["column"],
            "previous_tier": row["tier"], "previous_rule_id": row["rule_id"],
            "n_numbers": len(numbers),
            "landline": int((numbers["judged"] == "public:landline").sum()),
            "recurring": int((numbers["judged"] == "public:recurring").sum()),
            "officer_cue": int((numbers["judged"] == "public:cue").sum()),
            "numbers": "; ".join(numbers["entity_text"]),
        })

    rows = classes.to_dict("records")
    datasets = tier1.rollup(rows)
    tier1.writecsv(columnpath, rows)
    tier1.writecsv(os.path.join(rundir, "dataset_class.csv"), datasets)
    tier1.writecsv(os.path.join(rundir, "public_contact_override.csv"), audit)
    if os.path.exists(cfg["summary"]):
        summary, _ = finalclass(cfg["summary"], datasets)
        tier1.writecsv(os.path.join(rundir, "file_summary.csv"), summary)
    print("final class per file:", pd.Series([d["pii_class"] for d in datasets]).value_counts().to_dict())
    return 0


# -- merge -------------------------------------------------------------------

def merge(run, cfg, args):
    """Put every worker's summary rows into one summary."""
    import pandas as pd
    parts = [pd.read_csv(path, dtype=str, keep_default_na=False)
             for path in sorted(glob.glob(cfg["summary"].replace(".csv", "*.csv")))]
    merged = pd.concat(parts, ignore_index=True).drop_duplicates()
    twice = merged.file[merged.file.duplicated()].tolist()
    if twice:
        raise SystemExit(f"{len(twice)} file(s) scanned twice with different results: {twice[:5]}")
    merged.sort_values("file").to_csv(cfg["summary"], index=False)
    staged = sum(1 for _d, _s, names in os.walk(cfg["stage"])
                 for name in names if name != "pii_detections.csv")
    print(f"{len(merged)} of {staged} staged file(s) in {merged.label.nunique()} folder(s) "
          f"-> {cfg['summary']}")


# -- redact ------------------------------------------------------------------

def redact(run, cfg, args):
    """Redacted copies of the columns classified --redact-classes (default present).

    Every row is redacted, not only the rows the scan sampled; columns the
    tiers cleared are left alone; nothing is uploaded and the originals are
    not touched. The copies go to --redact-dir (default: the classification
    folder's redacted/), under the same relative paths.
    """
    import redact as redactor  # presidio_anonymizer and the models: only this step needs them

    rows = readcsv(os.path.join(cfg["classdir"], "column_class.csv"))
    classes = tuple(c.strip() for c in args.redactclasses.split(",") if c.strip())
    undecided = sum(1 for r in rows if r["pii_class"] == "undecided")
    if undecided and "undecided" not in classes:
        print(f"not redacting {undecided} undecided column(s) -- add undecided to "
              f"--redact-classes to include them", file=sys.stderr)
    targets = redactor.targets(rows, classes, cfg["stage"])
    if not targets:
        print(f"nothing classified {'/'.join(classes)}; no file redacted", file=sys.stderr)
        return 0
    outdir = args.redactdir or os.path.join(cfg["classdir"], "redacted")
    if os.path.commonpath([os.path.abspath(outdir), cfg["stage"]]) == cfg["stage"]:
        sys.exit(f"{outdir} is inside the scanned folder {cfg['stage']}; a rescan would "
                 f"read the redacted copies as data")
    print(f"Redacting {sum(len(c) for _, _, c in targets)} column(s) in {len(targets)} file(s)",
          file=sys.stderr)
    redactor.redact(targets, outdir, gpu=args.gpu, workers=args.workers,
                    rows=args.redactrows or None,
                    clean=cfg["stage"] if args.copyclean else None)
    return 0


STEPS = {"stage": stage, "scan": scan, "repair": repair, "classify": classify,
         "result": result, "override": override, "merge": merge, "redact": redact}
ALLOWED = {
    "lot2": {"stage", "scan", "repair", "classify", "result", "redact"},
    "lot3": {"stage", "scan", "repair", "classify", "result", "redact"},
    "kcc": {"stage", "scan", "classify", "override", "redact"},
    "kccfull": {"stage", "scan", "merge"},
    "folder": {"scan", "classify", "redact"},
}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", choices=list(RUNS))
    parser.add_argument("step", choices=list(STEPS))
    parser.add_argument("--out", default=os.path.join(PIPELINE, "out"),
                        help="root the lot and KCC runs write under (default: %(default)s; "
                             "the repo root writes the real files)")
    parser.add_argument("--path", help="folder run: the folder of tables to scan")
    parser.add_argument("--out-dir", dest="outdir",
                        help="folder run: where the summary, log and classification go")
    scanning = parser.add_argument_group("scan")
    scanning.add_argument("--gpu", action="store_true",
                          help="run the NER models on the GPU (~7x faster per file); off by "
                               "default because the Tier 3 judge holds the card")
    scanning.add_argument("--workers", type=int, default=1,
                          help="scan (or redaction) processes, ~3.3GB RSS each; 3 is this "
                               "box's ceiling")
    scanning.add_argument("--max-rows", dest="maxrows", type=int, default=HEADROWS,
                          help="rows scanned per file (default: %(default)s; kccfull: all)")
    scanning.add_argument("--ner-batch-size", dest="nerbatch", type=int, default=64)
    scanning.add_argument("--folders", help="comma-separated shards or states; default all")
    scanning.add_argument("--force", action="store_true",
                          help="rescan folders already in the summary")
    scanning.add_argument("--worker", default="w1",
                          help="kccfull: this worker's name, for its summary and log")
    scanning.add_argument("--max-files", dest="maxfiles", type=int,
                          help="folder run: scan just the first N files, for a trial run")
    judging = parser.add_argument_group("classify")
    judging.add_argument("--no-llm", dest="nollm", action="store_true",
                         help="stop after Tier 1; undecided pairs stay undecided")
    judging.add_argument("--no-catalog", dest="nocatalog", action="store_true",
                         help="lots: classify without the table's titles, as a plain folder run would")
    judging.add_argument("--per-folder", dest="perfolder", action="store_true",
                         help="Tier 3 judges each (folder, column, header row) once (on for kcc)")
    judging.add_argument("--judge-workers", dest="judgeworkers", type=int, default=8,
                         help="pairs sent to the judge at once (default: %(default)s)")
    judging.add_argument("--limit", type=int, help="Tier 3 judges only the first N pairs (dry run)")
    judging.add_argument("--endpoint", default=tier3.ENDPOINT)
    judging.add_argument("--model", default=tier3.MODEL)
    judging.add_argument("--max-tokens", dest="maxtokens", type=int, default=tier3.MAXTOKENS)
    judging.add_argument("--presence-penalty", dest="penalty", type=float, default=0.0,
                         help="Qwen3 recommends 1.5 against repetition loops")
    judging.add_argument("--dry-run", dest="dryrun", action="store_true",
                         help="override: report, write nothing")
    redacting = parser.add_argument_group("redact")
    redacting.add_argument("--redact-dir", dest="redactdir")
    redacting.add_argument("--redact-classes", dest="redactclasses", default="present")
    redacting.add_argument("--redact-max-rows", dest="redactrows", type=int, default=0,
                           help="stop each file after N rows, for a quick look; 0 redacts all")
    redacting.add_argument("--redact-copy-clean", dest="copyclean", action="store_true",
                           help="also copy the files that needed no redaction")
    args = parser.parse_args()

    if args.step not in ALLOWED[args.run]:
        parser.error(f"{args.run} has no {args.step} step (it has: "
                     f"{', '.join(s for s in STEPS if s in ALLOWED[args.run])})")
    return STEPS[args.step](args.run, where(args.run, args), args)


if __name__ == "__main__":
    sys.exit(main())
