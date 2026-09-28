"""
The API's own PII pipeline: scan -> Tier 1 -> Tier 3 -> one answer per file.

Deliberately separate from pii_classify_pipeline.py. The script classifies
*our* corpus, whose metadata lives in metadata.db and whose statistics the
filters were tuned on. An upload through the API is an unrelated dataset:
its title, catalog title and description come from the request, and nothing
learned from the corpus is assumed to hold for it. So this module imports
only the building blocks -- the scan, Tier 1's rules and vocabularies,
Tier 3's prompt and judge -- and does its own orchestration. None of the
script-side files is edited to serve the API.

Nothing here knows about FastAPI; app.py calls run() in its worker thread.

Run layout (also what is uploaded to S3, see storage.py):

    <run_dir>/input/<file>.csv        the upload (app.py puts it there)
    <run_dir>/request.json            request metadata + options (app.py)
    <run_dir>/result.json             the answer -- see run()
    <run_dir>/columns.csv             the flagged columns, one row each
    <run_dir>/detail/detections.csv   per detection, as the scan produced them
    <run_dir>/detail/tier1_column_class.csv
    <run_dir>/detail/tier3_verdicts.csv   only when the judge ran
    <run_dir>/detail/column_class.csv     final per-column rows
    <run_dir>/run.log                 this run's log lines (app.py)
"""

import csv
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
PII_TEST_DIR = os.path.dirname(SERVICE_DIR)
if PII_TEST_DIR not in sys.path:
    sys.path.insert(0, PII_TEST_DIR)

import pii_classify as tier1  # noqa: E402
import pii_filters  # noqa: E402
import pii_tier3 as tier3  # noqa: E402

log = logging.getLogger("pii_api")

# pii_column_class's lot is 1 or 2 for the corpus and 0 for a --csv run; an
# upload belongs to none of them.
API_LOT = "api"
# Bounds the judge's share of one run: each pair can take up to a minute on
# the T4, and a wide file could otherwise hold the queue for an hour.
MAX_TIER3_PAIRS = 40

JUDGE_ENDPOINT = os.environ.get("PII_JUDGE_ENDPOINT", tier3.ENDPOINT)
JUDGE_MODEL = os.environ.get("PII_JUDGE_MODEL", tier3.MODEL)

DETECTION_FIELDS = ("uuid", "column", "row_index", "entity_type",
                    "entity_text", "score", "source")
COLUMN_FIELDS = ("column", "class", "pii_types", "decided_by", "reason")

# Most serious first: decides the file's class and orders the column table.
# Deliberately not tier1.DATASET_CLASS_ORDER, which ranks permissible above
# undecided -- for "can this be published?" that would call a file with an
# unreviewed column publishable.
CLASS_ORDER = ("present", "undecided", "permissible", "false_positive")

# Files a client may download from a finished run, by public name.
DOWNLOADS = {
    "result.json": "result.json",
    "columns.csv": "columns.csv",
    "detections.csv": "detail/detections.csv",
    "tier1_column_class.csv": "detail/tier1_column_class.csv",
    "tier3_verdicts.csv": "detail/tier3_verdicts.csv",
    "column_class.csv": "detail/column_class.csv",
}


def disable_corpus_blocklist():
    """Stop the scan dropping names for being common in *our* datasets.

    pii_filters rejects any value seen in more than CROSS_DATASET_MAX corpus
    datasets (gazetteer/cross_dataset_common.txt). That is a statistic about
    our corpus, not about an uploaded file, and for one it would silently drop
    a private person who shares a name with someone frequent in ours. The
    dict is module state, so clearing it affects this process only; the
    hand-curated gazetteers stay on. Returns how many entries were dropped.
    """
    dropped = len(pii_filters.CROSS_DATASET_COUNTS)
    pii_filters.CROSS_DATASET_COUNTS.clear()
    return dropped


def judge_problem(endpoint=None, model=None):
    """Why Tier 3 cannot run right now, or None if it can.

    Same check as pii_classify_pipeline.server_problem, kept here so the API
    does not depend on the script.
    """
    endpoint, model = endpoint or JUDGE_ENDPOINT, model or JUDGE_MODEL
    parts = urllib.parse.urlsplit(endpoint)
    models_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))
    try:
        with urllib.request.urlopen(models_url, timeout=5) as response:
            served = [m.get("id") for m in json.load(response).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"no LLM judge at {models_url} ({exc})"
    if served and model not in served:
        return f"{models_url} serves {', '.join(served)}, not {model}"
    return None


# --------------------------------------------------------------------------
# Tier 1
# --------------------------------------------------------------------------

def dataset_metadata(input_path, meta):
    """What the tiers know about the upload: the request's fields + header row.

    Without a title the file name stands in for one, unless it is a UUID --
    the same fallback pii_classify.load_csv uses, for the same reason.
    Underscores read as spaces: app.py turns every space in an upload name
    into one, and "List_of_beneficiaries" gives Tier 1's word-boundary
    patterns nothing to match.
    """
    stem = os.path.splitext(os.path.basename(input_path))[0]
    fallback = None if tier1.UUID_STEM.match(stem) else stem.replace("_", " ")
    return {
        "title": meta.get("title") or fallback,
        "catalog_title": meta.get("catalog_title") or None,
        "description": meta.get("description") or None,
        "source_file": input_path,
        "headers": tier1.read_header_row(input_path),
    }


def tier1_detections(scan_detections, file_key):
    """Scan detections in the shape classify_detections reads."""
    return [{"uuid": file_key, "lot": API_LOT, "column": d["column"],
             "entity_type": d["entity_type"], "entity_text": d["entity_text"],
             "score": d.get("score"), "source": d.get("source"),
             "cardinality": None}
            for d in scan_detections]


# --------------------------------------------------------------------------
# Tier 3
# --------------------------------------------------------------------------

def build_pairs(rows, dataset_meta):
    """Tier 3 pairs for the columns Tier 1 left undecided.

    The API's counterpart of pii_tier3.pairs_from_class_rows, which leaves
    catalog title and description empty because a --csv run has none. Here
    they come from the request and go into the judge's prompt.
    """
    detected = sorted({r["column"] for r in rows})
    headers = dataset_meta.get("headers")
    pairs = []
    for r in sorted((r for r in rows if r["pii_class"] == "undecided"),
                    key=lambda r: r["column"]):
        evidence = r.get("evidence_json") or {}
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        pairs.append({
            "uuid": r["uuid"], "lot": r["lot"], "column": r["column"],
            "entity_types": r.get("entity_types"),
            "n_detections": r.get("n_detections"),
            "n_distinct": r.get("n_distinct"), "rule_id": r.get("rule_id"),
            "evidence": evidence,
            "title": dataset_meta.get("title"),
            "catalog_title": dataset_meta.get("catalog_title"),
            "description": dataset_meta.get("description"),
            "ministry": None, "sector": None,
            "headers": headers or detected,
            "headers_source": "file" if headers else "detected_columns",
        })
    return pairs


def run_tier3(rows, dataset_meta, *, llm=True, client=None, problem=judge_problem,
              progress=None):
    """Send Tier 1's undecided columns to the judge.

    Returns (final rows, tier3 info, judge results). The run always goes on:
    when the judge is off, down or gives up, Tier 1's rows stand and the
    columns it could not decide stay undecided -- ``status`` says why.
    """
    pairs = build_pairs(rows, dataset_meta)
    info = {"status": "not_needed", "detail": None, "pairs": len(pairs),
            "judged": 0, "not_judged": 0}
    if not pairs:
        return rows, info, []
    if not llm:
        info.update(status="skipped", detail="llm=false in the request",
                    not_judged=len(pairs))
        return rows, info, []
    why = problem()
    if why:
        log.warning(f"Tier 3 not run: {why}")
        info.update(status="unavailable", detail=why, not_judged=len(pairs))
        return rows, info, []

    judged = pairs[:MAX_TIER3_PAIRS]
    info["not_judged"] = len(pairs) - len(judged)
    client = client or tier3.VLLMClient(JUDGE_ENDPOINT, JUDGE_MODEL, tier3.MAX_TOKENS)
    log.info(f"Tier 3: judging {len(judged)} undecided column(s)"
             + (f", {info['not_judged']} over the cap left undecided"
                if info["not_judged"] else ""))

    def on_pair(i, total, result):
        mark = result["verdict"] or f"undecided ({result['error']})"
        log.info(f"Tier 3 [{i}/{total}] {result['column']!r} -> {mark}")
        if progress:
            progress("tier3", i, total)

    if progress:
        # Now, not after the first verdict: a column can take the judge tens
        # of seconds, and until then the run would still read as "tier1".
        progress("tier3", 0, len(judged))
    try:
        results = tier3.judge(judged, client, progress=on_pair)
    except tier3.ServerGaveUp as exc:
        log.warning(f"Tier 3 aborted: {exc}")
        info.update(status="aborted", detail=str(exc), not_judged=len(pairs))
        return rows, info, []
    info.update(status="ran", judged=len(results))
    return tier3.apply_verdicts(rows, tier3.to_rows(results)), info, results


# --------------------------------------------------------------------------
# The answer
# --------------------------------------------------------------------------

def column_table(rows):
    """One simple row per flagged column, loudest class first."""
    table = [{
        "column": r["column"],
        "class": r["pii_class"],
        "pii_types": r.get("entity_types") or "",
        "decided_by": "tier3" if r.get("rule_id") == "T3-judge" else "tier1",
        "reason": r.get("reason") or "",
    } for r in rows]
    table.sort(key=lambda c: (CLASS_ORDER.index(c["class"])
                              if c["class"] in CLASS_ORDER else len(CLASS_ORDER),
                              c["column"]))
    return table


def final_class(rows):
    """The file's class: that of its most serious column (see CLASS_ORDER)."""
    if not rows:
        return "no_pii_found"
    classes = {r["pii_class"] for r in rows}
    return next((c for c in CLASS_ORDER if c in classes), "undecided")


def message(cls, columns):
    """The one line a person reads first."""
    def named(wanted):
        names = [c["column"] for c in columns if c["class"] == wanted]
        return len(names), ", ".join(names)

    if cls == "present":
        n, names = named("present")
        return f"Personal data found in {n} column(s): {names}. Redact before publishing."
    if cls == "undecided":
        n, names = named("undecided")
        return (f"{n} column(s) could not be decided automatically ({names}); "
                f"needs manual review.")
    if cls == "permissible":
        return ("Personal data found, but it is official/public-role "
                "information that may be published.")
    if cls == "false_positive":
        return "Detections were checked and are not personal data."
    return "No personal data detected."


def warnings_for(scan, tier3_info, metadata_source):
    out = []
    if not scan.get("columns_scanned"):
        # Otherwise "no personal data detected" reads as a clean bill of
        # health for a file nobody actually looked into.
        skipped = len(scan.get("columns_skipped") or [])
        out.append(f"Nothing was scanned: none of the file's {skipped} column(s) "
                   f"holds free text (numbers, codes, dates or empty were skipped).")
    elif not scan.get("rows_scanned"):
        out.append("Nothing was scanned: the file has no data rows.")
    if scan.get("degraded"):
        out.append("NER failed on this file; only the regex detectors ran.")
    if tier3_info["status"] in ("unavailable", "aborted"):
        out.append(f"The LLM judge did not run ({tier3_info['status']}); "
                   f"{tier3_info['not_judged']} column(s) left undecided.")
    elif tier3_info["status"] == "ran" and tier3_info["not_judged"]:
        out.append(f"{tier3_info['not_judged']} column(s) over the per-run "
                   f"judge limit of {MAX_TIER3_PAIRS} left undecided.")
    if metadata_source == "filename":
        out.append("No title or description was sent; the rules only had the "
                   "file name and header row to go on.")
    return out


def _write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_result(run_dir, result):
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False, default=str)


def error_result(run_id, filename, error, s3_folder=None):
    return {"run_id": run_id, "status": "error", "file": filename,
            "error": error, "s3_folder": s3_folder}


def run(input_path, run_dir, meta, *, run_id, scan, max_rows, llm=True,
        progress=None, timings=None, judge_client=None,
        judge_check=judge_problem, s3_folder=None):
    """Scan one upload, classify it, write the run's files. Returns result.json.

    ``scan(path, max_rows)`` is scanner.scan_one in the service (tests pass a
    stub). A failed read comes back as a result with status "error" rather
    than an exception; anything unexpected propagates to the caller.
    """
    timings = {} if timings is None else timings
    progress = progress or (lambda stage, done, total: None)
    filename = os.path.basename(input_path)
    detail = os.path.join(run_dir, "detail")
    os.makedirs(detail, exist_ok=True)

    # -- Scan ------------------------------------------------------------------
    progress("scanning", 0, 0)
    started = time.time()
    log.info(f"scan: {filename} (max_rows={max_rows})")
    scan_result = scan(input_path, max_rows)
    timings["scan"] = round(time.time() - started, 2)
    if scan_result["error"]:
        log.error(f"scan failed: {scan_result['error']}")
        result = error_result(run_id, filename, scan_result["error"], s3_folder)
        write_result(run_dir, result)
        return result
    _write_csv(os.path.join(detail, "detections.csv"),
               scan_result["detections"], DETECTION_FIELDS)
    log.info(f"scan: {scan_result['rows_scanned']} row(s), "
             f"{len(scan_result['columns_scanned'])} column(s) scanned, "
             f"{scan_result['entity_count']} detection(s) kept "
             f"({timings['scan']}s)")

    # -- Tier 1 ----------------------------------------------------------------
    progress("tier1", 0, 0)
    started = time.time()
    metadata_source = ("request" if any(meta.get(k) for k in
                                        ("title", "catalog_title", "description"))
                       else "filename")
    file_key = filename
    dataset_meta = dataset_metadata(input_path, meta)
    rows = []
    if scan_result["detections"]:
        rows = tier1.classify_detections(
            tier1_detections(scan_result["detections"], file_key),
            {file_key: dataset_meta})
        tier1.write_rows_csv(os.path.join(detail, "tier1_column_class.csv"), rows)
    timings["tier1"] = round(time.time() - started, 2)
    counts = {c: sum(1 for r in rows if r["pii_class"] == c) for c in tier1.CLASSES}
    log.info(f"tier1: {len(rows)} column(s) -> "
             + ", ".join(f"{c} {n}" for c, n in counts.items() if n)
             + (f"; context {rows[0]['dataset_context']}" if rows else ""))

    # -- Tier 3 ----------------------------------------------------------------
    started = time.time()
    final, tier3_info, judged = run_tier3(
        rows, dataset_meta, llm=llm, client=judge_client, problem=judge_check,
        progress=progress)
    timings["tier3"] = round(time.time() - started, 2)
    if judged:
        tier3.write_verdicts_csv(os.path.join(detail, "tier3_verdicts.csv"), judged)
    if final:
        tier1.write_rows_csv(os.path.join(detail, "column_class.csv"), final)

    # -- Answer ----------------------------------------------------------------
    columns = column_table(final)
    cls = final_class(final)
    _write_csv(os.path.join(run_dir, "columns.csv"), columns, COLUMN_FIELDS)
    result = {
        "run_id": run_id,
        "status": "done",
        "file": filename,
        "final_class": cls,
        "message": message(cls, columns),
        "columns": columns,
        "rows_scanned": scan_result["rows_scanned"],
        "rows_limit": max_rows,
        "tier3": tier3_info["status"],
        "metadata_source": metadata_source,
        "warnings": warnings_for(scan_result, tier3_info, metadata_source),
        "s3_folder": s3_folder,
    }
    write_result(run_dir, result)
    log.info(f"result: {cls} ({len(columns)} flagged column(s), "
             f"tier3 {tier3_info['status']})")
    return result
