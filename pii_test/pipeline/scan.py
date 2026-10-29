"""The detection scan: read a table, pick the columns worth scanning, find PII in them.

Three passes look at every cell of the chosen columns -- two HuggingFace NER
models on the GPU (XLM-R for Latin script, IndicNER for Devanagari), spaCy with
Presidio's pattern recognizers on the CPU, and the regex detectors in
filters.py -- and filters.py then drops what is not a person or not a real
number, and decides the dataset flag.

run.py's ``scan`` step drives this: start() loads the models (once per
process, or once per pool worker), scanfile() scans one file, and
writedetections() / summaryrows() turn a folder's results into its
``pii_detections.csv`` and summary rows. Nothing here configures logging at
import; logto() does it, from run.py and in each pool worker.
"""

import logging
import os
import re
import warnings

import pandas as pd
import torch
from presidio_analyzer import AnalyzerEngine, BatchAnalyzerEngine, EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from transformers import pipeline as hfpipeline
from transformers.pipelines.token_classification import TokenClassificationPipeline

from filters import datasetflag, filterdetections, headerrule, regexmatches

logger = logging.getLogger(__name__)

# NER models that run on the GPU (plain torch — no spaCy/CuPy involved).
# spaCy must stay on CPU: activating spaCy's GPU (CuPy) alongside torch in
# the same process is what caused the "from_dlpack received an invalid
# capsule" failures in the batched path.
INDICMODEL = "ai4bharat/IndicNER"          # MuRIL-base, Devanagari/Indic scripts
LATINMODEL = "Davlan/xlm-roberta-base-ner-hrl"  # XLM-R base, Latin-script names
SPACYMODEL = "en_core_web_lg"               # CPU; feeds Presidio pattern recognizers

LABELS = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "MISC",
}

# Every OntoNotes label en_core_web_lg emits except PERSON. spaCy's only job
# here is PERSON (KEEP discards the rest downstream), and Presidio logs a
# WARNING for each entity it can't map to a Presidio type -- which floods the
# log with WORK_OF_ART/ORDINAL/PRODUCT noise on every dataset.
SPACYIGNORE = [
    "NORP", "FAC", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "WORK_OF_ART",
    "LAW", "LANGUAGE", "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY",
    "ORDINAL", "CARDINAL",
]


class WordAwarePipeline(TokenClassificationPipeline):
    """TokenClassificationPipeline with a correct word boundary for SentencePiece.

    To merge subword tokens back into words, the pipeline needs to know which
    tokens continue the previous word. For WordPiece/BPE it reads the
    tokenizer\'s ``continuing_subword_prefix`` (BERT\'s ``##``). XLM-R and MuRIL
    are SentencePiece Unigram models: they mark word *starts* with U+2581 and
    have no continuing prefix, so upstream falls back to guessing --

        is_subword = start > 0 and " " not in sentence[start - 1 : start + 1]

    -- and emits ``UserWarning: Tokenizer does not support real words, using
    fallback heuristic`` once per batch. Two things are wrong with the guess:

    1. It tests for an ASCII space only. KCC advisory cells are newline-
       delimited field labels, and a newline is not a space, so every field
       after a name was judged a continuation of it.
    2. More fundamentally, a SentencePiece word-start token *absorbs the
       whitespace before it*: the token spanning "\\nPara" of
       "...MOHAN VERMA\\nParasrampur" starts at the newline, so
       ``sentence[start - 1]`` reads the "R" that ends KUMAR -- one character
       too far left, on a token that plainly begins a word.

    Together those turned a cell whose per-token predictions are exactly right
    (MOHAN VERMA / Parasrampur / HARENDRA YADAV, all at 0.96-1.00) into two
    run-on spans, " Farmer\\nRAHUL" at 0.40 and " SINGH\\nMobile" at 0.65 --
    the second of which is a real name pushed *below*
    filters.SCOREFLOOR by a tokenization artefact.

    The rule below reads the token\'s own first character instead of the one
    before it, which is what SentencePiece itself means by a word start.
    Everything else -- the aggregation strategies, the label grouping -- is
    upstream\'s, unchanged.
    """

    def gather_pre_entities(self, sentence, *args, **kwargs):
        # *args/**kwargs: the upstream signature has gained parameters
        # (word_ids, word_to_chars_map) across releases, and this override
        # cares about none of them.
        with warnings.catch_warnings():
            # The fallback runs and warns inside super() before we correct it.
            warnings.simplefilter("ignore", UserWarning)
            pre_entities = super().gather_pre_entities(sentence, *args, **kwargs)

        for pre in pre_entities:
            start = pre["start"]
            if start is None:
                continue
            pre["is_subword"] = not (
                start == 0
                or sentence[start].isspace()
                or sentence[start - 1].isspace()
            )
        return pre_entities


class NerPipeline:
    """Batched HuggingFace token-classification wrapper for GPU NER.

    Uses fp16 on CUDA (T4 tensor cores) and sorts texts by length before
    batching so padded batches waste less compute.
    """

    # "average" and not "simple": both models use SentencePiece, and under
    # "simple" HF groups adjacent tokens only when their B-/I- tags agree, so a
    # single word whose subword pieces disagree is emitted as several entities
    # ("JHUNJHUNUN" -> "J" + "HUNJHUNUN", "Clerks" -> "C" + "lerks"). That
    # fragmentation fed mangled strings to every downstream filter -- the
    # place-name gazetteer matched none of the top 400 false positives -- and
    # inflated every score, because "simple" reports the max-ish subword score.
    # The word-level strategies (first/max/average) need a fast tokenizer,
    # which both models have. "average" is the one that de-fragments *and*
    # deflates the scores back to something a threshold can act on.
    #
    # Re-checked after WordAwarePipeline fixed the word
    # boundary, since correct grouping changes what each strategy is worth.
    # "average" is still the only one that discriminates: it separates
    # "JHUNJHUNUN" (a village mislabelled PER, 0.46) from "MOHAN VERMA"
    # (0.83), with SCOREFLOOR sitting between them. "max" returns
    # 0.95-1.00 for both -- a max over subwords saturates -- and "first"
    # additionally keeps trailing punctuation ("Ram Prasad,").
    AGGREGATION = "average"

    def __init__(self, name, device="cpu", maxlength=512):
        self.name = name
        dtype = torch.float16 if str(device).startswith("cuda") else None
        try:
            self.pipe = hfpipeline(
                "token-classification",
                model=name,
                aggregation_strategy=self.AGGREGATION,
                device=device,
                torch_dtype=dtype,
                pipeline_class=WordAwarePipeline,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load NER model {name!r}: {exc}\n"
                "XLM-R and MuRIL use SentencePiece tokenizers; if the error mentions "
                "SentencePiece conversion, install the missing backends with:\n"
                "    pip install sentencepiece protobuf"
            ) from exc
        self.pipe.tokenizer.model_max_length = maxlength

    def batch(self, texts, batch_size=64):
        """Run NER over texts. Returns list[list[RecognizerResult]] aligned with texts."""
        if not texts:
            return []
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        outputs = self.pipe([texts[i] for i in order], batch_size=batch_size)
        results = [None] * len(texts)
        for i, found in zip(order, outputs):
            text, spans = texts[i], []
            for out in found:
                label = out.get("entity_group") or out.get("entity")
                if label not in LABELS:
                    continue
                start, end = int(out["start"]), int(out["end"])
                if text:
                    # A SentencePiece word-start token absorbs the whitespace
                    # before it, so spans arrive with it attached
                    # ("\\nParasrampur") and a lone U+2581 at a line break is
                    # a real token with a whitespace-only span -- which
                    # surfaces as a PERSON whose text is "" at score 1.00.
                    # Trim to the content; drop what is left with none.
                    # Downstream this is what makes entity_text and the
                    # filters' cell-coverage ratio exact.
                    while start < end and text[start].isspace():
                        start += 1
                    while end > start and text[end - 1].isspace():
                        end -= 1
                    if start >= end:
                        continue
                spans.append(RecognizerResult(
                    entity_type=LABELS[label], start=start, end=end,
                    score=float(out.get("score", 0.0)), analysis_explanation=None))
            results[i] = spans
        return results


class NerModels:
    """The torch NER models that own the GPU: an XLM-R model for Latin-script
    text (the vast majority of cells) and IndicNER for Devanagari text.

    Both are lazy: a model is downloaded/loaded on first use, so IndicNER
    costs nothing on the ~99% of datasets with no Devanagari text.
    """

    def __init__(self, device="cpu"):
        self.device = device
        self.indicmodel = None
        self.latinmodel = None
        # The Latin model runs on virtually every dataset, so load it now:
        # a broken install then fails once, loudly, at startup instead of
        # degrading every file to regex-only detections for the whole run.
        _ = self.latin

    @property
    def indic(self):
        if self.indicmodel is None:
            self.indicmodel = NerPipeline(INDICMODEL, device=self.device)
        return self.indicmodel

    @property
    def latin(self):
        if self.latinmodel is None:
            self.latinmodel = NerPipeline(LATINMODEL, device=self.device)
        return self.latinmodel


class NerRecognizer(EntityRecognizer):
    """Presidio adapter over an NerPipeline for per-text analyzer.analyze()
    calls (redact.py's path; the batch path bypasses this)."""

    SUPPORTED_ENTITIES = ["PERSON", "LOCATION", "ORGANIZATION", "MISC"]

    def __init__(self, factory, supported_language, name, **kwargs):
        super().__init__(
            supported_entities=self.SUPPORTED_ENTITIES,
            supported_language=supported_language,
            **kwargs,
        )
        self.name = name
        # Callable returning an NerPipeline, so lazy models stay unloaded
        # until this recognizer actually fires.
        self.factory = factory

    def load(self):
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if not text:
            return []
        return self.factory().batch([text], batch_size=1)[0]

HINDI = re.compile(r"[\u0900-\u097F]")

# --- Column selection ---
#
# The header rules (filters.headerrule) decide most columns. What a header
# leaves open is decided by the values: their dtype, and how many distinct
# ones there are.

# A column with a handful of distinct values repeated over many rows is an
# enum, never free-text names. Genuine name columns approach ratio 1.0.
CATDISTINCT = 12
CATRATIO = 0.20
CATROWS = 25

# Values sampled per column for the type/cardinality heuristics.
SAMPLEROWS = 200

# Maps a headerrule decision to how much of the value checks it bypasses
# (see selectcolumns); "skip" and "consider" bypass nothing.
FORCEKINDS = {"force-pii": "pii", "force-person": "person"}

KEEP = {
    "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS",
    "AADHAAR_NUMBER", "PAN_NUMBER", "FARMER_REGISTRATION_ID",
}


def keepresult(res, text):
    """True for a model result of a kind the scan reports."""
    if res.entity_type not in KEEP:
        return False
    if res.entity_type == "PERSON" and len(text[res.start:res.end].strip()) < 3:
        return False
    return True


def language(text):
    return "hi" if HINDI.search(text or "") else "en"


def cardinality(series, limit=None):
    """Distinct/total ratio over the scanned portion of a column.

    Near 1.0 for free-text names (names rarely repeat), near 0 for enums.
    This is what lets a PERSON hit corroborate a dataset-level flag.
    """
    values = series if limit is None else series.head(limit)
    values = values.dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return 0.0
    return values.str.lower().nunique() / len(values)


def selectcolumns(df):
    """The columns worth scanning, and ``(column, reason)`` for the rest.

    The skipped list is returned so the log can say why a column was never
    scanned instead of leaving recall loss invisible.

    What fired in the header decides how much of the value checks a column
    is spared:

    ``"pii"`` (FORCEKINDS)
        email/phone/aadhaar header. Bypasses everything but emptiness -- a
        phone column read as int64 must still reach the regex pass, and a
        two-valued contact column in a tiny file is not an enum.
    ``"person"``
        person-name header. Bypasses the dtype/boolean/numeric/date checks
        for the same reason, but **still runs the cardinality check**: the
        old blanket bypass is what let ``Sub District Head Quarter (Name)``
        -- 17 distinct values over 2,587 rows -- through, for 12,323 false
        detections. A genuine name column sits near ratio 1.0 and is
        unaffected.
    ``None``
        every check applies.
    """
    selected, skipped = [], []
    for col in df.columns:
        decision, reason = headerrule(col)
        if decision == "skip":
            skipped.append((col, reason))
            continue
        force = FORCEKINDS.get(decision)
        series = df[col]

        why = None
        sample = series.dropna().head(SAMPLEROWS)
        if sample.empty:
            why = "no non-null values"
        else:
            texts = sample.astype(str).str.strip()
            texts = texts[texts != ""]
            if texts.empty:
                why = "all values blank"
            elif force != "pii":
                lowered = texts.str.lower()
                if force is None:
                    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
                        why = "numeric/boolean dtype"
                    elif lowered.isin({"true", "false", "yes", "no", "y", "n", "0", "1"}).mean() > 0.9:
                        why = "boolean-valued"
                    elif pd.to_numeric(texts, errors="coerce").notna().mean() > 0.9:
                        why = "numeric-valued"
                    elif pd.to_datetime(texts, errors="coerce", format="mixed").notna().mean() > 0.9:
                        why = "date-valued"
                # Cardinality: an enum repeated over many rows is a category,
                # not names. The row floor keeps small files -- where every
                # column looks low-variety by construction -- from being
                # wrongly rejected.
                if why is None:
                    rows, distinct = len(texts), lowered.nunique()
                    if rows >= CATROWS and distinct <= CATDISTINCT and distinct / rows < CATRATIO:
                        why = f"categorical ({distinct} distinct in {rows} rows)"

        if why is None:
            selected.append(col)
        else:
            skipped.append((col, why))
    return selected, skipped


def models(device="cpu"):
    """Build a Presidio AnalyzerEngine (CPU spaCy) plus the GPU NER models.

    spaCy is deliberately kept on CPU: its GPU mode (CuPy) conflicts with
    torch over DLPack capsules. The GPU is reserved for the torch/HF models
    in NerModels, which is where the NER accuracy comes from anyway.

    Returns (analyzer, ner).
    """
    spacy = [
        {"lang_code": "en", "model_name": SPACYMODEL},
        {"lang_code": "hi", "model_name": "xx_sent_ud_sm"},
    ]
    nlp = SpacyNlpEngine(spacy, ner_model_configuration=NerModelConfiguration(
        labels_to_ignore=SPACYIGNORE))
    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en", "hi"])
    ner = NerModels(device=device)
    # Registered for "hi" only, so per-text analyzer.analyze(language="hi")
    # still gets IndicNER. Not registered for "en": that would make
    # BatchAnalyzerEngine call the GPU model once per text; the batch path
    # runs ner.latin itself, properly batched.
    analyzer.registry.add_recognizer(
        NerRecognizer(lambda: ner.indic, supported_language="hi", name="IndicNerRecognizer"))
    return analyzer, ner


def resolve(results):
    """Reduce overlapping same-type spans over one text to the best of each.

    Three passes look at every cell -- the HF NER models, spaCy via Presidio,
    and the scan's structured field-label patterns -- and they routinely
    find the same name with different boundaries. Deduplicating on an exact
    (type, start, end) key, which is all this used to do, keeps every one of
    them: the PM-Kisan block in the KCC sample reported "MOHAN VERMA" at 0.95
    from the field-label pattern *and* "MOHAN VERMA\\nAddress" at 0.85 from
    spaCy, which is one person counted twice, once with the next field label
    attached.

    Highest score wins; the shorter span breaks a tie, since the tighter
    boundary is the one that has not absorbed a neighbour. Different entity
    types are resolved independently -- "Village Rampur" being a LOCATION does
    not stop a PERSON overlapping it -- and the original order is restored so
    output stays stable.
    """
    order = {id(r): i for i, r in enumerate(results)}
    bytype = {}
    for r in results:
        bytype.setdefault(r.entity_type, []).append(r)

    kept = []
    for candidates in bytype.values():
        accepted = []
        for r in sorted(candidates,
                        key=lambda r: (-r.score, r.end - r.start, order[id(r)])):
            if any(r.start < a.end and a.start < r.end for a in accepted):
                continue
            accepted.append(r)
        kept.extend(accepted)

    return sorted(kept, key=lambda r: order[id(r)])


def analyze(cells, analyzer, ner, spacybatch=32, nerbatch=64):
    """Run batched GPU NER + CPU Presidio over the unique texts in cells.

    ``cells`` is a list of (row, column, text, language) tuples, language "hi"
    or "en". Texts are deduplicated first: government CSVs repeat cell values
    heavily, so each unique string is analyzed once and the results are
    fanned back out to every cell containing it. Returns
    {(row, column): [RecognizerResult]}.
    """
    cache = {}
    if not cells:
        return cache

    where, lang = {}, {}
    for row, col, text, script in cells:
        where.setdefault(text, []).append((row, col))
        lang[text] = script
    texts = list(where)
    found = {t: [] for t in texts}

    # Results land in ``found`` as they are produced, so a failure in one pass
    # leaves the other pass's output intact. Each pass guards its own
    # failures, but anything that escapes them (OOM, a torch-level fault) must
    # not discard what the other pass already produced -- so the fan-out
    # below always runs.
    try:
        # 1. GPU NER, batched over unique texts: IndicNER for Devanagari,
        #    XLM-R for Latin script. Access .indic/.latin only for non-empty
        #    groups so an unused lazy model is never loaded, and inside the
        #    try: lazy model construction can fail (missing tokenizer
        #    dependency, bad download), and that must not abort the Presidio
        #    pass below for the whole file.
        if ner is not None:
            for label, group, model in (
                    ("indic", [t for t in texts if lang[t] == "hi"], lambda: ner.indic),
                    ("latin", [t for t in texts if lang[t] == "en"], lambda: ner.latin)):
                if not group:
                    continue
                try:
                    for t, results in zip(group, model().batch(group, batch_size=nerbatch)):
                        found[t].extend(results)
                except Exception as exc:
                    logger.warning("GPU NER (%s) failed: %s", label, exc)

        # 2. CPU Presidio (spaCy + pattern recognizers) over all unique texts
        #    in one "en" pass. The pattern recognizers are script-agnostic and
        #    the "hi" spaCy model (xx_sent_ud_sm) has no NER component, so a
        #    single en pass covers everything the old en/hi/hi-as-en passes did.
        try:
            engine = BatchAnalyzerEngine(analyzer_engine=analyzer)
            results = engine.analyze_iterator(texts, language="en", batch_size=spacybatch)
            for t, spans in zip(texts, results):
                found[t].extend(spans)
        except Exception as exc:
            logger.warning(
                "BatchAnalyzerEngine failed (%s); falling back to per-text analysis.", exc)
            for t in texts:
                try:
                    found[t].extend(analyzer.analyze(text=t, language="en"))
                except Exception as textexc:
                    logger.debug("Per-text analysis failed: %s", textexc)
    except Exception as exc:
        logger.error(
            "Batch analysis failed mid-run (%s); keeping partial results for %d text(s).",
            exc, sum(1 for v in found.values() if v))

    # 3. Resolve each unique text's results down to one span per region, then
    #    fan out to every cell that contained that text.
    for t, results in found.items():
        kept = resolve(results)
        if not kept:
            continue
        for key in where[t]:
            cache[key] = list(kept)
    return cache


# Field labels the PM-Kisan registration block pastes into KCC answers, where
# the value on the next line is a name whatever the model thinks of it.
#
# The case-insensitivity is scoped to the *label*. Written as a leading
# "(?i)" it also applied to the capture group, so "[A-Z][A-Z\s]{2,40}" --
# meant to read one line of an ALL-CAPS name -- matched any letters and any
# whitespace, newlines included, and ran on through the rest of the record:
# "MOHAN VERMA\\nAddress\\nParasrampur\\nDate of R". The capture is now
# confined to a single line by excluding the newline from its character class.
#
# The separator is optional because the block is not consistently formatted:
# "Name Of Farmer\\nMOHAN VERMA" and "Name Of Farmer MD AZAD" and
# "Address :Pachdahi" all occur. Requiring a newline or a colon missed the
# third form, and what filled the gap was spaCy\'s looser reading of the same
# text ("Farmer MD AZAD\\nAddress").
FIELDNAMES = [
    re.compile(r"(?i:name\s+of\s+farmer)\s*:?\s*([A-Za-z][A-Za-z .]{2,40})"),
    re.compile(r"(?i:farmer\s+name)\s*:?\s*([A-Za-z][A-Za-z .]{2,40})"),
    re.compile(r"(?i:father[/\w]*\s+name)\s*:?\s*([A-Za-z][A-Za-z .]{2,40})"),
    re.compile(r"(?i:guardian\s+name)\s*:?\s*([A-Za-z][A-Za-z .]{2,40})"),
]


def fieldnames(text):
    """Extract names from known KCC/PM-Kisan field label patterns.

    Spans are de-duplicated: "Father/Spouse/Guardian Name:" is matched by both
    the father and the guardian pattern, which otherwise emits the same name
    twice and doubles its weight in every column statistic downstream.
    """
    results = []
    seen = set()
    for pat in FIELDNAMES:
        for m in pat.finditer(text or ""):
            start, end = m.span(1)
            while end > start and text[end - 1].isspace():
                end -= 1
            if end - start < 3 or (start, end) in seen:
                continue
            seen.add((start, end))
            results.append(RecognizerResult(
                entity_type="PERSON",
                start=start,
                end=end,
                score=0.95,
                analysis_explanation=None,
            ))
    return results

# --- Reading a table ---

# Tabular formats the scan understands. Excel is not incidental here: the Lok
# Sabha member directories ship as .xls, and a format that is silently
# skipped looks identical to one that was scanned and found clean.
TABULAR = (".csv", ".xls", ".xlsx")


def readtable(path, nrows=None):
    """Read a CSV or Excel file, reading at most ``nrows`` data rows.

    Bounding the read is what makes a folder of real datasets scannable: the
    largest file in the test corpus is 490MB, of which only the first
    ``maxrows`` rows are ever looked at. A CSV that is not UTF-8 is read as
    Windows-1252 (0xa0 etc. are common in data.gov.in exports).
    """
    if os.path.splitext(path)[1].lower() in (".xls", ".xlsx"):
        try:
            return pd.read_excel(path, nrows=nrows)
        except ImportError as exc:
            # .xls needs xlrd, .xlsx needs openpyxl. Say which, rather than
            # letting a missing optional dependency read as a corrupt file.
            raise RuntimeError(
                f"Cannot read {os.path.basename(path)}: {exc}. "
                "Install the Excel engine with: pip install xlrd openpyxl"
            ) from exc
    try:
        return pd.read_csv(path, nrows=nrows)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", encoding_errors="replace", nrows=nrows)


# --- What a folder's scan writes ---

DETECTIONS = "pii_detections.csv"

# Characters of a cell kept before each span, for the naming-cue rule in
# filters.incontext. Wider than filters.CUEWINDOW so the filter, not the
# scan, owns how far back it looks.
CONTEXTCHARS = 64


def summaryrows(root, paths, results):
    """One summary row per file scanned.

    ``label`` is the first folder under ``root``: a lot's shard, a KCC state,
    or in the test corpus the expected answer (pii-present / pii-permissible
    / pii-false-postive), so the summary is directly gradeable without the
    caller having to join anything back together.
    """
    rows = []
    for path, result in zip(paths, results):
        rel = os.path.relpath(path, root)
        parent = os.path.dirname(rel)
        rows.append({
            "file": rel,
            "label": parent.split(os.sep)[0] if parent else "",
            "rows_scanned": result["rows_scanned"],
            "pii_found": result["pii_found"],
            "pii_flag_reason": result.get("pii_flag_reason"),
            "entity_count": result["entity_count"],
            "pii_types": ",".join(result["pii_types"]),
            "columns_scanned": len(result.get("columns_scanned") or []),
            "columns_skipped": len(result.get("columns_skipped") or []),
            "degraded": result.get("degraded", False),
            "error": result["error"],
        })
    return rows


def writedetections(paths, results):
    """Write one ``pii_detections.csv`` per folder, beside the files it covers.

    A folder run is a comparison between folders, so the detections are
    grouped the same way -- one file per folder rather than one per input,
    which otherwise scatters a CSV beside every dataset. Each row carries the
    source file so a consolidated view stays traceable back to it. A folder
    with no detection gets no file.
    """
    byfolder = {}
    for path, result in zip(paths, results):
        for det in result["detections"]:
            byfolder.setdefault(os.path.dirname(path), []).append(
                {"file": os.path.basename(path), **det})

    for folder, detections in sorted(byfolder.items()):
        out = os.path.join(folder, DETECTIONS)
        # "uuid" is the filename stem for local scans -- redundant next to the
        # explicit file column, and confusing in a folder-level export.
        pd.DataFrame(detections).drop(columns=["uuid"], errors="ignore").to_csv(out, index=False)
        logging.info(f"Saved {len(detections)} detections to {out}")


# --- Scanning a file ---

# The models and settings of this process, set by start(): once for a
# single-process run, and in every worker of a pool (start is the pool's
# initializer), which is why they are module state rather than arguments.
analyzer = None      # Presidio AnalyzerEngine: spaCy and the pattern recognizers, CPU
ner = None           # NerModels: the two HuggingFace models, GPU when there is one
maxrows = 250        # rows scanned per file
nerbatch = 64        # GPU NER batch size


def logto(path, console=True):
    """Point the root logger at ``path``, and at stderr too with ``console``."""
    handlers = [logging.FileHandler(path)] + ([logging.StreamHandler()] if console else [])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers, force=True)
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)


def start(gpu=False, rows=250, batch=64, log=None):
    """Load the models into this process. ``log``: a pool worker's log file."""
    global analyzer, ner, maxrows, nerbatch
    if log:
        logto(log, console=False)
    device = "cuda" if gpu and torch.cuda.is_available() else "cpu"
    analyzer, ner = models(device)
    maxrows, nerbatch = rows, batch
    logging.info(f"Worker {os.getpid()} initialized (device={device})")


def scanfile(path):
    """Scan one table. Returns a result dict; a failure is in ``error``."""
    uuid = os.path.splitext(os.path.basename(path))[0]
    result = {
        "uuid": uuid,
        "pii_found": False,
        "pii_types": [],
        "entity_count": 0,
        "rows_scanned": 0,
        "detections": [],
        "degraded": False,
        "pii_flag_reason": None,
        "columns_scanned": [],
        "columns_skipped": [],
        "error": None,
    }

    try:
        # Only the first ``maxrows`` rows are ever scanned, but the column
        # heuristics sample up to SAMPLEROWS rows independently -- so reading
        # fewer than that would quietly change which columns get skipped.
        df = readtable(path, nrows=max(maxrows, SAMPLEROWS))
        columns, skipped = selectcolumns(df)
        # A column that is never scanned cannot produce a detection, so silent
        # skipping looks identical to "scanned and clean" in the output. The
        # per-column detail goes to DEBUG; the INFO line keeps the shape of
        # the decision visible.
        logging.info("%s: scanning %d/%d column(s)%s", uuid, len(columns),
                     len(columns) + len(skipped), f" -> {columns}" if columns else " (none)")
        for col, why in skipped:
            logging.debug("%s: skipped column %r (%s)", uuid, col, why)
        result["columns_scanned"] = columns
        result["columns_skipped"] = skipped
        if not columns:
            return result

        rows = min(maxrows, len(df))
        detections = []

        cells = []
        text = {}
        for i in range(rows):
            row = df.iloc[i]
            for col in columns:
                value = str(row.get(col) or "").strip()
                if not value:
                    continue
                cells.append((i, col, value, language(value)))
                text[(i, col)] = value

        try:
            cache = analyze(cells, analyzer, ner, nerbatch=nerbatch)
        except Exception as exc:
            logging.error(f"Batch analysis failed for {uuid}: {exc}")
            cache = {}
            result["degraded"] = True

        # Merge structured field extractions into cache per cell. These
        # arrive after analyze has already resolved overlaps among its own
        # passes, so the affected cells are resolved again -- a field-label
        # name and spaCy's looser reading of the same name are exactly the
        # pair that needs it.
        for i, col, value, _ in cells:
            structured = fieldnames(value)
            if structured:
                cache[(i, col)] = resolve(cache.get((i, col), []) + structured)

        for (i, col), results in cache.items():
            value = text[(i, col)]
            for r in results:
                if not keepresult(r, value):
                    continue
                detections.append({
                    "uuid": uuid,
                    "column": col,
                    "row_index": i,
                    "entity_type": r.entity_type,
                    "entity_text": value[r.start:r.end],
                    "score": r.score,
                    "source": "presidio",
                    # Where the span sits in its cell. filterdetections reads
                    # these and strips them, so they never reach an export.
                    "cell_len": len(value),
                    "left_context": value[max(0, r.start - CONTEXTCHARS):r.start],
                })

        for (i, col), value in text.items():
            for label, snippet, _, _ in regexmatches(value):
                detections.append({
                    "uuid": uuid,
                    "column": col,
                    "row_index": i,
                    "entity_type": label,
                    "entity_text": snippet,
                    "score": 1.0,
                    "source": "regex",
                })

        ratios = {col: cardinality(df[col], rows) for col in columns}
        detections = filterdetections(detections, ratios)
        found, why = datasetflag(detections, ratios, rows=rows)

        result["rows_scanned"] = rows
        result["pii_found"] = found
        result["pii_flag_reason"] = why
        # Derive types from the post-filter detections so the summary never
        # lists an entity type whose hits were all filtered out.
        result["pii_types"] = sorted({d["entity_type"] for d in detections})
        result["entity_count"] = len(detections)
        result["detections"] = detections
    except Exception as e:
        result["error"] = str(e)

    return result
