import logging
import os
import re

import pandas as pd
from presidio_analyzer import (
    AnalyzerEngine,
    BatchAnalyzerEngine,
    EntityRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine, NerModelConfiguration
from transformers import pipeline as hf_pipeline

logger = logging.getLogger(__name__)

# NER models that run on the GPU (plain torch — no spaCy/CuPy involved).
# spaCy must stay on CPU: activating spaCy's GPU (CuPy) alongside torch in
# the same process is what caused the "from_dlpack received an invalid
# capsule" failures in the batched path.
INDIC_NER_MODEL = "ai4bharat/IndicNER"          # MuRIL-base, Devanagari/Indic scripts
LATIN_NER_MODEL = "Davlan/xlm-roberta-base-ner-hrl"  # XLM-R base, Latin-script names
EN_SPACY_MODEL = "en_core_web_lg"               # CPU; feeds Presidio pattern recognizers

NER_LABEL_MAP = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "MISC",
}

# Every OntoNotes label en_core_web_lg emits except PERSON. spaCy's only job
# here is PERSON (KEEP discards the rest downstream), and Presidio logs a
# WARNING for each entity it can't map to a Presidio type -- which floods the
# log with WORK_OF_ART/ORDINAL/PRODUCT noise on every dataset.
SPACY_LABELS_TO_IGNORE = [
    "NORP", "FAC", "ORG", "GPE", "LOC", "PRODUCT", "EVENT", "WORK_OF_ART",
    "LAW", "LANGUAGE", "DATE", "TIME", "PERCENT", "MONEY", "QUANTITY",
    "ORDINAL", "CARDINAL",
]


class HfNerPipeline:
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
    AGGREGATION_STRATEGY = "average"

    def __init__(self, model_name, device="cpu", max_length=512):
        import torch

        self.model_name = model_name
        dtype = torch.float16 if str(device).startswith("cuda") else None
        try:
            self._pipe = hf_pipeline(
                "token-classification",
                model=model_name,
                aggregation_strategy=self.AGGREGATION_STRATEGY,
                device=device,
                torch_dtype=dtype,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load NER model {model_name!r}: {exc}\n"
                "XLM-R and MuRIL use SentencePiece tokenizers; if the error mentions "
                "SentencePiece conversion, install the missing backends with:\n"
                "    pip install sentencepiece protobuf"
            ) from exc
        self._pipe.tokenizer.model_max_length = max_length
        self._label_map = NER_LABEL_MAP

    def analyze_batch(self, texts, batch_size=64):
        """Run NER over texts. Returns list[list[RecognizerResult]] aligned with texts."""
        if not texts:
            return []
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        outputs = self._pipe([texts[i] for i in order], batch_size=batch_size)
        results = [None] * len(texts)
        for i, out in zip(order, outputs):
            results[i] = self._to_results(out)
        return results

    def _to_results(self, outputs):
        results = []
        for out in outputs:
            label = out.get("entity_group") or out.get("entity")
            if label not in self._label_map:
                continue
            results.append(
                RecognizerResult(
                    entity_type=self._label_map[label],
                    start=int(out["start"]),
                    end=int(out["end"]),
                    score=float(out.get("score", 0.0)),
                    analysis_explanation=None,
                )
            )
        return results


class GpuNerEngines:
    """The torch NER models that own the GPU: an XLM-R model for Latin-script
    text (the vast majority of cells) and IndicNER for Devanagari text.

    Both are lazy: a model is downloaded/loaded on first use, so IndicNER
    costs nothing on the ~99% of datasets with no Devanagari text.
    """

    def __init__(self, device="cpu", indic_model=INDIC_NER_MODEL,
                 latin_model=LATIN_NER_MODEL, preload_latin=True):
        self.device = device
        self._indic_model = indic_model
        self._latin_model = latin_model
        self._indic = None
        self._latin = None
        # The Latin model runs on virtually every dataset, so load it now:
        # a broken install then fails once, loudly, at startup instead of
        # degrading every file to regex-only detections for the whole run.
        if preload_latin:
            _ = self.latin

    @property
    def indic(self):
        if self._indic is None:
            self._indic = HfNerPipeline(self._indic_model, device=self.device)
        return self._indic

    @property
    def latin(self):
        if self._latin is None:
            self._latin = HfNerPipeline(self._latin_model, device=self.device)
        return self._latin


class HfNerRecognizer(EntityRecognizer):
    """Presidio adapter over an HfNerPipeline for per-text analyzer.analyze()
    calls (used by the redaction script; the batch path bypasses this)."""

    SUPPORTED_ENTITIES = ["PERSON", "LOCATION", "ORGANIZATION", "MISC"]

    def __init__(self, pipeline_factory, supported_language, name, **kwargs):
        super().__init__(
            supported_entities=self.SUPPORTED_ENTITIES,
            supported_language=supported_language,
            **kwargs,
        )
        self.name = name
        # Callable returning an HfNerPipeline, so lazy models stay unloaded
        # until this recognizer actually fires.
        self._pipeline_factory = pipeline_factory

    def load(self):
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        if not text:
            return []
        return self._pipeline_factory().analyze_batch([text], batch_size=1)[0]


# --- Constants ---

Hindi_RE = re.compile(r"[\u0900-\u097F]")

# --- Column selection ---
#
# Headers are matched on whole tokens, never substrings. The previous
# substring match had two failure modes that between them dominated the
# LOT 2 results: "blockname" never matched the real-world "Udise_Block_Name"
# (so block columns were scanned and produced ~28% of all detections), while
# a bare "id" matched inside "Guide_Name" / "President_Name" / "Bidder_Name"
# (so the columns most likely to hold real names were silently never scanned).

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Tokens that mark a column as structurally incapable of holding personal
# data: administrative geography, closed categorical vocabularies, codes and
# temporal fields.
SKIP_COLUMN_TOKENS = {
    # administrative geography
    "block", "blocks", "district", "districts", "state", "states",
    "village", "villages", "city", "cities", "town", "ward", "panchayat",
    "tehsil", "taluk", "taluka", "subdistrict", "region", "zone", "circle",
    "constituency", "location", "loc", "place", "area", "pincode", "pin",
    "country", "nation",
    # closed categorical vocabularies
    "qualification", "management", "mgmt", "category", "categories",
    "type", "types", "medium", "stream", "subject", "status", "gender",
    "sex", "caste", "religion", "scheme", "level", "grade", "class",
    "unit", "units", "sector", "designation", "department",
    "discipline", "disciplines", "hostel", "hostels",
    # languages: "Mother Tongue Name" is a census language list, and once the
    # negative bigram cancels its "mother" it needs a skip token of its own to
    # land on.
    "tongue", "language", "languages", "dialect", "dialects",
    # goods: "Agricultural/Manufacturers/Handicrafts Commodities (First..Third)"
    # in the census village directories. These hold crop and craft names and
    # cannot hold a person, and they were 74% of the surviving detections and
    # 10 of the 15 surviving dataset flags in the 1,000-dataset re-scan. The
    # commodities gazetteer only ever caught the ones spelled canonically --
    # the source cells are full of typos and mid-word truncations
    # ("BARLEY, PATATO, MUSTE") that no value list can enumerate. A person-name
    # token still overrides this, so a hypothetical "Commodity Owner Name"
    # is still scanned.
    "commodity", "commodities", "handicraft", "handicrafts",
    # organisation names -- not personal data, and the largest residual
    # source of PERSON false positives once geography is excluded
    # ("University", "Name of Institution", "College_name", ...)
    "university", "universities", "institution", "institutions",
    "institute", "college", "colleges", "school", "schools", "company",
    "firm", "agency", "organisation", "organization", "org", "bank",
    "branch", "office", "hospital", "centre", "center", "programme",
    "program", "course", "ministry", "board", "committee",
    # identifiers and codes
    "code", "codes", "id", "ids", "sno", "srno", "serial", "no", "number",
    # temporal
    "year", "month", "date", "time", "day", "quarter", "period", "session",
}

# Tokens that, paired with "name", mark a column as holding personal names.
# These override SKIP_COLUMN_TOKENS so that e.g. "District_Officer_Name" is
# still scanned despite the "district" token.
PERSON_NAME_TOKENS = {
    "father", "mother", "guardian", "spouse", "husband", "wife", "parent",
    "candidate", "applicant", "beneficiary", "student", "teacher", "pupil",
    "employee", "officer", "official", "owner", "holder", "person",
    "customer", "patient", "farmer", "member", "director", "proprietor",
    "principal", "head", "staff", "nominee", "signatory", "bidder",
    "resident", "president", "secretary", "contractor",
    "recipient", "awardee", "trainee", "guide", "author",
}

# Adjacent-token pairs in which a PERSON_NAME_TOKEN is not a person. The
# override above cannot simply be dropped -- the genuine
# "Name of Vice-Chancellor/Director/Head" column depends on it -- but in these
# compounds the person reading is always wrong: "Sub District Head Quarter
# (Name)" is census geography (12,323 detections) and "Mother Tongue Name" is
# a language list (2,005), which between them were 35% of the LOT 2 table.
# Cancellation is per-bigram, so the VC column, which has no negative bigram,
# still forces.
NEGATIVE_PERSON_BIGRAMS = {
    ("head", "quarter"), ("head", "quarters"), ("head", "office"),
    ("head", "count"), ("crime", "head"), ("mother", "tongue"),
    ("account", "head"), ("budget", "head"),
}

# Tokens that force a scan on their own -- these columns are PII by
# definition regardless of anything else in the header.
FORCE_SCAN_TOKENS = {
    "email", "mail", "mobile", "phone", "telephone", "contact",
    "aadhaar", "aadhar", "uid", "pan", "passport",
}

# A column with a handful of distinct values repeated over many rows is an
# enum, never free-text names. Genuine name columns approach ratio 1.0.
CATEGORICAL_MAX_DISTINCT = 12
CATEGORICAL_MAX_RATIO = 0.20
CATEGORICAL_MIN_ROWS = 25

# Values sampled per column for the type/cardinality heuristics.
COLUMN_SAMPLE_ROWS = 200


def normalize_column_tokens(name):
    """Split a column header into lowercase tokens.

    Headers in this corpus mix every convention -- ``Udise_Block_Name``,
    ``blockName``, ``S. No.``, ``loc_name`` -- so camelCase and acronym
    boundaries are split first, then any run of non-alphanumerics.
    """
    spaced = _ACRONYM_BOUNDARY_RE.sub(" ", _CAMEL_BOUNDARY_RE.sub(" ", str(name)))
    return [t for t in _NON_ALNUM_RE.split(spaced.lower()) if t]


def _token_variants(token):
    """A token plus its singular form, so "locations" matches "location"."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return {token, token[:-1]}
    return {token}


# Minimum length for the glued-header substring fallback below. Short tokens
# ("id", "no", "pin") must never be matched as substrings -- that is exactly
# the rule that used to skip "Guide_Name" and "President_Name".
_SUBSTRING_MIN_LEN = 5


def cancelled_person_tokens(raw, glued=None):
    """Person tokens a NEGATIVE_PERSON_BIGRAM cancels in this header.

    Cancellation is per-token, driven by the adjacent pair the token sits in:
    "head" in ``Sub District Head Quarter (Name)`` is geography, "head" in
    ``Name of Vice-Chancellor/Director/Head`` is a person. Both members of a
    matched pair are returned; only the person one can matter, since the other
    is not in PERSON_NAME_TOKENS.
    """
    pairs = set()
    for a, b in zip(raw, raw[1:]):
        for a_var in _token_variants(a):
            for b_var in _token_variants(b):
                pairs.add((a_var, b_var))
    if glued is not None:
        # "mothertongue" / "headquarter" written without a separator.
        pairs.update(pair for pair in NEGATIVE_PERSON_BIGRAMS
                     if pair[0] + pair[1] in glued)

    cancelled = set()
    for pair in pairs & NEGATIVE_PERSON_BIGRAMS:
        cancelled.update(pair)
        cancelled.update(_token_variants(pair[0]) | _token_variants(pair[1]))
    return cancelled


def classify_column_name(col):
    """Decide what a column header alone says about scanning it.

    Returns ``(decision, reason)`` where decision is one of:
      "force-pii"    -- email/phone/aadhaar header: scan regardless of *any*
                        value-based heuristic (a phone column read as int64
                        must still reach the regex pass)
      "force-person" -- person-name header: scan despite dtype and despite a
                        skip token, but still subject to the cardinality check
      "skip"         -- never scan
      "consider"     -- fall through to the value-based checks
    """
    raw = normalize_column_tokens(col)
    if not raw:
        return "consider", None

    tokens = set()
    for t in raw:
        tokens |= _token_variants(t)

    # Headers written without separators ("blockname", "instituionname",
    # "fathername") collapse to a single token, so those get a substring
    # fallback -- restricted to long tokens, which is what keeps it safe.
    glued = "".join(raw) if len(raw) == 1 else None

    def match(vocab, exclude=frozenset()):
        if exclude:
            vocab = vocab - exclude
        hit = tokens & vocab
        if hit:
            return sorted(hit)[0]
        if glued is not None:
            long_hits = [v for v in vocab if len(v) >= _SUBSTRING_MIN_LEN and v in glued]
            if long_hits:
                return sorted(long_hits, key=len, reverse=True)[0]
        return None

    forced = match(FORCE_SCAN_TOKENS)
    if forced:
        return "force-pii", f"force token {forced!r}"

    if tokens & {"name"} or (glued is not None and "name" in glued):
        cancelled = cancelled_person_tokens(raw, glued)
        person = match(PERSON_NAME_TOKENS, exclude=cancelled)
        if person:
            return "force-person", f"person-name token {person!r}"

    skipped = match(SKIP_COLUMN_TOKENS)
    if skipped:
        return "skip", f"non-PII token {skipped!r}"

    return "consider", None


# Maps a classify_column_name decision to the force kind _column_skip_reason
# understands; "skip"/"consider" map to None (no bypass).
FORCE_KINDS = {"force-pii": "pii", "force-person": "person"}

aadhaar_pattern = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
pan_pattern = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
phone_pattern = re.compile(
    r"(?<!\d)(?:\+?91[\s\-]?)?(?:[6-9]\d{9}|[6-9]\d{4}[\s\-]\d{5})(?!\d)"
)
farmer_reg_pattern = re.compile(r"(?i)\b[a-z]{2}\d{9}\b")

# Verhoeff checksum tables. The 12th digit of an Aadhaar number is a Verhoeff
# check digit over the preceding 11, so this is an exact test, not a
# heuristic: every number UIDAI has ever issued passes it, and ~90% of
# arbitrary 12-digit numbers do not. _D is the dihedral group D5
# multiplication table and _P the position permutation.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

# Repeated-digit fillers are the one family Verhoeff does not catch:
# 333333333333, 666666666666 and 999999999999 all carry a valid check digit,
# and those are exactly the values a government CSV uses for "not supplied".
# Rejecting palindromes removes all three (and matches Presidio's
# InAadhaarRecognizer). It is the only rule here that is not free: roughly
# one issued Aadhaar in a million is a palindrome, and this would miss it.
_AADHAAR_SEPARATORS_RE = re.compile(r"[\s\-]")

KEEP = {
    "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS",
    "AADHAAR_NUMBER", "PAN_NUMBER", "FARMER_REGISTRATION_ID",
}

# LOT 2: datasets live directly under a per-ministry folder (no batch_N
# subfolders), so discovery is "list ministry folders, then list CSVs in
# each" rather than deriving an S3 key from a batch number.
LOT2_S3_ROOT_PREFIX = "downloaded-datasets/"
LOT2_EXCLUDED_FOLDERS = {"downloaded-datasets-mohfw", "ogdp-sample-datasets"}


def keep_result(res: RecognizerResult, text: str) -> bool:
    if res.entity_type not in KEEP:
        return False
    if res.entity_type == "PERSON" and len(text[res.start:res.end].strip()) < 3:
        return False
    return True


# --- Functions ---

def detect_language(text):
    return "hi" if Hindi_RE.search(text or "") else "en"


def verhoeff_check(digits):
    """True when `digits` carries a valid Verhoeff check digit in its last place."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def is_valid_aadhaar(raw):
    """True when `raw` can actually be an issued Aadhaar number.

    aadhaar_pattern only checks the shape (12 digits, first not 0 or 1), which
    every 12-digit code, meter reading and aggregate volume in the corpus also
    satisfies. This is what makes AADHAAR_NUMBER worth its place in
    pii_filters.HIGH_PRECISION_ENTITIES, where one hit flags a dataset on its
    own.
    """
    digits = _AADHAAR_SEPARATORS_RE.sub("", raw or "")
    if len(digits) != 12 or not digits.isdecimal():
        return False
    if digits[0] in "01":
        return False
    if digits == digits[::-1]:
        return False
    return verhoeff_check(digits)


def regex_pii_matches(text):
    matches = []
    patterns = (
        (aadhaar_pattern, "AADHAAR_NUMBER"),
        (pan_pattern, "PAN_NUMBER"),
        (phone_pattern, "PHONE_NUMBER"),
        (farmer_reg_pattern, "FARMER_REGISTRATION_ID"),
    )
    for pat, label in patterns:
        for m in pat.finditer(text or ""):
            raw = (m.group(0) or "").strip()
            if not raw:
                continue
            if label == "AADHAAR_NUMBER" and not is_valid_aadhaar(raw):
                continue
            if label == "FARMER_REGISTRATION_ID":
                raw = re.sub(r"[\s\-/]+", "", raw).upper()
            start, end = m.span()
            matches.append((label, raw, start, end))
    return matches


def is_phone_entity(entity_type):
    return "PHONE" in (entity_type or "").upper()


def regex_matches_to_results(regex_matches):
    """Convert regex match tuples to RecognizerResult objects."""
    results = []
    for label, _, start, end in regex_matches:
        results.append(
            RecognizerResult(
                entity_type=label,
                start=start,
                end=end,
                score=1.0,
                analysis_explanation=None,
            )
        )
    return results


def analyze_multi_language(analyzer, text, languages):
    """Run the analyzer across multiple languages and de-duplicate overlaps."""
    all_results = []
    for lang in languages:
        all_results.extend(analyzer.analyze(text=text, language=lang))
    seen = set()
    unique = []
    for r in all_results:
        key = (r.entity_type, r.start, r.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def list_ministry_folders(s3_client, bucket, root_prefix=LOT2_S3_ROOT_PREFIX, exclude=LOT2_EXCLUDED_FOLDERS):
    """List per-ministry folder names directly under root_prefix (LOT 2), skipping excluded ones."""
    paginator = s3_client.get_paginator("list_objects_v2")
    folders = []
    for page in paginator.paginate(Bucket=bucket, Prefix=root_prefix, Delimiter="/"):
        for common_prefix in page.get("CommonPrefixes", []):
            name = common_prefix["Prefix"][len(root_prefix):].rstrip("/")
            if name and name not in exclude:
                folders.append(name)
    return sorted(folders)


def list_ministry_csv_keys(s3_client, bucket, ministry, root_prefix=LOT2_S3_ROOT_PREFIX):
    """List (uuid, s3_key) tuples for every CSV directly under a ministry folder (LOT 2)."""
    prefix = f"{root_prefix}{ministry}/"
    paginator = s3_client.get_paginator("list_objects_v2")
    items = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(".csv"):
                continue
            uuid = os.path.splitext(os.path.basename(key))[0]
            items.append((uuid, key))
    return items


def _column_skip_reason(series, force_kind=None):
    """Value-based reasons to skip a column, or None to scan it.

    ``force_kind`` is what fired in the header, and it decides how much is
    bypassed:

    ``"pii"``
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
    sample = series.dropna().head(COLUMN_SAMPLE_ROWS)
    if sample.empty:
        return "no non-null values"

    sample_str = sample.astype(str).str.strip()
    sample_str = sample_str[sample_str != ""]
    if sample_str.empty:
        return "all values blank"

    if force_kind == "pii":
        return None

    lowered_values = sample_str.str.lower()

    if force_kind is None:
        if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
            return "numeric/boolean dtype"

        bool_tokens = {"true", "false", "yes", "no", "y", "n", "0", "1"}
        if lowered_values.isin(bool_tokens).mean() > 0.9:
            return "boolean-valued"

        if pd.to_numeric(sample_str, errors="coerce").notna().mean() > 0.9:
            return "numeric-valued"

        if pd.to_datetime(sample_str, errors="coerce", format="mixed").notna().mean() > 0.9:
            return "date-valued"

    # Cardinality: an enum repeated over many rows is a category, not names.
    # The row floor keeps small files -- where every column looks low-variety
    # by construction -- from being wrongly rejected.
    n_rows = len(sample_str)
    n_distinct = lowered_values.nunique()
    if (n_rows >= CATEGORICAL_MIN_ROWS
            and n_distinct <= CATEGORICAL_MAX_DISTINCT
            and n_distinct / n_rows < CATEGORICAL_MAX_RATIO):
        return f"categorical ({n_distinct} distinct in {n_rows} rows)"

    return None


def column_cardinality_ratio(series, limit=None):
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


def select_detection_columns(df, return_skipped=False):
    """Select columns likely to contain PII-relevant text data.

    Returns the selected column names. With ``return_skipped=True`` returns
    ``(selected, skipped)`` where skipped is a list of ``(column, reason)``,
    so callers can log why a column was never scanned instead of leaving
    recall loss invisible.
    """
    selected = []
    skipped = []
    for col in df.columns:
        decision, reason = classify_column_name(col)
        if decision == "skip":
            skipped.append((col, reason))
            continue

        value_reason = _column_skip_reason(df[col], FORCE_KINDS.get(decision))
        if value_reason is not None:
            skipped.append((col, value_reason))
            continue

        selected.append(col)

    return (selected, skipped) if return_skipped else selected


def build_analyzer(include_transformer_recognizer=True, device="cpu"):
    """Build a Presidio AnalyzerEngine (CPU spaCy) plus the GPU NER engines.

    spaCy is deliberately kept on CPU: its GPU mode (CuPy) conflicts with
    torch over DLPack capsules. The GPU is reserved for the torch/HF models
    in GpuNerEngines, which is where the NER accuracy comes from anyway.

    Returns: (analyzer, gpu_ner | None)
    """
    models = [
        {"lang_code": "en", "model_name": EN_SPACY_MODEL},
        {"lang_code": "hi", "model_name": "xx_sent_ud_sm"},
    ]
    ner_config = NerModelConfiguration(labels_to_ignore=SPACY_LABELS_TO_IGNORE)
    nlp_engine = SpacyNlpEngine(models, ner_model_configuration=ner_config)
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en", "hi"],
    )
    gpu_ner = None
    if include_transformer_recognizer:
        gpu_ner = GpuNerEngines(device=device)
        # Registered for "hi" only, so per-text analyzer.analyze(language="hi")
        # still gets IndicNER. Not registered for "en": that would make
        # BatchAnalyzerEngine call the GPU model once per text; the batch
        # path runs gpu_ner.latin itself, properly batched.
        analyzer.registry.add_recognizer(
            HfNerRecognizer(lambda: gpu_ner.indic, supported_language="hi", name="IndicNerRecognizer")
        )
    return analyzer, gpu_ner


def batch_analyze_cells(
    cell_info,
    analyzer,
    gpu_ner,
    spacy_batch_size=32,
    ner_batch_size=64,
):
    """Run batched GPU NER + CPU Presidio over the unique texts in cell_info.

    Texts are deduplicated first: government CSVs repeat cell values heavily,
    so each unique string is analyzed once and the results are fanned back
    out to every cell containing it.

    Parameters
    ----------
    cell_info : list[tuple[Any, str, str, str]]
        (row_key, col, text, language) tuples; language is "hi" or "en".
    analyzer : AnalyzerEngine
    gpu_ner : GpuNerEngines | None
    spacy_batch_size : int
        Batch size for BatchAnalyzerEngine (spaCy nlp.pipe, CPU).
    ner_batch_size : int
        Batch size for the HF NER pipelines (GPU).

    Returns
    -------
    dict[(row_key, col), list[RecognizerResult]]
        Deduped detections per cell.
    """
    cache: dict = {}
    if not cell_info:
        return cache

    text_cells: dict = {}
    text_lang: dict = {}
    for row_key, col, text, lang in cell_info:
        text_cells.setdefault(text, []).append((row_key, col))
        text_lang[text] = lang

    unique_texts = list(text_cells)
    per_text = {t: [] for t in unique_texts}

    # Steps 1 and 2 guard their own failures, but anything that escapes them
    # (OOM, a torch-level fault) must not discard the results the other pass
    # already produced -- so the fan-out in step 3 always runs.
    try:
        _analyze_unique_texts(
            unique_texts, per_text, text_lang, analyzer, gpu_ner,
            spacy_batch_size, ner_batch_size,
        )
    except Exception as exc:
        logger.error(
            "Batch analysis failed mid-run (%s); keeping partial results for %d text(s).",
            exc, sum(1 for v in per_text.values() if v),
        )

    # 3. Dedup per unique text on (entity_type, start, end), then fan out
    #    to every cell that contained that text.
    for t, results in per_text.items():
        seen = set()
        deduped = []
        for r in results:
            k = (r.entity_type, r.start, r.end)
            if k not in seen:
                seen.add(k)
                deduped.append(r)
        if not deduped:
            continue
        for cell_key in text_cells[t]:
            cache[cell_key] = list(deduped)

    return cache


def _analyze_unique_texts(unique_texts, per_text, text_lang, analyzer, gpu_ner,
                          spacy_batch_size, ner_batch_size):
    """Run the GPU NER and CPU Presidio passes, accumulating into per_text.

    Results land in per_text as they are produced, so a failure in one pass
    leaves the other pass's output intact for the caller.
    """
    # 1. GPU NER, batched over unique texts: IndicNER for Devanagari,
    #    XLM-R for Latin script.
    if gpu_ner is not None:
        hi_texts = [t for t in unique_texts if text_lang[t] == "hi"]
        en_texts = [t for t in unique_texts if text_lang[t] == "en"]
        # Access .indic/.latin only for non-empty groups so an unused lazy
        # model is never loaded.
        groups = (
            ("indic", hi_texts, lambda: gpu_ner.indic),
            ("latin", en_texts, lambda: gpu_ner.latin),
        )
        for label, texts, get_pipe in groups:
            if not texts:
                continue
            # get_pipe() must stay inside the try: lazy model construction can
            # fail (missing tokenizer dependency, bad download), and that must
            # not abort the Presidio pass below for the whole file.
            try:
                pipe = get_pipe()
                for t, results in zip(texts, pipe.analyze_batch(texts, batch_size=ner_batch_size)):
                    per_text[t].extend(results)
            except Exception as exc:
                logger.warning("GPU NER (%s) failed: %s", label, exc)

    # 2. CPU Presidio (spaCy + pattern recognizers) over all unique texts in
    #    one "en" pass. The pattern recognizers are script-agnostic and the
    #    "hi" spaCy model (xx_sent_ud_sm) has no NER component, so a single
    #    en pass covers everything the old en/hi/hi-as-en passes did.
    try:
        batch_engine = BatchAnalyzerEngine(analyzer_engine=analyzer)
        results_list = batch_engine.analyze_iterator(
            unique_texts, language="en", batch_size=spacy_batch_size
        )
        for t, text_results in zip(unique_texts, results_list):
            per_text[t].extend(text_results)
    except Exception as exc:
        logger.warning(
            "BatchAnalyzerEngine failed (%s); falling back to per-text analysis.", exc
        )
        for t in unique_texts:
            try:
                per_text[t].extend(analyzer.analyze(text=t, language="en"))
            except Exception as text_exc:
                logger.debug("Per-text analysis failed: %s", text_exc)
