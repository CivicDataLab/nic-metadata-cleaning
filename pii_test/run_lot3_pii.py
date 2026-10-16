"""Run the PII test over LOT 3 (dublin_core_lot3): stage, scan, classify, report.

LOT 3's files are local -- data/lot3_downloads and data/lot3_s3_downloads,
named <Identifier[UUID]>.<ext> -- so the test is the folder pipeline
(pii_classify_pipeline.py), not the S3 batch flow LOT 1 and LOT 2 used. Four
things about the lot stop a bare ``pii_classify_pipeline.py --path`` from
being the whole answer, and they are the only reasons this wrapper exists:

* **Two folders, and formats the scan does not open.** The scan reads
  .csv/.xls/.xlsx. 4,777 files are JSON (the Karnataka crop surveys), 207
  ".xls" files are CSV text, and a few carry the wrong extension in other
  ways. A skipped file looks the same as a clean one, so ``stage`` builds one
  folder the scan can read in full: symlinks under the extension the content
  actually has, and for JSON the first HEAD_ROWS records written out as CSV.
  That is every row the scan would look at anyway -- it reads --max-rows rows
  per file -- so a head CSV gets the answer the JSON would.
* **The scan is long and holds its results in memory.** ``scan`` is
  run_kcc_scan.py pointed at the staged shards: results land per shard and a
  restart skips the shards already in the summary.
* **Some CSVs are ragged.** A trailing comma or an unclosed quote makes
  pandas refuse the file, which the scan records as an error and moves on.
  ``repair`` restages those with every row padded to one width, in a shard of
  their own, so the next ``scan`` reads them.
* **The files are named by UUID, so the folder run has no title.** The
  catalogue has one. ``classify`` hands Tier 1 and the Tier 3 judge the
  title, catalog title, description, publisher and sector from
  dublin_core_lot3 -- the fields load_from_db / load_undecided give them for
  LOT 1 and LOT 2 -- and otherwise runs pii_classify_pipeline.py --csv as is.
* **The result is wanted per table row.** ``result`` joins the final class
  back to dublin_core_lot3, with the rows that have no file, or a file that
  is not a table, listed as such rather than left out.

Nothing is written to metadata.db or S3, and no script-side PII file is edited.

    python pii_test/run_lot3_pii.py stage
    python pii_test/run_lot3_pii.py scan --gpu
    python pii_test/run_lot3_pii.py repair      # then scan again, if it moved any
    python pii_test/run_lot3_pii.py classify
    python pii_test/run_lot3_pii.py result
"""

import argparse
import csv
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PII_TEST_DIR = os.path.join(REPO_ROOT, "pii_test")
sys.path.insert(0, PII_TEST_DIR)

DB_PATH = os.path.join(REPO_ROOT, "transformation", "metadata.db")
TABLE = "dublin_core_lot3"
SOURCE_DIRS = [os.path.join(REPO_ROOT, "data", "lot3_downloads"),
               os.path.join(REPO_ROOT, "data", "lot3_s3_downloads")]

STAGE_ROOT = os.path.join(REPO_ROOT, "data", "lot3_pii_stage")
OUT_DIR = os.path.join(PII_TEST_DIR, "lot3")
MANIFEST_PATH = os.path.join(OUT_DIR, "stage_manifest.csv")
SCAN_LOG_PATH = os.path.join(OUT_DIR, "lot3_scan.log")
SUMMARY_PATH = os.path.join(OUT_DIR, "lot3_scan_summary.csv")
CLASS_DIR = os.path.join(OUT_DIR, "classification")
PIPELINE_RESULT_PATH = os.path.join(CLASS_DIR, "pii_result.csv")
RESULT_PATH = os.path.join(OUT_DIR, "lot3_pii_result.csv")

SHARD_SIZE = 1200
REPAIR_SHARD = "r00"
# run_pii_s3.read_row_limit(250): the rows the scan reads off disk per file.
HEAD_ROWS = 250
JSON_HEAD_BYTES = 1 << 20

MANIFEST_FIELDS = ["uuid", "source_file", "source_kind", "staged_as", "shard",
                   "staged_file", "skip_reason"]


# -- stage -------------------------------------------------------------------

def sniff(path):
    """What the file actually is, whatever its extension says."""
    if os.path.getsize(path) == 0:
        return "empty"
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "xls"
    if head[:2] == b"PK":
        return "zip"
    text = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if text[:1] in (b"[", b"{"):
        return "json"
    if text[:1] == b"<":
        return "markup"
    return "text"


def array_head(path, limit):
    """The first ``limit`` items of a top-level JSON array, read from the head
    of the file: the crop-survey files run to 108MB and only the head is used."""
    size = os.path.getsize(path)
    chunk = JSON_HEAD_BYTES
    while True:
        with open(path, "rb") as handle:
            text = handle.read(chunk).decode("utf-8", "replace").lstrip("\ufeff \r\n\t")
        decoder, pos, records, cut_short = json.JSONDecoder(), 1, [], False
        while len(records) < limit:
            while pos < len(text) and text[pos] in " \r\n\t,":
                pos += 1
            if pos >= len(text):
                cut_short = True
                break
            if text[pos] == "]":
                break
            try:
                record, pos = decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                cut_short = True
                break
            records.append(record)
        if cut_short and chunk < size:
            chunk *= 4
            continue
        return records


def json_head_records(path, limit=HEAD_ROWS):
    """(first ``limit`` records, None), or (None, why the file holds no table).

    Nearly every file is one array of flat objects. A wrapped payload
    ({"status": ..., "data": [...]}) is rare and small enough to load whole.
    """
    with open(path, "rb") as handle:
        first = handle.read(64).lstrip(b"\xef\xbb\xbf").lstrip()[:1]
    if first == b"[":
        records = array_head(path, limit)
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


def write_head_csv(path, records):
    columns = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for record in records:
            row = []
            for key in columns:
                value = record.get(key)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                row.append("" if value is None else value)
            writer.writerow(row)


def source_files(uuids):
    """(uuid, path) for every LOT 3 file, sorted by uuid."""
    found = {}
    for folder in SOURCE_DIRS:
        for name in os.listdir(folder):
            uuid = name.split(".", 1)[0]
            if uuid in found:
                raise SystemExit(f"{uuid} is in more than one source folder")
            if uuid not in uuids:
                raise SystemExit(f"{name} in {folder} is not a {TABLE} identifier")
            found[uuid] = os.path.join(folder, name)
    return sorted(found.items())


def stage(_args):
    """Build STAGE_ROOT: shards of ~SHARD_SIZE files the scan can read."""
    catalog = load_catalog()
    plan = []                                   # (uuid, path, kind, staged_ext, skip)
    for uuid, path in source_files(set(catalog)):
        ext = os.path.splitext(path)[1].lower()
        kind = sniff(path)
        staged_ext = skip = None
        if kind == "json":
            staged_ext = "json-head"
        elif kind == "text" and ext in (".csv", ".xls", ".xlsx", ".json"):
            staged_ext = ".csv"
        elif kind == "xls" and ext in (".xls", ".xlsx"):
            staged_ext = ".xls"
        elif kind == "zip" and ext in (".xls", ".xlsx"):
            staged_ext = ".xlsx"
        else:
            skip = f"not a table ({ext.lstrip('.') or 'no extension'}, {kind})"
        plan.append([uuid, path, kind, staged_ext, skip])

    os.makedirs(OUT_DIR, exist_ok=True)
    counters, rows = {"t": 0, "j": 0}, []
    for uuid, path, kind, staged_ext, skip in plan:
        row = {"uuid": uuid, "source_file": os.path.relpath(path, REPO_ROOT),
               "source_kind": kind, "staged_as": "", "shard": "",
               "staged_file": "", "skip_reason": skip or ""}
        records = None
        if staged_ext == "json-head":
            records, why = json_head_records(path)
            if records is None:
                row["skip_reason"] = why
        if not row["skip_reason"]:
            # JSON heads get their own shards: ~4,800 files with two schemas,
            # which is worth being able to look at -- or rerun -- on its own.
            prefix = "j" if records is not None else "t"
            shard = f"{prefix}{counters[prefix] // SHARD_SIZE:02d}"
            counters[prefix] += 1
            shard_dir = os.path.join(STAGE_ROOT, shard)
            os.makedirs(shard_dir, exist_ok=True)
            name = uuid + (".csv" if records is not None else staged_ext)
            target = os.path.join(shard_dir, name)
            if records is not None:
                write_head_csv(target, records)
                row["staged_as"] = f"first {len(records)} records as csv"
            else:
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(path, target)
                row["staged_as"] = "symlink"
            row["shard"] = shard
            row["staged_file"] = f"{shard}/{name}"
        rows.append(row)

    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    staged = [r for r in rows if r["staged_file"]]
    print(f"{TABLE}: {len(catalog)} identifiers, {len(rows)} with a file, "
          f"{len(catalog) - len(rows)} without")
    print(f"staged {len(staged)} file(s) in "
          f"{len({r['shard'] for r in staged})} shard(s) under {STAGE_ROOT}")
    for how, count in Counter(
            ("csv head of JSON" if r["staged_as"].startswith("first") else
             os.path.splitext(r["source_file"])[1] + " -> " + os.path.splitext(r["staged_file"])[1])
            for r in staged).most_common():
        print(f"  {count:>6}  {how}")
    print(f"not staged: {len(rows) - len(staged)}")
    for why, count in Counter(r["skip_reason"] for r in rows if r["skip_reason"]).most_common():
        print(f"  {count:>6}  {why}")
    print(f"manifest: {MANIFEST_PATH}")


# -- scan --------------------------------------------------------------------

def scan(args):
    """run_kcc_scan.py over the staged shards: one shard is one of its states."""
    import run_kcc_scan as kcc

    kcc.CORPUS_ROOT = STAGE_ROOT
    kcc.LOG_PATH = SCAN_LOG_PATH
    kcc.SUMMARY_PATH = SUMMARY_PATH
    sys.argv = ["run_lot3_pii.py scan", "--root", STAGE_ROOT,
                "--workers", str(args.workers), "--max-rows", str(HEAD_ROWS)]
    if args.gpu:
        sys.argv.append("--gpu")
    if args.shards:
        sys.argv += ["--states", args.shards]
    if args.force:
        sys.argv.append("--force")
    kcc.main()


# -- repair ------------------------------------------------------------------

def padded_head(path, limit=HEAD_ROWS):
    """Header and first ``limit`` rows, every row padded to the widest.

    The csv module reads what pandas' tokenizer rejects: a row with more
    fields than the header gets extra ``Unnamed: N`` columns, and an unclosed
    quote swallows the rest of the file into one cell. Columns can end up
    shifted on such rows, but all of the text is there for the scan.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with open(path, newline="", encoding=encoding,
                      errors="strict" if encoding == "utf-8-sig" else "replace") as handle:
                rows = []
                for row in csv.reader(handle):
                    if any(cell.strip() for cell in row):
                        rows.append(row)
                    if len(rows) > limit:
                        break
            break
        except UnicodeDecodeError:
            continue
    if len(rows) < 2:
        return None
    width = max(len(row) for row in rows)
    header = [name.strip() or f"Unnamed: {i}" for i, name in enumerate(rows[0])]
    header += [f"Unnamed: {i}" for i in range(len(header), width)]
    return [header] + [row + [""] * (width - len(row)) for row in rows[1:]]


def repair(_args):
    """Restage the files the scan could not parse and drop their error rows."""
    with open(SUMMARY_PATH, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        summary_fields, summary = reader.fieldnames, list(reader)
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as handle:
        manifest = list(csv.DictReader(handle))
    by_staged = {r["staged_file"]: r for r in manifest if r["staged_file"]}

    shard_dir = os.path.join(STAGE_ROOT, REPAIR_SHARD)
    moved = set()
    for row in summary:
        if not row["error"] or row["label"] == REPAIR_SHARD:
            continue
        staged = os.path.join(STAGE_ROOT, row["file"])
        rows = padded_head(staged)
        if rows is None:
            print(f"left as an error (no rows to pad): {row['file']} -- {row['error'].strip()}")
            continue
        os.makedirs(shard_dir, exist_ok=True)
        name = file_uuid(row["file"]) + ".csv"
        with open(os.path.join(shard_dir, name), "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
        os.remove(staged)
        entry = by_staged[row["file"]]
        entry.update(shard=REPAIR_SHARD, staged_file=f"{REPAIR_SHARD}/{name}",
                     staged_as=f"ragged rows padded, first {len(rows) - 1} rows as csv")
        moved.add(row["file"])

    if not moved:
        print("nothing to repair")
        return
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)
    # A shard is done once it is in the summary, so a half-written repair
    # shard must not be: drop its rows along with the errors it replaces.
    kept = [r for r in summary if r["file"] not in moved and r["label"] != REPAIR_SHARD]
    with open(SUMMARY_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(kept)
    print(f"restaged {len(moved)} file(s) in {shard_dir}; run scan again to read them")


# -- classify ----------------------------------------------------------------

def load_catalog():
    """uuid -> the catalogue fields the tiers read, from dublin_core_lot3."""
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = con.execute(f'''
        SELECT "Identifier[UUID]", nid, "Title", "Relation[Catalog Title]",
               "Description",
               coalesce("Publisher[state_department]", "Publisher[ministry_department]"),
               "Subject[sector]"
        FROM {TABLE} ORDER BY nid''').fetchall()
    con.close()
    catalog = {}
    for uuid, nid, title, catalog_title, description, publisher, sector in rows:
        # One identifier is on two rows; the first nid speaks for the file.
        catalog.setdefault(uuid, {
            "nid": nid, "title": title, "catalog_title": catalog_title,
            "description": description, "ministry": publisher, "sector": sector})
    return catalog


def file_uuid(key):
    """The identifier behind a staged file key such as ``t03/<uuid>.csv``."""
    return os.path.splitext(os.path.basename(str(key)))[0]


def classify(args, extra):
    import pii_classify as tier1
    import pii_classify_pipeline as pipeline
    import pii_tier3 as tier3

    catalog = load_catalog()
    load_csv, pairs_from_class_rows = tier1.load_csv, tier3.pairs_from_class_rows

    def load_csv_with_catalog(paths):
        detections, metadata = load_csv(paths)
        for key, meta in metadata.items():
            entry = catalog.get(file_uuid(key))
            if entry and not args.no_catalog:
                meta.update(title=entry["title"], catalog_title=entry["catalog_title"],
                            description=entry["description"])
        return detections, metadata

    def pairs_with_catalog(rows, limit=None, rejudge=False):
        pairs = pairs_from_class_rows(rows, limit, rejudge)
        for pair in pairs:
            entry = catalog.get(file_uuid(pair["uuid"]))
            if entry and not args.no_catalog:
                pair.update(catalog_title=entry["catalog_title"],
                            description=entry["description"],
                            ministry=entry["ministry"], sector=entry["sector"])
        return pairs

    out_dir = args.out_dir or CLASS_DIR
    judged_path = os.path.join(out_dir, "tier3_judged.jsonl")
    judge = tier3.judge

    def judge_resumable(pairs, client, progress=None, **kwargs):
        """tier3.judge, keeping each verdict as it arrives and sending
        --judge-workers pairs at a time.

        judge() returns everything at the end and writes nothing if the
        server dies on the way, which is hours of work. A pair with a verdict
        in the file is not sent again; one the model could not decide is.

        judge() also sends one pair, waits, sends the next. The model writes
        ~390 tokens of reasoning per verdict at ~30 tokens/s on the T4, so
        that is ~14s a pair, with the server's batch otherwise empty. vLLM
        decodes concurrent requests together: 8 at once measured 3.8s a pair
        with the same verdicts. Each worker is judge() over its own slice.
        """
        judged = {}
        if os.path.exists(judged_path):
            with open(judged_path, encoding="utf-8") as handle:
                for line in handle:
                    kept = json.loads(line)
                    judged[(kept["uuid"], kept["column"])] = kept
        todo = [p for p in pairs if (p["uuid"], p["column"]) not in judged]
        if len(todo) < len(pairs):
            print(f"{len(pairs) - len(todo)} pair(s) already judged in {judged_path}",
                  file=sys.stderr)
        workers = max(1, min(args.judge_workers, len(todo)))
        lock, count = threading.Lock(), [0]
        with open(judged_path, "a", encoding="utf-8") as handle:
            def keep(_index, _total, result):
                with lock:
                    count[0] += 1
                    if result["verdict"]:
                        handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
                        handle.flush()
                    if progress:
                        progress(count[0], len(todo), result)
            with ThreadPoolExecutor(workers) as pool:
                slices = [pool.submit(judge, todo[i::workers], client, progress=keep, **kwargs)
                          for i in range(workers)]
            for done in slices:
                for result in done.result():            # re-raises ServerGaveUp
                    judged[(result["uuid"], result["column"])] = result
        return [judged[(p["uuid"], p["column"])] for p in pairs]

    tier1.load_csv = load_csv_with_catalog
    tier3.pairs_from_class_rows = pairs_with_catalog
    tier3.judge = judge_resumable

    os.makedirs(out_dir, exist_ok=True)
    sys.argv = ["run_lot3_pii.py classify", "--csv", STAGE_ROOT,
                "--summary", SUMMARY_PATH, "--out-dir", out_dir,
                "--output", os.path.join(out_dir, "pii_result.csv")] + extra
    return pipeline.main()


# -- result ------------------------------------------------------------------

RESULT_FIELDS = ["nid", "uuid", "title", "catalog_title", "publisher",
                 "source_file", "pii_status", "final_pii_class", "class_columns",
                 "class_rule_ids", "rows_scanned", "entity_count", "pii_types",
                 "note"]


def result(_args):
    """One row per dublin_core_lot3 row, with the final class or why there is none."""
    import duckdb
    con = duckdb.connect(DB_PATH, read_only=True)
    table = con.execute(f'''
        SELECT nid, "Identifier[UUID]", "Title", "Relation[Catalog Title]",
               coalesce("Publisher[state_department]", "Publisher[ministry_department]")
        FROM {TABLE} ORDER BY nid''').fetchall()
    con.close()

    with open(MANIFEST_PATH, newline="", encoding="utf-8") as handle:
        manifest = {r["uuid"]: r for r in csv.DictReader(handle)}
    with open(PIPELINE_RESULT_PATH, newline="", encoding="utf-8") as handle:
        scanned = {r["file"]: r for r in csv.DictReader(handle)}

    rows = []
    for nid, uuid, title, catalog_title, publisher in table:
        row = dict.fromkeys(RESULT_FIELDS, "")
        row.update(nid=nid, uuid=uuid, title=title, catalog_title=catalog_title,
                   publisher=publisher)
        staged = manifest.get(uuid)
        if staged is None:
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

    with open(RESULT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{TABLE}: {len(rows)} rows")
    for status, count in Counter(r["pii_status"] for r in rows).most_common():
        print(f"  {status:<26} {count:>6}")
    print(f"result: {RESULT_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stage", help="build the folder the scan reads")

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
    p_class.add_argument("--out-dir", help=f"default: {CLASS_DIR}")
    p_class.add_argument("--judge-workers", type=int, default=8, metavar="N",
                         help="pairs sent to the judge at once (default: %(default)s)")
    p_class.add_argument("--no-catalog", action="store_true",
                         help="classify without the dublin_core_lot3 titles, as a "
                              "plain folder run would")

    sub.add_parser("repair", help="restage files the scan could not parse")
    sub.add_parser("result", help="join the final class back to the table rows")

    args, extra = parser.parse_known_args()
    if args.command == "classify":
        return classify(args, extra)
    if extra:
        parser.error(f"unrecognised arguments: {' '.join(extra)}")
    return {"stage": stage, "scan": scan, "repair": repair,
            "result": result}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
