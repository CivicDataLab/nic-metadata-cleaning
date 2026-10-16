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

    <run_dir>/input/<file>            the upload (app.py puts it there)
    <run_dir>/converted/<name>.csv    the table scanned, when the upload was not
                                      one already (convert.py); for a PDF, its
                                      text as page, line, text (pdf_text.py)
    <run_dir>/request.json            request metadata + options (app.py)
    <run_dir>/result.json             the answer -- see run()
    <run_dir>/columns.csv             the flagged columns, one row each
    <run_dir>/results.csv             every detection with both tiers' verdicts
    <run_dir>/redacted.csv            only when asked for: the table with its
                                      `present` columns redacted (redact.py)
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
import traceback
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

import convert  # noqa: E402
import redact as redactor  # noqa: E402

log = logging.getLogger("pii_api")

# pii_column_class's lot is 1 or 2 for the corpus and 0 for a --csv run; an
# upload belongs to none of them.
API_LOT = "api"
# Bounds the judge's share of one run: each pair can take up to a minute on
# the T4, and a wide file could otherwise hold the queue for an hour.
MAX_TIER3_PAIRS = 40
# The scan reads at least this many rows whatever max_rows says
# (run_pii_s3.read_row_limit); redaction has to read the file the same way.
COLUMN_SAMPLE_ROWS = 200                      # pii_utils.COLUMN_SAMPLE_ROWS
# Below this average word confidence tesseract is guessing: the clean test
# scans read at 92-95, a skewed and speckled one at 84.
LOW_OCR_CONFIDENCE = 70

JUDGE_ENDPOINT = os.environ.get("PII_JUDGE_ENDPOINT", tier3.ENDPOINT)
JUDGE_MODEL = os.environ.get("PII_JUDGE_MODEL", tier3.MODEL)

DETECTION_FIELDS = ("uuid", "column", "row_index", "entity_type",
                    "entity_text", "score", "source")
COLUMN_FIELDS = ("column", "class", "pii_types", "decided_by", "reason")
RESULT_FIELDS = ("column", "row_index", "entity_type", "entity_text", "score",
                 "source", "tier1_class", "tier1_reason", "llm_verdict",
                 "llm_reasoning", "final_class", "decided_by")

# Most serious first: decides the file's class and orders the column table.
# Deliberately not tier1.DATASET_CLASS_ORDER, which ranks permissible above
# undecided -- for "can this be published?" that would call a file with an
# unreviewed column publishable.
CLASS_ORDER = ("present", "undecided", "permissible", "false_positive")

# Files a client may download from a finished run, by public name.
DOWNLOADS = {
    "result.json": "result.json",
    "columns.csv": "columns.csv",
    "results.csv": "results.csv",
    "redacted.csv": "redacted.csv",
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

def dataset_metadata(input_path, meta, headers=True):
    """What the tiers know about the upload: the request's fields + header row.

    ``headers=False`` for a PDF: the header of its table of lines is ours
    (page, line, text) and says nothing about the document.

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
        "headers": tier1.read_header_row(input_path) if headers else None,
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


def results_table(detections, tier1_rows, final_rows, judged):
    """Every detection with what each tier said about its column.

    The tiers rule on a column, not on a value, so a verdict is repeated on
    each of the column's detections; ``llm_verdict`` is empty for a column
    the judge was never asked about. The judge's reasoning is written only on
    the rows whose value was in its prompt (tier3.build_prompt shows the
    first MAX_SAMPLE_VALUES distinct ones): it runs to TRACE_KEPT characters,
    and a free-text column can hold tens of thousands of detections.
    """
    tier1_by_column = {r["column"]: r for r in tier1_rows}
    final_by_column = {r["column"]: r for r in final_rows}
    judged_by_column = {}
    for r in judged:
        samples = (r.get("evidence") or {}).get("sample_values") or []
        judged_by_column[r["column"]] = (
            r, {str(v) for v in samples[:tier3.MAX_SAMPLE_VALUES]})

    order = {c["column"]: i for i, c in enumerate(column_table(final_rows))}
    table = []
    for d in detections:
        first = tier1_by_column.get(d["column"], {})
        last = final_by_column.get(d["column"], {})
        verdict, shown = judged_by_column.get(d["column"], (None, ()))
        in_prompt = str(d["entity_text"]) in shown
        reasoning = ""
        if verdict and in_prompt:
            reasoning = verdict["trace"] or f"(no verdict: {verdict['error']})"
        table.append({
            "column": d["column"], "row_index": d["row_index"],
            "entity_type": d["entity_type"], "entity_text": d["entity_text"],
            "score": d.get("score"), "source": d.get("source"),
            "tier1_class": first.get("pii_class", ""),
            "tier1_reason": first.get("reason") or "",
            "llm_verdict": (verdict["verdict"] or "no verdict") if verdict else "",
            "llm_reasoning": reasoning,
            "final_class": last.get("pii_class", ""),
            "decided_by": ("tier3" if last.get("rule_id") == "T3-judge" else "tier1"),
        })
    table.sort(key=lambda r: (order.get(r["column"], len(order)), r["column"],
                              r["row_index"]))
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


def warnings_for(scan, tier3_info, metadata_source, document=False):
    """``document`` is a PDF, which has pages rather than columns and rows;
    pdf_warnings says what was and was not read of it."""
    out = []
    if document:
        pass
    elif not scan.get("columns_scanned"):
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
                   + ("file name to go on." if document
                      else "file name and header row to go on."))
    return out


def table_warnings(table):
    """What convert.prepare found out about the upload that the user should know."""
    out = []
    if table["disguised"]:
        out.append("The file is named as an Excel workbook but holds plain "
                   "text; it was read as CSV.")
    if len(table["sheets"]) > 1:
        # Otherwise a clean answer reads as one for the whole workbook.
        first, others = table["sheets"][0], table["sheets"][1:]
        out.append(f"Only the first sheet ({first}) was checked; {len(others)} "
                   f"other sheet(s) were not: {', '.join(map(str, others))}.")
    if table["pdf"]:
        out += pdf_warnings(table["pdf"])
    return out


# --------------------------------------------------------------------------
# PDFs
# --------------------------------------------------------------------------
# A PDF is checked as one column of text, a row per line. The tiers run on it
# unchanged; what differs is how the answer is worded -- pages, not columns.

PDF_RESULT_FIELDS = ("page", "line") + RESULT_FIELDS
REDACTION_NOT_FOR_PDF = {
    "status": "not_supported",
    "message": "A redacted copy cannot be made of a PDF yet; the check above "
               "is unaffected."}


def page_list(pages, limit=12):
    """Page numbers as a person writes them: "1, 4, 7-9"."""
    runs = []
    for page in sorted(set(pages)):
        if runs and page == runs[-1][1] + 1:
            runs[-1][1] = page
        else:
            runs.append([page, page])
    shown = [str(a) if a == b else f"{a}-{b}" for a, b in runs[:limit]]
    return ", ".join(shown) + (", ..." if len(runs) > limit else "")


def document_rows(path):
    """(page, line) of each row of pdf_text's table, by row index."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [(int(row["page"]), int(row["line"])) for row in csv.DictReader(handle)]


def pdf_message(cls, pages):
    if cls == "present":
        return (f"Personal data found on {len(pages)} page(s): {page_list(pages)}. "
                f"Redact before publishing.")
    if cls == "undecided":
        return (f"What was found on {len(pages)} page(s) ({page_list(pages)}) could "
                f"not be decided automatically; needs manual review.")
    return message(cls, [])


def pdf_warnings(summary):
    """What was not read of a PDF, and how far to trust what was."""
    out = []
    read, empty = summary["pages_read"], summary["pages_empty"]
    if read < summary["pages"]:
        # Otherwise a clean answer reads as one for the whole document.
        out.append(f"Only the first {read} of {summary['pages']} pages were checked.")
    if len(empty) == read:
        out.append("Nothing was checked: no text could be read from this PDF.")
    elif empty:
        out.append(f"No text could be read from {len(empty)} page(s): "
                   f"{page_list(empty)}.")
    if summary["pages_ocr"] > len(empty):
        out.append(f"{summary['pages_ocr']} page(s) were read by OCR; a misread "
                   f"letter or digit can hide a name or a number.")
    confidence = summary.get("ocr_confidence")
    if confidence is not None and confidence < LOW_OCR_CONFIDENCE:
        out.append(f"The OCR was unsure of what it read (average confidence "
                   f"{confidence}%); treat a clean result with caution.")
    return out


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

def run_redaction(table, run_dir, columns, scan_result, *, find_values, max_rows,
                  progress=None):
    """The redacted copy. Returns (result.json's ``redaction``, warnings).

    Nothing that goes wrong here fails the run: the check has its answer
    either way, and a copy that cannot be vouched for is simply not offered.
    """
    present = [c["column"] for c in columns if c["class"] == "present"]
    if not present:
        return {"status": "not_needed",
                "message": "No column was classified present, so there was "
                           "nothing to redact."}, []

    def searched(column, columns_, done, total):
        # One count across the free-text columns, so the bar never restarts.
        if progress:
            progress("redacting", column * total + done, columns_ * total)

    try:
        done = redactor.redact_file(
            table["path"], os.path.join(run_dir, DOWNLOADS["redacted.csv"]),
            present, scan_result["detections"],
            rows_read=max(max_rows, COLUMN_SAMPLE_ROWS),
            find_values=find_values, progress=searched)
    except redactor.RedactionError as exc:
        log.error(f"redact failed: {exc}")
        return {"status": "failed", "message": f"Redaction failed: {exc}."}, []
    except Exception as exc:                            # noqa: BLE001
        # The frames, not the message: a pandas error can quote a cell.
        log.error(f"redact failed: {type(exc).__name__}\n"
                  + "".join(traceback.format_tb(exc.__traceback__)))
        return {"status": "failed",
                "message": f"Redaction failed: {type(exc).__name__}."}, []

    notes = list(done["notes"])
    undecided = [str(c["column"]) for c in columns if c["class"] == "undecided"]
    if undecided:
        notes.append(f"The redacted copy still holds {len(undecided)} undecided "
                     f"column(s): {', '.join(undecided)}. Review them before "
                     f"publishing.")
    if len(table["sheets"]) > 1:
        notes.append("The redacted copy holds the first sheet only.")
    return {"status": "done",
            "message": f"{len(done['columns'])} column(s) redacted in "
                       f"{done['rows']:,} row(s).",
            "rows": done["rows"], "columns": done["columns"]}, notes


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
        redact=False, find_values=None, scan_text=None, progress=None,
        timings=None, judge_client=None, judge_check=judge_problem,
        s3_folder=None):
    """Scan one upload, classify it, write the run's files. Returns result.json.

    ``scan(path, max_rows)`` is scanner.scan_one in the service (tests pass a
    stub), and ``scan_text`` is scanner.scan_text, which takes its place for
    a PDF. A file that cannot be read comes back as a result with status
    "error" rather than an exception; anything unexpected propagates to the
    caller. ``redact`` adds the redacted copy, whose own failure is reported
    in the result and never fails the run; ``find_values(texts)`` is
    scanner.find_values, which it searches free text with.
    """
    timings = {} if timings is None else timings
    progress = progress or (lambda stage, done, total: None)
    filename = os.path.basename(input_path)
    detail = os.path.join(run_dir, "detail")
    os.makedirs(detail, exist_ok=True)

    # -- The table -------------------------------------------------------------
    # From here on the tiers see table["path"]: for a JSON upload the header
    # row and the rows are the converted CSV's, never the raw file's.
    progress("converting", 0, 0)
    started = time.time()
    try:
        table = convert.prepare(
            input_path, run_dir,
            progress=lambda done, total: progress("converting", done, total))
    except convert.ConversionError as exc:
        log.error(f"convert failed: {exc}")
        result = error_result(run_id, filename, str(exc), s3_folder)
        write_result(run_dir, result)
        return result
    timings["convert"] = round(time.time() - started, 2)
    is_pdf = table["kind"] == "pdf"
    if is_pdf:
        read = table["pdf"]
        log.info(f"convert: {filename}: {read['pages_read']} of {read['pages']} "
                 f"page(s) read, {read['pages_ocr']} by OCR, {read['lines']:,} "
                 f"line(s) ({timings['convert']}s)")
    elif table["converted"]:
        log.info(f"convert: {filename} -> converted/{os.path.basename(table['path'])}"
                 + (f", {table['records']:,} record(s)" if table["records"] else "")
                 + f" ({timings['convert']}s)")
    elif table["sheets"]:
        log.info(f"convert: workbook with {len(table['sheets'])} sheet(s); "
                 f"the first is read")

    # -- Scan ------------------------------------------------------------------
    progress("scanning", 0, 0)
    started = time.time()
    log.info(f"scan: {filename}" + ("" if is_pdf else f" (max_rows={max_rows})"))
    # A PDF's limit is its page cap. max_rows on top of it would stop part-way
    # through the lines while the answer still said every page was checked.
    scan_result = (scan_text(table["path"], None) if is_pdf
                   else scan(table["path"], max_rows))
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
    dataset_meta = dataset_metadata(table["path"], meta, headers=not is_pdf)
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
    results = results_table(scan_result["detections"], rows, final, judged)
    pages = []
    if is_pdf:
        where = document_rows(table["path"])
        for row in results:
            row["page"], row["line"] = where[row["row_index"]]
        pages = sorted({row["page"] for row in results if row["final_class"] == cls})
    _write_csv(os.path.join(run_dir, "results.csv"), results,
               PDF_RESULT_FIELDS if is_pdf else RESULT_FIELDS)
    result = {
        "run_id": run_id,
        "status": "done",
        "file": filename,
        "final_class": cls,
        "message": pdf_message(cls, pages) if is_pdf else message(cls, columns),
        "columns": columns,
        "rows_scanned": scan_result["rows_scanned"],
        "rows_limit": None if is_pdf else max_rows,
        "tier3": tier3_info["status"],
        "metadata_source": metadata_source,
        "warnings": (table_warnings(table)
                     + warnings_for(scan_result, tier3_info, metadata_source,
                                    document=is_pdf)),
        "s3_folder": s3_folder,
    }
    if is_pdf:
        result["pdf"] = {"pages": table["pdf"]["pages"],
                         "pages_checked": table["pdf"]["pages_read"],
                         "pages_ocr": table["pdf"]["pages_ocr"],
                         "pages_with_findings": pages}
    log.info(f"result: {cls} ({len(columns)} flagged column(s), "
             f"tier3 {tier3_info['status']})")

    # -- Redacted copy ---------------------------------------------------------
    if redact and is_pdf:
        result["redaction"] = dict(REDACTION_NOT_FOR_PDF)
    elif redact:
        progress("redacting", 0, 0)
        started = time.time()
        result["redaction"], notes = run_redaction(
            table, run_dir, columns, scan_result, find_values=find_values,
            max_rows=max_rows, progress=progress)
        result["warnings"] += notes
        timings["redact"] = round(time.time() - started, 2)
        log.info(f"redact: {result['redaction']['status']} ({timings['redact']}s)")
    write_result(run_dir, result)
    return result
