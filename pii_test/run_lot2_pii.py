"""Run the PII test over LOT 2 (dublin_core_remaining): stage, scan, classify, report.

This is run_lot3_pii.py pointed at LOT 2. The scan, the repair of ragged CSVs
and the classification are that driver's own functions, so a LOT 2 file gets
the answer a LOT 3 file would. Two things differ, and they are all this file
holds:

* **The files arrive in waves.** 34,983 are a copy of the S3 folders, 172 came
  from the retry of the undownloadable list, and the rest are being downloaded
  from data.gov.in over many hours (scripts/lot2_download_missing.sh). The
  LOT 3 ``stage`` deals shards out over every file present, so staging again
  after more files land would move files between shards and break the scan's
  per-shard resume. ``stage`` here only adds: a file already in the manifest
  keeps its shard, new files go to new shards, and the next ``scan`` reads
  just those.
* **A row without a file has a reason.** ``result`` says whether the download
  failed (and how) or was never attempted, from the two download logs.

The August 2026 scan of 29,818 LOT 2 CSVs stays where it is (pii_detections_lot2,
pii_column_class). This run rescans those files with the current scan code so
the whole lot has one result. Nothing is written to metadata.db or S3.

    python pii_test/run_lot2_pii.py stage
    python pii_test/run_lot2_pii.py scan --gpu
    python pii_test/run_lot2_pii.py repair      # then scan again, if it moved any
    python pii_test/run_lot2_pii.py classify
    python pii_test/run_lot2_pii.py result
"""

import argparse
import csv
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII_TEST_DIR = os.path.join(REPO_ROOT, "pii_test")
sys.path.insert(0, PII_TEST_DIR)

import run_lot3_pii as L3  # noqa: E402

TABLE = "dublin_core_remaining"
DATA_DIR = os.path.join(REPO_ROOT, "data")
S3_COPY_DIR = os.path.join(DATA_DIR, "lot2_s3_downloads")       # one folder per ministry
RETRY_DIR = os.path.join(DATA_DIR, "lot2_retry_downloads")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "lot2_downloads")
DOWNLOAD_LOG = os.path.join(DATA_DIR, "lot2_download_log.csv")
RETRY_LOG = os.path.join(DATA_DIR, "lot2_retry_download_log.csv")

OUT_DIR = os.path.join(PII_TEST_DIR, "lot2")
L3.TABLE = TABLE
L3.STAGE_ROOT = os.path.join(DATA_DIR, "lot2_pii_stage")
L3.OUT_DIR = OUT_DIR
L3.MANIFEST_PATH = os.path.join(OUT_DIR, "stage_manifest.csv")
L3.SCAN_LOG_PATH = os.path.join(OUT_DIR, "lot2_scan.log")
L3.SUMMARY_PATH = os.path.join(OUT_DIR, "lot2_scan_summary.csv")
L3.CLASS_DIR = os.path.join(OUT_DIR, "classification")
L3.PIPELINE_RESULT_PATH = os.path.join(L3.CLASS_DIR, "pii_result.csv")
L3.RESULT_PATH = os.path.join(OUT_DIR, "lot2_pii_result.csv")

SHARD_PREFIX = "s"


# -- stage -------------------------------------------------------------------

def download_log(path):
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


def source_files(uuids):
    """(uuid, path, origin) for every LOT 2 file on disk, sorted by uuid.

    A file in the download folder counts only once the log calls it a
    success: the download may still be running, and a file it is half-way
    through writing is on disk too.
    """
    finished = {uuid for uuid, (status, _) in download_log(DOWNLOAD_LOG).items()
                if status == "success"}
    folders = [(os.path.join(S3_COPY_DIR, name), "s3")
               for name in sorted(os.listdir(S3_COPY_DIR))] if os.path.isdir(S3_COPY_DIR) else []
    folders += [(RETRY_DIR, "retry download"), (DOWNLOAD_DIR, "download")]
    found = {}
    for folder, origin in folders:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            uuid = name.split(".", 1)[0]
            if origin == "download" and uuid not in finished:
                continue
            if uuid in found:
                raise SystemExit(f"{uuid} is in more than one source folder")
            if uuid not in uuids:
                raise SystemExit(f"{name} in {folder} is not a {TABLE} identifier")
            found[uuid] = (os.path.join(folder, name), origin)
    return sorted((uuid, path, origin) for uuid, (path, origin) in found.items())


def read_manifest():
    if not os.path.exists(L3.MANIFEST_PATH):
        return []
    with open(L3.MANIFEST_PATH, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def staged_extension(path):
    """(extension to stage the file under, what it is, why not) -- L3.stage's rules."""
    ext = os.path.splitext(path)[1].lower()
    kind = L3.sniff(path)
    if kind == "json":
        return "json-head", kind, None
    if kind == "text" and ext in (".csv", ".xls", ".xlsx", ".json"):
        return ".csv", kind, None
    if kind == "xls" and ext in (".xls", ".xlsx"):
        return ".xls", kind, None
    if kind == "zip" and ext in (".xls", ".xlsx"):
        return ".xlsx", kind, None
    return None, kind, f"not a table ({ext.lstrip('.') or 'no extension'}, {kind})"


def stage(_args):
    """Add the files not yet in the manifest to new shards under STAGE_ROOT."""
    catalog = L3.load_catalog()
    manifest = read_manifest()
    known = {row["uuid"] for row in manifest}
    used = [int(row["shard"][len(SHARD_PREFIX):]) for row in manifest
            if row["shard"].startswith(SHARD_PREFIX)]
    first_shard = max(used) + 1 if used else 0

    os.makedirs(OUT_DIR, exist_ok=True)
    added, placed = [], 0
    for uuid, path, _origin in source_files(set(catalog)):
        if uuid in known:
            continue
        staged_ext, kind, skip = staged_extension(path)
        row = {"uuid": uuid, "source_file": os.path.relpath(path, REPO_ROOT),
               "source_kind": kind, "staged_as": "", "shard": "",
               "staged_file": "", "skip_reason": skip or ""}
        records = None
        if staged_ext == "json-head":
            records, why = L3.json_head_records(path)
            if records is None:
                row["skip_reason"] = why
        if not row["skip_reason"]:
            shard = f"{SHARD_PREFIX}{first_shard + placed // L3.SHARD_SIZE:03d}"
            placed += 1
            shard_dir = os.path.join(L3.STAGE_ROOT, shard)
            os.makedirs(shard_dir, exist_ok=True)
            name = uuid + (".csv" if records is not None else staged_ext)
            target = os.path.join(shard_dir, name)
            if records is not None:
                L3.write_head_csv(target, records)
                row["staged_as"] = f"first {len(records)} records as csv"
            else:
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(path, target)
                row["staged_as"] = "symlink"
            row["shard"] = shard
            row["staged_file"] = f"{shard}/{name}"
        added.append(row)

    with open(L3.MANIFEST_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=L3.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest + added)

    staged = [r for r in added if r["staged_file"]]
    print(f"{TABLE}: {len(catalog)} identifiers, {len(manifest) + len(added)} with a file "
          f"({len(manifest)} already in the manifest, {len(added)} new)")
    print(f"staged {len(staged)} new file(s) in "
          f"{len({r['shard'] for r in staged})} shard(s) under {L3.STAGE_ROOT}")
    for how, count in Counter(
            ("csv head of JSON" if r["staged_as"].startswith("first") else
             os.path.splitext(r["source_file"])[1] + " -> " + os.path.splitext(r["staged_file"])[1])
            for r in staged).most_common():
        print(f"  {count:>6}  {how}")
    print(f"not staged: {len(added) - len(staged)}")
    for why, count in Counter(r["skip_reason"] for r in added if r["skip_reason"]).most_common():
        print(f"  {count:>6}  {why}")
    print(f"manifest: {L3.MANIFEST_PATH}")


# -- result ------------------------------------------------------------------

RESULT_FIELDS = ["nid", "uuid", "title", "catalog_title", "publisher", "format",
                 "archive", "source_file", "pii_status", "final_pii_class",
                 "class_columns", "class_rule_ids", "rows_scanned", "entity_count",
                 "pii_types", "note"]


def result(_args):
    """One row per dublin_core_remaining row, with the final class or why there is none."""
    import duckdb
    con = duckdb.connect(L3.DB_PATH, read_only=True)
    table = con.execute(f'''
        SELECT nid, "Identifier[UUID]", "Title", "Relation[Catalog Title]",
               "Publisher[ministry_department]", "Format", archive
        FROM {TABLE} ORDER BY nid''').fetchall()
    con.close()

    manifest = {row["uuid"]: row for row in read_manifest()}
    scanned = {}
    if os.path.exists(L3.PIPELINE_RESULT_PATH):
        with open(L3.PIPELINE_RESULT_PATH, newline="", encoding="utf-8") as handle:
            scanned = {row["file"]: row for row in csv.DictReader(handle)}
    # The retry log covers the undownloadable list; the download log everything else.
    attempts = download_log(RETRY_LOG)
    attempts.update(download_log(DOWNLOAD_LOG))

    rows = []
    for nid, uuid, title, catalog_title, publisher, file_format, archive in table:
        row = dict.fromkeys(RESULT_FIELDS, "")
        row.update(nid=nid, uuid=uuid, title=title, catalog_title=catalog_title,
                   publisher=publisher, format=file_format,
                   archive="true" if archive else "")
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
                note=hit["error"] or (staged["staged_as"]
                                      if staged["staged_as"] != "symlink" else ""))
        rows.append(row)

    with open(L3.RESULT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{TABLE}: {len(rows)} rows")
    for status, count in Counter(r["pii_status"] for r in rows).most_common():
        print(f"  {status:<28} {count:>6}")
    print(f"result: {L3.RESULT_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stage", help="add the files not yet staged to new shards")

    p_scan = sub.add_parser("scan", help="scan the staged shards; resumes")
    p_scan.add_argument("--gpu", action="store_true")
    p_scan.add_argument("--workers", type=int, default=1,
                        help="~3.3GB RSS each; see run_kcc_scan.py before raising this")
    p_scan.add_argument("--shards", help="comma-separated shard folders; default all")
    p_scan.add_argument("--force", action="store_true",
                        help="rescan shards already in the summary")

    p_class = sub.add_parser(
        "classify", help="Tier 1 + Tier 3 over the finished scan; unrecognised "
                         "options go to pii_classify_pipeline.py (--no-llm, --limit ...)")
    p_class.add_argument("--out-dir", help=f"default: {L3.CLASS_DIR}")
    p_class.add_argument("--judge-workers", type=int, default=8, metavar="N",
                         help="pairs sent to the judge at once (default: %(default)s)")
    p_class.add_argument("--no-catalog", action="store_true",
                         help=f"classify without the {TABLE} titles, as a plain folder "
                              "run would")

    sub.add_parser("repair", help="restage files the scan could not parse")
    sub.add_parser("result", help="join the final class back to the table rows")

    args, extra = parser.parse_known_args()
    if args.command == "classify":
        return L3.classify(args, extra)
    if extra:
        parser.error(f"unrecognised arguments: {' '.join(extra)}")
    return {"stage": stage, "scan": L3.scan, "repair": L3.repair,
            "result": result}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
