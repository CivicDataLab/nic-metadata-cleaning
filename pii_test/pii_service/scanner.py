"""
The service's bridge into the LOT 2 scan pipeline (the scan step of
api_pipeline.run; Tier 1 and Tier 3 live there).

scan_one is the table scan. scan_text and find_values run the same detectors
over loose text -- a PDF's lines, a free-text column being redacted -- where
the table scan's column statistics do not apply.

Everything here exists so app.py can call the *same* code path as
``run_pii_s3.py --path``: same column selection, same NER models, same
filters, same flag. The service must give the same answer as the CLI on the
same file, so nothing about the scan is reimplemented -- the module globals
run_pii_s3 already uses (_analyzer, _gpu_ner, _max_rows, _ner_batch_size)
are set here exactly the way rescan_sample.py sets them.
"""

import logging
import os
import sys

import pandas as pd

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
PII_TEST_DIR = os.path.dirname(SERVICE_DIR)
REPO_ROOT = os.path.dirname(PII_TEST_DIR)
LOG_PATH = os.path.join(SERVICE_DIR, "pii_service.log")

# run_pii_s3 opens its LOT 1 log with a path relative to the repo root, and
# every other script in pii_test assumes it is run from there; pin the cwd
# so the service behaves the same no matter where it was launched from.
os.chdir(REPO_ROOT)
sys.path.insert(0, PII_TEST_DIR)
# The chdir strands a relative or empty ("") sys.path entry for this folder,
# which is how app.py would otherwise find api_pipeline and storage outside
# gunicorn (gunicorn adds its absolute chdir itself).
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

import run_pii_s3 as R  # noqa: E402  (repoints the root logger; undone below)
import api_pipeline  # noqa: E402

# Uploads are unrelated to our corpus, so the corpus-frequency name blocklist
# does not apply to them (see api_pipeline.disable_corpus_blocklist). This
# process only; CLI runs still load it.
CORPUS_BLOCKLIST_DROPPED = api_pipeline.disable_corpus_blocklist()


def configure_logging():
    """Take the root logger back from run_pii_s3.

    Importing run_pii_s3 calls its configure_logging(force=True), which sends
    *everything* -- including uvicorn's access log -- to pii_test/pii_s3.log
    with no console output. The service gets its own file plus stderr.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)
    logging.info(f"Corpus name blocklist disabled for API runs "
                 f"({CORPUS_BLOCKLIST_DROPPED} entries dropped)")


def load_models(device):
    """Build the analyzer + GPU NER once. Takes about a minute."""
    R._analyzer, R._gpu_ner = R.build_analyzer(
        include_transformer_recognizer=True, device=device
    )
    logging.info(f"Models loaded (device={device})")


def models_loaded():
    return R._analyzer is not None


def _detect(texts, ner_batch_size, strict):
    """The scan's passes over each of ``texts``, without its column pass.

    Returns (one list of detections per text, whether NER failed). The
    passes are run_pii_s3.scan_local_file's own: batched NER, the field-label
    patterns, the regexes, then the per-detection filters. What is left out
    is pii_filters.filter_column_context. That pass keeps a column of
    advisory text from being classified on a few stray spans, and does it by
    dropping any name that covers under half of a long cell unless a "Shri"
    or "Name:" introduces it -- which is most names in a sentence, and every
    name in a row of a scanned list.

    With ``strict`` an NER failure propagates. Without it the regexes still
    run and the failure is reported, as the scan does.
    """
    cells = [(i, "", text, R.detect_language(text))
             for i, text in enumerate(texts) if text]
    failed = False
    try:
        cache = R.batch_analyze_cells(cells, R._analyzer, R._gpu_ner,
                                      ner_batch_size=ner_batch_size) if cells else {}
    except Exception as exc:                            # noqa: BLE001
        if strict:
            raise
        logging.error(f"Batch analysis failed: {type(exc).__name__}")
        cache, failed = {}, True
    found = [[] for _ in texts]
    for i, column, text, _ in cells:
        results = cache.get((i, column), [])
        structured = R.extract_structured_names(text)
        if structured:
            results = R.resolve_overlaps(list(results) + structured)
        spans = [(text[r.start:r.end], r.entity_type, r.score, "presidio")
                 for r in results if R.keep_result(r, text)]
        spans += [(snippet, label, 1.0, "regex")
                  for label, snippet, _, _ in R.regex_pii_matches(text)]
        found[i] = [d for d in ({"entity_type": entity_type, "entity_text": value,
                                 "score": score, "source": source}
                                for value, entity_type, score, source in spans)
                    if api_pipeline.pii_filters.filter_detection(d)]
    return found, failed


def find_values(texts, ner_batch_size=64):
    """What the detectors flag in each of ``texts``, for redaction.

    Returns one list per text of (value, entity type); see _detect for what
    is and is not applied. Caller must serialize calls, like scan_one. An
    NER failure propagates: the caller has to know the names were not looked
    for.
    """
    found, _ = _detect(texts, ner_batch_size, strict=True)
    return [[(d["entity_text"], d["entity_type"]) for d in cell] for cell in found]


def scan_text(path, max_rows, column="text", ner_batch_size=64):
    """scan_one for a document: the lines pdf_text wrote, one per row.

    Same result dict as scan_one. The table scan itself is the wrong tool
    here -- its column pass would drop the names (see _detect), and its
    column heuristics exist to choose among columns a document does not
    have. ``max_rows=None`` reads every line, which is what a PDF gets: its
    limit is pdf_text's page cap. Caller must serialize calls.
    """
    result = {"uuid": os.path.splitext(os.path.basename(path))[0], "error": None,
              "detections": [], "rows_scanned": 0, "columns_scanned": [column],
              "columns_skipped": [], "entity_count": 0, "degraded": False}
    try:
        table = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=max_rows)
        texts = [text.strip() for text in table[column]]
        found, result["degraded"] = _detect(texts, ner_batch_size, strict=False)
    except Exception as exc:                            # noqa: BLE001
        # The type only: a parser error can quote the line it choked on.
        result["error"] = f"The document's text could not be scanned ({type(exc).__name__})"
        return result
    result["rows_scanned"] = len(texts)
    result["detections"] = [dict(d, uuid=result["uuid"], column=column, row_index=row)
                            for row, cell in enumerate(found) for d in cell]
    result["entity_count"] = len(result["detections"])
    return result


def scan_one(path, max_rows, ner_batch_size=64):
    """Scan one local CSV. Caller must serialize calls (one GPU, one model).

    Returns run_pii_s3.scan_local_file's result dict; a failed read/scan
    comes back in its "error" key rather than as an exception.
    """
    R._max_rows = max_rows
    R._ner_batch_size = ner_batch_size
    return R.scan_local_file(path)
