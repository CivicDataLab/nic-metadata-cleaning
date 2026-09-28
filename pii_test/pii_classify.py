"""
Tier-1 classification of stored PII detections.

The detector answers "did something match here". This module answers the two
questions a reviewer actually asks, at the granularity where they can be
answered:

  Q1  Is this column really a roster of identifiable people, or personal
      contact channels?                      no  -> ``false_positive``
  Q2  If it is, are those people identified in a public-office or
      institutional capacity?                yes -> ``permissible``
                                             no  -> ``present``

Why (dataset, column) and not the individual span
-------------------------------------------------
Nothing in a span decides either question. "Rahul Kumar" is the same string
whether it names an MP or a farmer who phoned a call centre. What decides it
is the column it sits in and the dataset that column belongs to. There are
only ~7.7k such pairs behind ~55k stored detections, under ~235 distinct
headers, so the pair is both the correct unit and a far cheaper one.

Why not the confidence score
----------------------------
There is no score to threshold. 22,461 of the stored PERSON detections carry
exactly 0.85, which is Presidio's hard-coded ``SpacyRecognizer`` default, and
0.4 on PHONE_NUMBER is the weak-regex constant. Neither is a probability.
Scores are read here only as a tie-break inside an already-decided class.

Rule order, and why it is what it is
------------------------------------
Rules fire in order; the first to match decides. The order encodes three
judgements that are not arbitrary:

* **Q1 before Q2.** A column that is not personal data at all cannot be
  "permissible"; asking about publication capacity first would launder every
  crime-head list into a legal category it does not need.
* **Dataset context outranks most header role words.** In the Lok Sabha
  former-member directories the columns ``Father Name``, ``Mother Name`` and
  ``Spouse Name`` hold real relatives of real people -- and are published in
  the official member biographies under parliamentary practice. Reading those
  headers alone gives ``present``; reading them inside a directory gives
  ``permissible``, which is the right answer. This is the single most
  consequential ordering decision in the file.
* **Some header words outrank any context.** ``Beneficiary``, ``Patient``,
  ``Victim``, ``Accused`` name a private individual no matter how the dataset
  is titled, so they sit *above* the context rule. A dataset calling itself a
  directory does not make its patients public.

Deliberate non-features
-----------------------
No confidence float is emitted for rule-tier verdicts. Inventing one here
would repeat exactly the mistake that makes the detector's 0.85 useless. Each
verdict carries a ``rule_id`` and an ordinal ``rule_strength`` instead; the
``confidence`` column exists for the model and LLM tiers that follow and stays
NULL until one of them fills it.

Rules only ever move a detection towards *less* action (FP and permissible are
both quieter than present), except where a rule returns ``present``. Those are
listed explicitly in PRESENT_RULES so a future change that adds one is visible.

Usage
-----
    python pii_classify.py --test                  # self-tests, no I/O
    python pii_classify.py --snapshot DIR          # classify a parquet snapshot
    python pii_classify.py --db PATH --write       # create pii_column_class
    python pii_classify.py --csv SCAN_DIR --out classes.csv
                                                   # classify a --path scan's CSVs

``--csv`` takes what ``run_pii_s3.py --path`` writes: a folder's
``pii_detections.csv`` or a single file's ``<name>_pii_detections.csv``, or a
directory to search for them. Each scanned *file* becomes one dataset. See
load_csv for how that maps onto the DB's (uuid, lot) and what it cannot supply.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pii_filters import (  # noqa: E402
    GAZETTEER_DIR,
    classify_phone_number,
    looks_like_person_name,
    normalize_entity_text,
    _median,
    _read_name_file,
)
from pii_utils import classify_column_name, normalize_column_tokens  # noqa: E402

# The public office-holder allow-list, built by
# build_public_office_gazetteer.py. Absent until that has been run, in which
# case R6 is simply inert -- every other rule is unaffected.
PUBLIC_OFFICE_PATH = os.path.join(GAZETTEER_DIR, "public_office_holders.txt")
PUBLIC_OFFICE_HOLDERS = frozenset(
    normalize_entity_text(line)
    for line in _read_name_file(
        PUBLIC_OFFICE_PATH,
        "public office holders will not be recognised. Run: "
        "python pii_test/build_public_office_gazetteer.py --all"))

# A single match decides nothing: "Ram Singh" is an MP and several hundred
# thousand other people. A share of the column's distinct values has to match
# before the column reads as a roster of office holders, and a column with
# only one or two distinct values cannot clear that bar meaningfully.
PUBLIC_OFFICE_MATCH_RATE = 0.30
PUBLIC_OFFICE_MIN_MATCHES = 3

CLASSES = ("false_positive", "permissible", "present", "undecided")
ROLES = ("not_person", "public_office", "org_contact",
         "private_individual", "personal_contact", "unknown")

# Rules whose verdict is "present". Any addition here widens what the pipeline
# treats as a live privacy problem, so the set is written out rather than
# derived, and the self-tests assert its contents.
PRESENT_RULES = ("R5-private-absolute", "R9-private-contextual",
                 "R10-individual-records", "R11-personal-channel")


# --------------------------------------------------------------------------
# Header vocabularies
# --------------------------------------------------------------------------

# Controlled vocabularies that classify_column_name does not already skip.
# Every entry was read off the stored detection table: these headers hold a
# closed list of categories, never people. Kept separate from
# pii_utils.SKIP_COLUMN_TOKENS because that set governs *whether to scan* and
# is load-bearing for the live pipeline; this one only governs how an
# already-stored detection is read, so it can be extended without
# invalidating any scan.
CONTROLLED_VOCABULARY_TOKENS = {
    # census / NCRB / statistical row labels.
    #
    # "head" is deliberately absent. It is the person word in "Name of
    # Vice-Chancellor/Director/Principal/Head" and the category word in
    # "Crime Head" and "Budget Head", and pii_utils.NEGATIVE_PERSON_BIGRAMS
    # already resolves that pair-by-pair. Listing it here would classify the
    # vice-chancellor column as a controlled vocabulary. "crime" carries the
    # NCRB case on its own.
    "indicator", "indicators", "crime", "cause", "causes",
    "characteristic", "characteristics", "variable", "particular",
    "particulars", "item", "items", "nco", "occupation", "occupations",
    # infrastructure and geography names read as people
    "route", "routes", "station", "stations", "waterbody", "basin",
    "habitation", "habitations", "settlement", "locality",
    # goods and biology
    "product", "products", "crop", "crops", "species", "breed", "variety",
    "cargo", "commodity", "commodities",
    # aviation / finance table labels
    "cpse", "enterprise", "enterprises", "airline", "carrier",
}

# Free-text columns. A detection here is a span cut out of prose, not the
# cell's value, so a mobile number or personal email inside one is a real
# leak even when the column header says nothing about people.
FREE_TEXT_TOKENS = {
    "answer", "ans", "question", "query", "remark", "remarks", "comment",
    "comments", "note", "notes", "detail", "details", "description",
    "abstract", "summary", "text", "feedback", "complaint", "grievance",
    "faq", "faqanswer", "response", "narrative",
}

# Office-holder words. A person named in one of these columns is named in a
# public capacity: DPDP Act 2023 s.3(c)(ii) puts personal data published under
# a legal obligation outside the Act, and office-bearer directories are
# published under exactly such obligations.
PUBLIC_OFFICE_TOKENS = {
    "mp", "mla", "mlc", "minister", "chairman", "chairperson", "chair",
    "vicechancellor", "chancellor", "registrar", "commissioner",
    "cpio", "apio", "pio", "nodal", "incharge", "hod", "dean", "warden",
    "sarpanch", "pradhan", "mayor", "collector", "magistrate", "speaker",
    "governor", "ambassador", "judge", "justice", "mayor",
}

# Weaker office words: real in a directory, ambiguous elsewhere. "Director"
# heads an institute and also a private company; "Officer" appears in both
# staff lists and beneficiary tables. These need the dataset to agree.
WEAK_OFFICE_TOKENS = {
    "director", "principal", "secretary", "officer", "official", "head",
    "president", "member", "representative", "authority", "coordinator",
}

# Private-individual words that no dataset title can override. A patient is a
# patient in a table calling itself a directory.
PRIVATE_ABSOLUTE_TOKENS = {
    "beneficiary", "beneficiaries", "patient", "victim", "accused",
    "complainant", "deceased", "borrower", "applicant", "candidate",
    "prisoner", "inmate", "orphan", "widow", "migrant", "labourer",
}

# Private-individual words that a genuine official directory does override --
# the relatives named in a parliamentary member biography are published with
# the member's own record.
PRIVATE_CONTEXTUAL_TOKENS = {
    "father", "mother", "spouse", "husband", "wife", "guardian", "parent",
    "child", "children", "son", "daughter", "student", "pupil", "farmer",
    "worker", "resident", "household", "respondent", "customer",
    "subscriber", "tenant", "trainee", "employee", "staff",
}

# Quasi-identifier headers. Two or more of these among a dataset's other
# detected columns means the table describes individuals, whatever any single
# header says. Only a partial view from the DB: siblings there are derived from
# columns that produced detections, so a clean sibling is invisible (see
# derive_sibling_headers). A --csv run reads the real header row and sees all.
QUASI_IDENTIFIER_TOKENS = {
    "age", "gender", "sex", "caste", "religion", "income", "disease",
    "diagnosis", "aadhaar", "aadhar", "bank", "account", "village",
    "house", "household", "scheme", "disability", "marital", "pregnancy",
    "vaccination", "treatment",
}

# Things that get named in a "Name of ..." column and are not people. Without
# these, any column whose header contains "name" reads as a person column, and
# "Name of the Monument" convicts a heritage list. Observation-driven, like the
# gazetteers: extended as the corpus turns up more, never guessed at.
NON_PERSON_SUBJECT_TOKENS = {
    "monument", "site", "sites", "facility", "facilities", "port", "ports",
    "hotel", "hotels", "pipeline", "park", "building", "temple", "fort",
    "dam", "reservoir", "lake", "river", "canal", "forest", "sanctuary",
    "museum", "airport", "terminal", "depot", "warehouse", "mine", "plant",
    "body", "bodies", "website", "url", "link", "portal", "domain",
    "parameter", "parameters", "parametar", "parametars", "theme", "topic",
    "act", "rule", "policy", "drug", "drugs", "property", "asset",
}

# Headers that mark a dataset as an office-bearer or member biography,
# whatever its title says. Two or more of these among a dataset's columns is
# a schema no survey has.
#
# This exists because six LOT 1 datasets carry the Lok Sabha current-member
# directory (Current_mem_Eng_nov_2017.csv) under the catalogue title "Data
# Item Comparison Report of Sikkim for 2014-2015 and 2013-2014". The title and
# the file disagree in the source catalogue, so title-derived context is wrong
# for exactly the datasets where getting it right matters most. The column
# schema comes from the file itself and cannot drift from it.
DIRECTORY_SCHEMA_MARKERS = {
    "position", "positions", "constituency", "party", "tenure", "portfolio",
    "publication", "publications", "book", "books", "profession",
    "professions", "achievement", "achievements", "biography", "elected",
    "term", "ministry", "office", "designation",
}

ADDRESS_TOKENS = {"address", "addr", "residence", "domicile"}

INSTITUTIONAL_EMAIL_SUFFIXES = (
    ".gov.in", ".nic.in", ".ac.in", ".edu.in", ".res.in", ".org.in",
    "@gov.in", "@nic.in",
)

# --------------------------------------------------------------------------
# Dataset context patterns
# --------------------------------------------------------------------------

_DIRECTORY_RE = re.compile(
    r"\b(director(y|ies)|who\s*'?s\s*who|office\s+bearer|list\s+of\s+"
    r"(officer|official|member|minister|employee|faculty|staff)|"
    r"members?\s+of\s+(parliament|rajya|lok|assembly|council)|"
    r"(former|current|sitting)\s+members?|contact\s+(detail|list|director)|"
    r"nodal\s+officer|cpio|public\s+information\s+officer|rti|"
    r"awardee|award\s+winner|recipients?\s+of|padma|"
    r"vice[-\s]?chancellor|telephone\s+director)", re.IGNORECASE)

_INDIVIDUAL_RE = re.compile(
    r"\b(survey|schedule|beneficiar|applicant|enrol|enrol?lment|registration|"
    r"call\s*cent(re|er)|transcript|kisan\s+call|complaint|grievance|"
    r"patient|household|houselist|respondent|individual\s+record|"
    r"pension(er)?s?\s+list|ration\s+card|job\s+card|scholarship|"
    r"admission|candidate\s+list|voter)", re.IGNORECASE)

_AGGREGATE_RE = re.compile(
    r"\b(performance|statistic|number\s+of|distribution|classification|"
    r"amenit|traffic|consumption|incidence|production|area\s+under|"
    r"year[-\s]wise|state[-\s]wise|district[-\s]wise|total\s+|"
    r"annual\s+report|comparative\s+statement|census|indicator)",
    re.IGNORECASE)

CONTEXTS = ("official_directory", "individual_records",
            "aggregate_statistics", "unknown")


def dataset_context(title, catalog_title=None, description=None):
    """Classify a dataset by what kind of thing its rows are.

    Returns ``(context, reason)``. The directory and individual-record tests
    run before the aggregate test because an aggregate word is common in both
    ("Annual Report of Members ..."), while the reverse is rare.
    """
    blob = " ".join(str(p) for p in (title, catalog_title, description) if p)
    if not blob.strip():
        return "unknown", "no title"

    directory = _DIRECTORY_RE.search(blob)
    individual = _INDIVIDUAL_RE.search(blob)
    if directory and not individual:
        return "official_directory", f"title matches {directory.group(0)!r}"
    if individual and not directory:
        return "individual_records", f"title matches {individual.group(0)!r}"
    if directory and individual:
        # Both fired: a beneficiary list published as a "directory". The
        # individual reading is the safer of the two.
        return "individual_records", (
            f"title matches both {directory.group(0)!r} and "
            f"{individual.group(0)!r}; taking the individual reading")

    aggregate = _AGGREGATE_RE.search(blob)
    if aggregate:
        return "aggregate_statistics", f"title matches {aggregate.group(0)!r}"
    return "unknown", "no context pattern"


SCHEMA_MARKER_MINIMUM = 2


def schema_context(headers):
    """Context read off the dataset's column schema, or ``(None, reason)``.

    The schema comes from the scanned file; the title comes from the
    catalogue, and in this corpus the two can disagree outright. Where the
    schema speaks, it outranks the title -- see DIRECTORY_SCHEMA_MARKERS.
    """
    tokens = set()
    for header in headers:
        tokens |= header_tokens(header)
    markers = sorted(tokens & DIRECTORY_SCHEMA_MARKERS)
    if len(markers) >= SCHEMA_MARKER_MINIMUM and (tokens & {"name", "member"}):
        return "official_directory", (
            f"column schema carries office-bearer markers "
            f"{', '.join(markers[:4])}")
    return None, "no schema signal"


# --------------------------------------------------------------------------
# Header helpers
# --------------------------------------------------------------------------

def header_tokens(column):
    """Lowercase tokens of a header, plus naive singulars."""
    raw = normalize_column_tokens(column)
    tokens = set(raw)
    for t in raw:
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            tokens.add(t[:-1])
    # Headers written without separators ("fathername", "waterbodyname").
    if len(raw) == 1 and len(raw[0]) >= 8:
        glued = raw[0]
        for vocab in (PUBLIC_OFFICE_TOKENS, PRIVATE_ABSOLUTE_TOKENS,
                      PRIVATE_CONTEXTUAL_TOKENS, CONTROLLED_VOCABULARY_TOKENS,
                      FREE_TEXT_TOKENS, WEAK_OFFICE_TOKENS):
            tokens.update(v for v in vocab if len(v) >= 5 and v in glued)
    return tokens


def _hit(tokens, vocab):
    """First matching token, alphabetically, or None. Stable for reasons."""
    common = tokens & vocab
    return sorted(common)[0] if common else None


def email_domain_class(values):
    """"institutional", "mixed", "consumer" or None for a set of emails."""
    emails = [v for v in values if "@" in str(v)]
    if not emails:
        return None
    institutional = sum(
        1 for e in emails
        if any(str(e).lower().rstrip(">.,;").endswith(s)
               or s in str(e).lower()
               for s in INSTITUTIONAL_EMAIL_SUFFIXES))
    if institutional == len(emails):
        return "institutional"
    if institutional:
        return "mixed"
    return "consumer"


# --------------------------------------------------------------------------
# Feature extraction
# --------------------------------------------------------------------------

def corpus_frequency_index(all_detections):
    """Map normalized PERSON value -> number of distinct datasets holding it.

    Computed over the snapshot rather than read from
    ``gazetteer/cross_dataset_common.txt``. The file is built from post-filter
    detections that were themselves produced using the file, so it can only
    ever grow; computing here at least keeps the count current with the table
    being classified. It is still the same feedback loop and is used only as
    one of three Q1 tests, never alone.
    """
    seen = defaultdict(set)
    for d in all_detections:
        if d["entity_type"] != "PERSON":
            continue
        key = normalize_entity_text(d["entity_text"])
        if key:
            seen[key].add(d["uuid"])
    return {k: len(v) for k, v in seen.items()}


def derive_sibling_headers(all_detections, metadata=None):
    """Map uuid -> the dataset's headers, as far as they are known.

    The DB does not persist the header row, so there the set is only the
    columns that produced a detection -- strictly a subset, in which a clean
    column is invisible and the absence of a quasi-identifier sibling proves
    nothing. Rules therefore only ever read this set positively.

    Where ``metadata`` carries the real header row (a --csv run reads it off
    the scanned file), it is added. That matters most for directories whose
    descriptive columns are in a script the detector does not read: the Hindi
    Lok Sabha member lists share the English lists' schema, but their
    ``Hobbies`` and ``Activity(s)`` columns produce no detections, so the
    detected-only view misses the directory the English lists are read as.
    """
    siblings = defaultdict(set)
    for d in all_detections:
        siblings[d["uuid"]].add(d["column"])
    for uuid, meta in (metadata or {}).items():
        if uuid in siblings and meta.get("headers"):
            siblings[uuid].update(meta["headers"])
    return siblings


def column_features(detections, frequency_index, siblings=()):
    """Aggregate one (dataset, column) group into the features rules read."""
    values = [d["entity_text"] for d in detections]
    distinct = list(dict.fromkeys(values))
    types = sorted({d["entity_type"] for d in detections})

    persons = [d for d in detections if d["entity_type"] == "PERSON"]
    person_distinct = list(dict.fromkeys(d["entity_text"] for d in persons))
    phones = [d for d in detections if d["entity_type"] == "PHONE_NUMBER"]
    emails = [d for d in detections if d["entity_type"] == "EMAIL_ADDRESS"]

    name_shaped = (
        sum(1 for v in person_distinct if looks_like_person_name(v))
        / len(person_distinct)) if person_distinct else None
    office_matches = sum(1 for v in person_distinct
                         if normalize_entity_text(v) in PUBLIC_OFFICE_HOLDERS)
    median_frequency = _median(
        [frequency_index.get(normalize_entity_text(v), 1)
         for v in person_distinct]) if person_distinct else None

    phone_kinds = Counter(
        classify_phone_number(d["entity_text"]) or "not-a-number"
        for d in phones)

    cardinalities = [d["cardinality"] for d in detections
                     if d.get("cardinality") is not None]

    sibling_tokens = set()
    for header in siblings:
        sibling_tokens |= header_tokens(header)

    return {
        "column": detections[0]["column"],
        "entity_types": types,
        "n_detections": len(detections),
        "n_distinct": len(distinct),
        "n_person_distinct": len(person_distinct),
        "name_shaped_fraction": name_shaped,
        "median_corpus_frequency": median_frequency,
        "cardinality": (sum(cardinalities) / len(cardinalities)
                        if cardinalities else None),
        "office_holder_matches": office_matches,
        "office_holder_match_rate": (office_matches / len(person_distinct)
                                     if person_distinct else None),
        "phone_kinds": dict(phone_kinds),
        "phone_values_look_dialled": bool(phones) and all(
            _looks_like_a_dialled_number(d["entity_text"]) for d in phones),
        "email_domain_class": email_domain_class(
            d["entity_text"] for d in emails),
        "has_regex_source": any(d.get("source") == "regex" for d in detections),
        "sample_values": distinct[:15],
        "sibling_quasi_identifiers": sorted(
            sibling_tokens & QUASI_IDENTIFIER_TOKENS),
    }


# --------------------------------------------------------------------------
# Q1 helpers
# --------------------------------------------------------------------------

NAME_SHAPE_FLOOR = 0.5
CARDINALITY_FLOOR = 0.5

# Corpus frequency alone does not reject a column, and this is the correction
# that matters most in the file.
#
# Measured over the stored table: the columns known to hold real people
# (the parliamentary member directories) sit at a median frequency of exactly
# 6, because the same directory is published six times -- across years and in
# both languages -- and every member therefore appears in six "different"
# datasets. Columns that really are controlled vocabularies sit at a median of
# 17 with a 90th percentile of 90. The two ranges overlap, so no threshold on
# frequency alone separates them, and the threshold that ``evaluate_dataset_flag``
# uses for flagging (> 1) rejects the genuine directories outright.
#
# Frequency therefore only rejects when the values are also less than
# uniformly name-shaped. A column that is 100% name-shaped and highly
# distinct is left for the later tiers rather than dismissed here.
FREQUENCY_FP_FLOOR = 10
FREQUENCY_NAME_SHAPE_CEILING = 0.9


def person_column_is_real(feat):
    """Q1 for the PERSON detections of a column: ``(bool|None, reason)``.

    ``None`` means undecidable from shape alone, which is a real answer here:
    it routes the column to the later tiers instead of convicting it.
    """
    if not feat["n_person_distinct"]:
        return None, "no PERSON detections"

    shape = feat["name_shaped_fraction"]
    if shape is not None and shape < NAME_SHAPE_FLOOR:
        return False, f"{shape:.0%} of distinct values are name-shaped"
    if feat["cardinality"] is not None and feat["cardinality"] <= CARDINALITY_FLOOR:
        return False, f"cardinality {feat['cardinality']:.2f}"

    frequency = feat["median_corpus_frequency"]
    if frequency is not None and frequency > FREQUENCY_FP_FLOOR:
        if shape is not None and shape < FREQUENCY_NAME_SHAPE_CEILING:
            return False, (f"median value appears in {frequency:g} datasets "
                           f"and only {shape:.0%} of values are name-shaped")
        return None, (f"median value appears in {frequency:g} datasets, but "
                      f"{shape:.0%} of values are name-shaped")
    return True, "name-shaped, corpus-rare"


def _looks_like_a_dialled_number(value):
    """Whether a phone match is written the way a number is written.

    ``classify_phone_number`` reads a digit run against the national numbering
    plan, and a bare integer can satisfy it by accident: the toll-free prefix
    test matches any run starting 180, which is how "Aggregate
    Evapotranspiration Volume" and "ELEPHANT POPULATION IN 2007" became
    published helplines. A real number carries a separator, a country code or
    a trunk zero; an aggregate is a naked digit run.
    """
    text = str(value or "").strip()
    if any(ch in text for ch in "+-() ") or text.startswith("0"):
        return True
    return len(re.sub(r"\D", "", text)) == 10


def contacts_are_real(feat, header_has_contact_token=False):
    """Q1 for PHONE/EMAIL: ``(bool|None, reason)``."""
    kinds = feat["phone_kinds"]
    has_email = feat["email_domain_class"] is not None
    if not kinds and not has_email:
        return None, "no contact detections"
    if has_email:
        return True, "email address present"

    real_kinds = kinds.keys() - {"not-a-number"}
    if not real_kinds:
        return False, "no phone match fits the national numbering plan"
    if not feat["phone_values_look_dialled"] and not header_has_contact_token:
        return False, ("phone matches are bare digit runs in a column whose "
                       "header names no contact channel")
    return True, "contact channel present"


def column_signal(column, feat):
    """What the column itself says it holds: "contact", "person" or None.

    The context rules (R6, R9) may only convict a column that shows one of
    these. Dataset context says what the *rows* are; it cannot say that a
    particular column is about people, and letting it try is what labelled
    "Name of the Monument" and "Depth range (m)" as personal data.
    """
    tokens = header_tokens(column)
    decision, _ = classify_column_name(column)
    if decision == "force-pii":
        return "contact"
    if decision == "force-person":
        return "person"
    if tokens & NON_PERSON_SUBJECT_TOKENS or tokens & CONTROLLED_VOCABULARY_TOKENS:
        return None
    if "name" in tokens:
        return "person"
    # An address is personal data in its own right, and the header carries no
    # "name" or contact token to say so. In a directory this makes the MP's
    # listed address permissible; in a survey it makes a respondent's address
    # present. Both are decided by the context rules below, not here.
    if tokens & ADDRESS_TOKENS:
        return "contact"
    if feat["email_domain_class"] is not None or feat["phone_kinds"]:
        return "contact"
    return None


# --------------------------------------------------------------------------
# The rule cascade
# --------------------------------------------------------------------------

def classify_pair(feat, context, context_reason=""):
    """Apply the Tier-1 cascade to one (dataset, column) pair.

    Returns a dict with ``pii_class``, ``role``, ``rule_id``,
    ``rule_strength`` and ``reason``. The first matching rule decides.
    """
    tokens = header_tokens(feat["column"])

    def verdict(pii_class, role, rule_id, strength, reason):
        return {"pii_class": pii_class, "role": role, "rule_id": rule_id,
                "rule_strength": strength, "reason": reason}

    # ---- Q1: is this personal data at all? --------------------------------
    decision, why = classify_column_name(feat["column"])
    if decision == "skip":
        return verdict("false_positive", "not_person", "R1-skip-header",
                       "high", f"header is a non-PII column: {why}")

    vocab_hit = _hit(tokens, CONTROLLED_VOCABULARY_TOKENS)
    person_only = feat["entity_types"] == ["PERSON"]
    if vocab_hit and person_only:
        return verdict("false_positive", "not_person", "R1-controlled-vocab",
                       "high",
                       f"header token {vocab_hit!r} marks a controlled "
                       f"vocabulary, and only PERSON was detected")

    decision_is_contact = decision == "force-pii"
    person_real, person_why = person_column_is_real(feat)
    contact_real, contact_why = contacts_are_real(feat, decision_is_contact)

    if person_real is False and contact_real is not True:
        return verdict("false_positive", "not_person", "R2-column-shape",
                       "high", f"PERSON values rejected: {person_why}")
    if person_real is not True and contact_real is False:
        return verdict("false_positive", "not_person", "R3-not-a-number",
                       "high", contact_why)

    # ---- Q2: permissible or present? --------------------------------------
    signal = column_signal(feat["column"], feat)
    if signal is None:
        return verdict("undecided", "unknown", "R12-residual", "none",
                       f"no person or contact signal in the header; dataset "
                       f"context ({context}) alone cannot convict a column")

    kinds = feat["phone_kinds"]
    institutional_phone = bool(kinds) and not (
        kinds.keys() - {"institutional", "landline", "not-a-number"})
    institutional_email = feat["email_domain_class"] == "institutional"
    contacts_only = person_real is not True

    if contacts_only and (institutional_phone or institutional_email) \
            and not (kinds.keys() & {"mobile"}):
        channel = "toll-free/landline" if institutional_phone else "institutional domain"
        return verdict("permissible", "org_contact", "R4-institutional-channel",
                       "high",
                       f"every contact value is an office channel ({channel})")

    absolute = _hit(tokens, PRIVATE_ABSOLUTE_TOKENS)
    if absolute:
        return verdict("present", "private_individual", "R5-private-absolute",
                       "high",
                       f"header token {absolute!r} names a private individual "
                       f"regardless of dataset context")

    matches = feat["office_holder_matches"]
    match_rate = feat["office_holder_match_rate"]
    if matches >= PUBLIC_OFFICE_MIN_MATCHES \
            and match_rate >= PUBLIC_OFFICE_MATCH_RATE:
        return verdict("permissible", "public_office", "R6-office-allowlist",
                       "high",
                       f"{match_rate:.0%} of this column's distinct values "
                       f"({matches}) are known public office holders")

    if context == "official_directory":
        return verdict("permissible", "public_office", "R7-directory-context",
                       "medium",
                       f"dataset is an office-bearer directory "
                       f"({context_reason})")

    office = _hit(tokens, PUBLIC_OFFICE_TOKENS)
    if office:
        return verdict("permissible", "public_office", "R8-office-header",
                       "high",
                       f"header token {office!r} names a public office holder")

    contextual = _hit(tokens, PRIVATE_CONTEXTUAL_TOKENS)
    if contextual:
        return verdict("present", "private_individual", "R9-private-contextual",
                       "high",
                       f"header token {contextual!r} names a private "
                       f"individual, and the dataset is not a directory")

    if context == "individual_records":
        return verdict("present", "private_individual", "R10-individual-records",
                       "medium",
                       f"dataset holds individual records ({context_reason})")

    free_text = _hit(tokens, FREE_TEXT_TOKENS)
    personal_channel = ("mobile" in kinds) or \
        (feat["email_domain_class"] in ("consumer", "mixed"))
    if personal_channel:
        where = f"free-text column ({free_text!r})" if free_text else "column"
        return verdict("present", "personal_contact", "R11-personal-channel",
                       "high",
                       f"subscriber mobile or personal email address in this "
                       f"{where}")

    weak_office = _hit(tokens, WEAK_OFFICE_TOKENS)
    hint = f"; header token {weak_office!r} hints at an office" if weak_office else ""
    quasi = feat["sibling_quasi_identifiers"]
    if quasi:
        hint += f"; sibling columns include {', '.join(quasi[:3])}"
    return verdict("undecided", "unknown", "R12-residual", "none",
                   f"real names in a {context} dataset with no role "
                   f"signal in the header{hint}")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def classify_detections(detections, metadata):
    """Classify every (uuid, lot, column) group.

    ``detections`` is a list of dicts with uuid, lot, column, entity_type,
    entity_text, score, source and optionally cardinality. ``metadata`` maps
    uuid -> dict with title, catalog_title, description.
    """
    frequency_index = corpus_frequency_index(detections)
    siblings = derive_sibling_headers(detections, metadata)

    groups = defaultdict(list)
    for d in detections:
        groups[(d["uuid"], d["lot"], d["column"])].append(d)

    contexts = {}
    rows = []
    for (uuid, lot, column), group in sorted(groups.items()):
        meta = metadata.get(uuid, {})
        if uuid not in contexts:
            from_title = dataset_context(
                meta.get("title"), meta.get("catalog_title"),
                meta.get("description"))
            from_schema, schema_reason = schema_context(siblings[uuid])
            # The schema is read from the file; the title is read from the
            # catalogue, and the two demonstrably disagree in this corpus.
            # Where the schema speaks, it wins.
            contexts[uuid] = ((from_schema, schema_reason) if from_schema
                              else from_title)
        context, context_reason = contexts[uuid]

        others = siblings[uuid] - {column}
        feat = column_features(group, frequency_index, others)
        result = classify_pair(feat, context, context_reason)

        rows.append({
            "uuid": uuid,
            "lot": lot,
            "column": column,
            "entity_types": ",".join(feat["entity_types"]),
            "n_detections": feat["n_detections"],
            "n_distinct": feat["n_distinct"],
            "pii_class": result["pii_class"],
            "role": result["role"],
            "confidence": None,          # model/LLM tiers only -- see module docstring
            "tier": "rule",
            "rule_id": result["rule_id"],
            "rule_strength": result["rule_strength"],
            "reason": result["reason"],
            "dataset_context": context,
            "evidence_json": json.dumps({
                "name_shaped_fraction": feat["name_shaped_fraction"],
                "median_corpus_frequency": feat["median_corpus_frequency"],
                "cardinality": feat["cardinality"],
                "phone_kinds": feat["phone_kinds"],
                "email_domain_class": feat["email_domain_class"],
                "sibling_quasi_identifiers": feat["sibling_quasi_identifiers"],
                "sample_values": feat["sample_values"],
                "context_reason": context_reason,
            }, ensure_ascii=False),
            "classified_at": datetime.now(),
        })
    return rows


DDL = """
CREATE TABLE IF NOT EXISTS pii_column_class (
    uuid            VARCHAR,
    lot             INTEGER,
    "column"        VARCHAR,
    entity_types    VARCHAR,
    n_detections    INTEGER,
    n_distinct      INTEGER,
    pii_class       VARCHAR,
    role            VARCHAR,
    confidence      DOUBLE,
    tier            VARCHAR,
    rule_id         VARCHAR,
    rule_strength   VARCHAR,
    reason          VARCHAR,
    dataset_context VARCHAR,
    evidence_json   VARCHAR,
    classified_at   TIMESTAMP
);
"""

# Dataset roll-up. A view, not a table, so it can never disagree with the
# column verdicts it summarises. present > permissible > undecided >
# false_positive: the loudest column decides the dataset.
VIEW_DDL = """
CREATE OR REPLACE VIEW pii_dataset_class AS
SELECT uuid, lot,
       CASE WHEN sum(CASE WHEN pii_class='present'        THEN 1 ELSE 0 END) > 0
                 THEN 'present'
            WHEN sum(CASE WHEN pii_class='permissible'    THEN 1 ELSE 0 END) > 0
                 THEN 'permissible'
            WHEN sum(CASE WHEN pii_class='undecided'      THEN 1 ELSE 0 END) > 0
                 THEN 'undecided'
            ELSE 'false_positive' END           AS pii_class,
       count(*)                                  AS n_columns,
       sum(n_detections)                         AS n_detections,
       string_agg(DISTINCT rule_id, ',')         AS rule_ids,
       any_value(dataset_context)                AS dataset_context
FROM pii_column_class
GROUP BY uuid, lot;
"""

# Loudest first; the order VIEW_DDL's CASE encodes.
DATASET_CLASS_ORDER = ("present", "permissible", "undecided", "false_positive")


def rollup_datasets(rows):
    """The pii_dataset_class view, for runs that never touch the DB.

    Must agree with VIEW_DDL: the loudest column decides the dataset.
    """
    groups = defaultdict(list)
    for r in rows:
        groups[(r["uuid"], r["lot"])].append(r)
    out = []
    for (uuid, lot), group in sorted(groups.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        classes = {r["pii_class"] for r in group}
        out.append({
            "uuid": uuid,
            "lot": lot,
            "pii_class": next(c for c in DATASET_CLASS_ORDER if c in classes),
            "n_columns": len(group),
            "n_detections": sum(int(r["n_detections"]) for r in group),
            "rule_ids": ",".join(sorted({str(r["rule_id"]) for r in group})),
            "dataset_context": group[0]["dataset_context"],
        })
    return out


def load_snapshot(directory):
    """Read the parquet snapshot written by the --snapshot export."""
    import duckdb
    con = duckdb.connect()
    detections, metadata = [], {}
    for lot in (1, 2):
        det_path = os.path.join(directory, f"det_lot{lot}.parquet")
        meta_path = os.path.join(directory, f"meta_lot{lot}.parquet")
        if not os.path.exists(det_path):
            continue
        cardinality = "cardinality" if lot == 1 else "NULL AS cardinality"
        for row in con.execute(
                f'SELECT uuid, "column", entity_type, entity_text, score, '
                f"source, {cardinality} FROM '{det_path}'").fetchall():
            detections.append({
                "uuid": row[0], "lot": lot, "column": row[1],
                "entity_type": row[2], "entity_text": row[3],
                "score": row[4], "source": row[5], "cardinality": row[6],
            })
        if os.path.exists(meta_path):
            for row in con.execute(
                    f"SELECT uuid, title, catalog_title, descr "
                    f"FROM '{meta_path}'").fetchall():
                metadata[row[0]] = {"title": row[1], "catalog_title": row[2],
                                    "description": row[3]}
    con.close()
    return detections, metadata


# What run_pii_s3.py --path writes. Duplicated rather than imported: importing
# run_pii_s3 pulls in torch, boto3 and presidio, and repoints the root logger.
FOLDER_DETECTIONS_NAME = "pii_detections.csv"     # run_pii_s3.FOLDER_DETECTIONS_FILENAME
SINGLE_FILE_SUFFIX = "_pii_detections.csv"
SOURCE_EXTENSIONS = (".csv", ".xls", ".xlsx")     # run_pii_s3.TABULAR_EXTENSIONS
# A scanned file is in neither lot, and pii_column_class.lot is an INTEGER.
CSV_LOT = 0
# data.gov.in resource ids, which is how S3-downloaded files are named.
UUID_STEM = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def find_detection_csvs(paths):
    """Expand files and directories into the detection CSVs they hold."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            for dirpath, _, filenames in sorted(os.walk(path)):
                for name in sorted(filenames):
                    if name == FOLDER_DETECTIONS_NAME or name.endswith(SINGLE_FILE_SUFFIX):
                        found.append(os.path.join(dirpath, name))
        elif os.path.isfile(path):
            found.append(path)
        else:
            raise FileNotFoundError(path)
    return found


def read_header_row(path):
    """The source file's header row, or None if it cannot be read.

    Tier 1 adds it to the detected columns its schema and quasi-identifier
    rules read, and Tier 3 shows it to the judge in place of the ``Conforms
    To`` header row the catalog supplies for DB datasets.
    """
    try:
        if os.path.splitext(path)[1].lower() in (".xls", ".xlsx"):
            import pandas as pd
            headers = list(pd.read_excel(path, nrows=0).columns)
        else:
            import csv
            headers = None
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    with open(path, newline="", encoding=encoding) as handle:
                        headers = next(csv.reader(handle), [])
                    break
                except UnicodeDecodeError:
                    continue
        return [str(h).strip() for h in headers or [] if str(h).strip()] or None
    except Exception:                                  # noqa: BLE001
        return None


def load_csv(paths):
    """Read the detection CSVs a ``run_pii_s3.py --path`` run writes.

    Returns (detections, metadata), the same shapes load_from_db returns.

    * **One scanned file is one dataset.** The ``uuid`` field keeps its name
      for pii_column_class, but here it is a file key, not a data.gov.in id:
      the file's path relative to the common parent of ``paths``, whatever the
      file is called -- ``KERALA/2023_Q4.csv``, ``msme - assam.csv`` or
      ``<uuid>.csv`` alike. The folder stays in the key because quarterly
      exports reuse the same names in every folder, and a bare stem would
      merge them into one dataset.
    * **A descriptive file name is the title; a UUID-shaped one is not.**
      ``msme - assam`` tells the rules and the judge what the dataset is;
      ``3b1f...`` only adds noise to the prompt, so it gives no title. The
      folder is never the title: the test corpus encodes the expected answer
      in folder names (pii-present, pii-false-postive), and handing that to
      the rules or the Tier 3 prompt would leak it.
    * **The real header row is read.** Tier 1 adds it to the detected columns
      (see derive_sibling_headers) and Tier 3 shows it to the judge.
    * **No cardinality, no catalog title or description.** The folder CSVs
      do not store them. That matches LOT 2, whose detections also carry no
      cardinality, so the same rules apply with the same blind spots.
    """
    import csv
    files = find_detection_csvs(paths)
    roots = [os.path.abspath(p if os.path.isdir(p) else os.path.dirname(p) or ".")
             for p in paths]
    root = os.path.commonpath(roots)

    detections, metadata = [], {}
    for det_path in files:
        folder = os.path.dirname(os.path.abspath(det_path))
        with open(det_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            missing = {"column", "entity_type", "entity_text"} - fields
            if missing or not fields & {"file", "uuid"}:
                hint = (" -- this looks like a --summary-out file; pass the "
                        "scanned folder or its pii_detections.csv instead"
                        if "pii_found" in fields else "")
                raise ValueError(
                    f"{det_path} is not a detections CSV (missing "
                    f"{', '.join(sorted(missing)) or 'file/uuid'}){hint}")
            for row in reader:
                source = _source_path(folder, row)
                uuid = os.path.relpath(source, root).replace(os.sep, "/")
                if uuid not in metadata:
                    stem = os.path.splitext(os.path.basename(source))[0]
                    metadata[uuid] = {
                        "title": None if UUID_STEM.match(stem) else stem,
                        "catalog_title": None,
                        "description": None,
                        "source_file": source,
                        "headers": read_header_row(source),
                    }
                score = row.get("score")
                detections.append({
                    "uuid": uuid, "lot": CSV_LOT, "column": row["column"],
                    "entity_type": row["entity_type"],
                    "entity_text": row["entity_text"],
                    "score": float(score) if score not in (None, "") else None,
                    "source": row.get("source"), "cardinality": None,
                })
    return detections, metadata


def _source_path(folder, row):
    """The scanned file a detection row came from.

    Folder runs record it in ``file``. Single-file runs record only the stem
    in ``uuid``, so the extension is recovered from whatever sits beside the
    detections file.
    """
    if row.get("file"):
        return os.path.join(folder, row["file"])
    stem = os.path.join(folder, row["uuid"])
    for ext in SOURCE_EXTENSIONS:
        if os.path.exists(stem + ext):
            return stem + ext
    return stem


def with_file_context(rows, metadata):
    """Add the columns a --csv run carries through to Tier 3.

    ``source_file``, ``title`` and ``file_headers`` (a JSON list) are what
    pii_tier3 reads from the DB's metadata tables otherwise.
    """
    out = []
    for r in rows:
        meta = metadata.get(r["uuid"], {})
        headers = meta.get("headers")
        out.append({**r,
                    "source_file": meta.get("source_file"),
                    "title": meta.get("title"),
                    "file_headers": json.dumps(headers, ensure_ascii=False) if headers else ""})
    return out


def write_rows_csv(path, rows):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_to_db(db_path, rows, replace=True):
    """Create pii_column_class and load rows. Needs the DuckDB write lock."""
    import duckdb
    try:
        con = duckdb.connect(db_path)
    except duckdb.IOException as exc:
        raise SystemExit(
            f"cannot open {db_path} for writing: {exc}\n"
            "A scan is probably holding the single writer lock. "
            "Re-run when it finishes; the --snapshot output is unaffected."
        ) from exc

    con.execute(DDL)
    if replace:
        con.execute("DELETE FROM pii_column_class")
    con.executemany(
        "INSERT INTO pii_column_class VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["uuid"], r["lot"], r["column"], r["entity_types"],
          r["n_detections"], r["n_distinct"], r["pii_class"], r["role"],
          r["confidence"], r["tier"], r["rule_id"], r["rule_strength"],
          r["reason"], r["dataset_context"], r["evidence_json"],
          r["classified_at"]) for r in rows])
    con.execute(VIEW_DDL)
    con.close()


def summarise(rows):
    """Text report of the class distribution, by rule and by context."""
    out = []
    total = len(rows)
    out.append(f"{total} (dataset, column) pairs classified\n")

    by_class = Counter(r["pii_class"] for r in rows)
    out.append("class            pairs   share   datasets")
    for name in CLASSES:
        pairs = by_class.get(name, 0)
        datasets = len({r["uuid"] for r in rows if r["pii_class"] == name})
        out.append(f"{name:<16} {pairs:>5}  {pairs/total:>5.1%}   {datasets:>6}")

    out.append("\nby rule")
    by_rule = Counter((r["rule_id"], r["pii_class"]) for r in rows)
    for (rule, name), count in sorted(by_rule.items(),
                                      key=lambda kv: -kv[1]):
        out.append(f"  {rule:<26} -> {name:<15} {count:>5}")

    out.append("\nby dataset context")
    for context, count in Counter(r["dataset_context"] for r in rows).most_common():
        out.append(f"  {context:<22} {count:>5}")

    out.append("\ntop headers still undecided")
    undecided = Counter(r["column"] for r in rows if r["pii_class"] == "undecided")
    for column, count in undecided.most_common(20):
        out.append(f"  {count:>5}  {column}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Self-tests
# --------------------------------------------------------------------------

def _feat(column, values, types=("PERSON",), cardinality=None,
          frequency=1, siblings=()):
    detections = [{"uuid": "u", "lot": 1, "column": column,
                   "entity_type": types[i % len(types)],
                   "entity_text": v, "score": 0.85, "source": "presidio",
                   "cardinality": cardinality}
                  for i, v in enumerate(values)]
    index = {normalize_entity_text(v): frequency for v in values}
    return column_features(detections, index, siblings)


def _run_tests():
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # -- dataset_context ---------------------------------------------------
    check("ctx directory",
          dataset_context("Former Members of Rajya Sabha")[0],
          "official_directory")
    check("ctx nodal",
          dataset_context("List of Nodal Officers under RTI Act")[0],
          "official_directory")
    check("ctx survey",
          dataset_context("Annual Health Survey - Woman Schedule")[0],
          "individual_records")
    check("ctx aggregate",
          dataset_context("Performance of Key HMIS Indicators for Dibang "
                          "Valley")[0],
          "aggregate_statistics")
    check("ctx both prefers individual",
          dataset_context("Directory of Beneficiaries under the scholarship "
                          "scheme")[0],
          "individual_records")
    check("ctx empty", dataset_context(None)[0], "unknown")

    # -- header tokens -----------------------------------------------------
    check("glued father", "father" in header_tokens("fathername"), True)
    check("camel case", "enterprise" in header_tokens("EnterpriseName"), True)
    check("short glued not substring-matched",
          "mp" in header_tokens("employment"), False)

    # -- Q1: controlled vocabularies ---------------------------------------
    crime = _feat("Crime Head", ["Murder", "Dacoity", "Theft"], frequency=288)
    check("crime head is FP",
          classify_pair(crime, "aggregate_statistics")["pii_class"],
          "false_positive")

    indicator = _feat("Indicator",
                      ["Number of pregnant women registered for ANC",
                       "Number of children fully immunised"], frequency=1500)
    check("HMIS indicator is FP",
          classify_pair(indicator, "aggregate_statistics")["pii_class"],
          "false_positive")

    commodity = _feat("Agricultural Commodities (First)",
                      ["PADDY", "BARLEY", "MUSTARD"], frequency=190)
    check("commodity is FP",
          classify_pair(commodity, "aggregate_statistics")["pii_class"],
          "false_positive")

    tongue = _feat("Mother Tongue Name", ["Hindi", "Bhojpuri"], frequency=18)
    check("mother tongue is FP (skip header beats 'mother')",
          classify_pair(tongue, "aggregate_statistics")["rule_id"],
          "R1-skip-header")

    hq = _feat("Sub District Head Quarter (Name)",
               ["Chhatarpur", "Bijawar"], frequency=162)
    check("head quarter is FP",
          classify_pair(hq, "aggregate_statistics")["pii_class"],
          "false_positive")

    # A numbering-plan miss: an aggregate read as a phone number. "1800..."
    # satisfies the toll-free prefix test, so only the absence of any phone
    # formatting separates it from a real helpline.
    volume = _feat("Aggregate Evapotranspiration Volume",
                   ["1800234567890"], types=("PHONE_NUMBER",))
    check("evapotranspiration volume is FP, not a helpline",
          classify_pair(volume, "aggregate_statistics")["rule_id"],
          "R3-not-a-number")
    check("dialled-number test rejects a bare digit run",
          _looks_like_a_dialled_number("1800234567890"), False)
    check("dialled-number test accepts a formatted toll-free number",
          _looks_like_a_dialled_number("1800-180-1551"), True)

    # -- Q2: permissible ---------------------------------------------------
    member = _feat("Member Name",
                   ["H.K. Javare Gowda", "Janeshwar Mishra", "M.J. Varkey"],
                   cardinality=0.98)
    check("MP name in directory is permissible",
          classify_pair(member, "official_directory")["pii_class"],
          "permissible")

    father = _feat("Father Name",
                   ["Shri Sankara Pillai", "Jaggan Bhagat", "Shri Devshanker"],
                   cardinality=0.97)
    check("MP's father in a directory is permissible",
          classify_pair(father, "official_directory")["rule_id"],
          "R7-directory-context")
    check("same header in a survey is present",
          classify_pair(father, "individual_records")["pii_class"],
          "present")

    vc = _feat("Name of Vice-Chancellor/ Director/ Principal/ Head",
               ["Anil Sahasrabudhe", "R. Subrahmanyam"], cardinality=1.0)
    check("vice-chancellor is permissible without directory context",
          classify_pair(vc, "unknown")["pii_class"], "permissible")

    helpline = _feat("Contact Details", ["1800-180-1551", "011-24300606"],
                     types=("PHONE_NUMBER",))
    check("helpline is permissible",
          classify_pair(helpline, "unknown")["rule_id"],
          "R4-institutional-channel")

    gov_email = _feat("Email ID", ["okazmi@sansad.nic.in", "cs@gov.in"],
                      types=("EMAIL_ADDRESS",))
    check("gov email is permissible",
          classify_pair(gov_email, "unknown")["pii_class"], "permissible")

    # -- Q2: present -------------------------------------------------------
    beneficiary = _feat("Beneficiary Name", ["Rahul Kumar", "Sita Devi"],
                        cardinality=0.99)
    check("beneficiary overrides directory context",
          classify_pair(beneficiary, "official_directory")["pii_class"],
          "present")

    mother = _feat("Mother Name", ["Shanti Devi", "Kamla Devi"],
                   cardinality=0.96)
    check("mother name in a survey is present",
          classify_pair(mother, "individual_records")["pii_class"], "present")

    mobile = _feat("KccAns", ["7739668923"], types=("PHONE_NUMBER",))
    check("subscriber mobile in free text is present",
          classify_pair(mobile, "unknown")["rule_id"], "R11-personal-channel")

    consumer_email = _feat("KccAns", ["dbtcellagri@gmail.com"],
                           types=("EMAIL_ADDRESS",))
    check("consumer email is present",
          classify_pair(consumer_email, "unknown")["pii_class"], "present")

    # -- residual ----------------------------------------------------------
    enterprise = _feat("EnterpriseName", ["Jay Mataji", "Randal Daimond"],
                       cardinality=0.98)
    got = classify_pair(enterprise, "unknown")
    check("MSME enterprise name lands on a controlled-vocab or residual rule",
          got["rule_id"] in ("R1-controlled-vocab", "R12-residual"), True)

    # -- regressions -------------------------------------------------------
    # A republished directory: the same members appear in six near-duplicate
    # datasets, so corpus frequency is 6. Frequency alone must not reject a
    # column that is entirely name-shaped and almost entirely distinct.
    republished = _feat("Member Name",
                        ["H.K. Javare Gowda", "Janeshwar Mishra",
                         "M.J. Varkey"], cardinality=1.0, frequency=6)
    check("a six-times-republished member list is not rejected on frequency",
          classify_pair(republished, "official_directory")["pii_class"],
          "permissible")

    # A genuine controlled vocabulary at high frequency and mediocre shape.
    scheme = _feat("healthscheme_1", ["RSBY card", "State scheme", "None"],
                   cardinality=1.0, frequency=22)
    check("a high-frequency scheme list is still rejected",
          classify_pair(scheme, "individual_records")["pii_class"],
          "false_positive")

    # Dataset context must not convict a column that is not about people.
    monument = _feat("Name of the Monument", ["Taj Mahal", "Red Fort"],
                     cardinality=1.0)
    check("a monument list in an individual-records dataset is not present",
          classify_pair(monument, "individual_records")["pii_class"],
          "undecided")
    depth = _feat("Depth range (m)", ["Ten Twenty"], cardinality=1.0)
    check("a measurement column is not present",
          classify_pair(depth, "individual_records")["pii_class"], "undecided")

    # Schema-derived context, for the six datasets whose catalogue title
    # describes a different file than the one that was scanned.
    sansad_headers = ["Member Name", "Father Name", "Spouse Name",
                      "Position(s) Held", "Books Published",
                      "Other Profession(s)"]
    check("member-biography schema is recognised as a directory",
          schema_context(sansad_headers)[0], "official_directory")
    check("an HMIS schema is not",
          schema_context(["Indicator", "District", "Value"])[0], None)
    check("schema context rescues the mistitled directory",
          classify_pair(
              _feat("Father Name", ["Shri Sankara Pillai", "Jaggan Bhagat"],
                    cardinality=1.0, frequency=6),
              *schema_context(sansad_headers))["pii_class"],
          "permissible")

    # -- R6, the office-holder allow-list ----------------------------------
    # Driven through the feature dict rather than the real gazetteer, so the
    # rule is tested whether or not the list has been built on this machine.
    roster = _feat("Name", ["Kapil Sibal", "Amar Singh", "Ahmed Patel",
                            "Anand Sharma"], cardinality=1.0)
    roster["office_holder_matches"] = 4
    roster["office_holder_match_rate"] = 1.0
    check("a column of known office holders is permissible",
          classify_pair(roster, "unknown")["rule_id"], "R6-office-allowlist")

    stray = dict(roster)
    stray["office_holder_matches"] = 1
    stray["office_holder_match_rate"] = 0.25
    check("one office holder among private names decides nothing",
          classify_pair(stray, "unknown")["rule_id"] == "R6-office-allowlist",
          False)

    beneficiaries = _feat("Beneficiary Name", ["Kapil Sibal", "Amar Singh",
                                               "Ahmed Patel"], cardinality=1.0)
    beneficiaries["office_holder_matches"] = 3
    beneficiaries["office_holder_match_rate"] = 1.0
    check("a beneficiary column is present even if every name matches",
          classify_pair(beneficiaries, "unknown")["pii_class"], "present")

    # -- invariants --------------------------------------------------------
    check("PRESENT_RULES is accurate",
          set(PRESENT_RULES),
          {"R5-private-absolute", "R9-private-contextual",
           "R10-individual-records", "R11-personal-channel"})

    for name in CLASSES:
        check(f"{name} is a known class", name in CLASSES, True)

    # -- email domain classes ---------------------------------------------
    check("mixed domains", email_domain_class(
        ["a@nic.in", "b@gmail.com"]), "mixed")
    check("no emails", email_domain_class(["not an email"]), None)

    # -- --csv input -------------------------------------------------------
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        def write(rel, text):
            path = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            return path
        # Folder-run output: same file name in two folders.
        write("pii-present/2023_Q4.csv", "State,KccAns,Crop\nX,y,z\n")
        write("pii-present/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              "2023_Q4.csv,KccAns,3,PHONE_NUMBER,9876543210,1.0,regex\n"
              "2023_Q4.csv,KccAns,4,PERSON,Ramesh Kumar,0.85,presidio\n")
        write("other/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              "2023_Q4.csv,Name,1,PERSON,Sunita Devi,,presidio\n")
        # Single-file-run output: stem in uuid, no file column.
        write("single/msme - assam.csv", "Enterprise Name\nA\n")
        write("single/msme - assam_pii_detections.csv",
              "uuid,column,row_index,entity_type,entity_text,score,source\n"
              "msme - assam,Enterprise Name,0,PERSON,Asha Traders,0.85,presidio\n")
        rid = "3b1f0c2a-9d4e-4f1b-8a2c-5e6d7f8a9b0c"
        write(f"ids/pii_detections.csv",
              "file,column,row_index,entity_type,entity_text,score,source\n"
              f"{rid}.csv,Name,0,PERSON,Ravi Shankar,0.85,presidio\n")
        summary = write("summary.csv", "file,label,pii_found\na.csv,x,True\n")

        dets, meta = load_csv([tmp])
        uuids = sorted(meta)
        check("csv: one dataset per scanned file", uuids,
              [f"ids/{rid}.csv", "other/2023_Q4.csv", "pii-present/2023_Q4.csv",
               "single/msme - assam.csv"])
        check("csv: a descriptive file name is the title",
              meta["single/msme - assam.csv"]["title"], "msme - assam")
        check("csv: a UUID-named file gives no title",
              meta[f"ids/{rid}.csv"]["title"], None)
        check("csv: lot is the CSV lot", {d["lot"] for d in dets}, {CSV_LOT})
        check("csv: title is the file, not the label folder",
              meta["pii-present/2023_Q4.csv"]["title"], "2023_Q4")
        check("csv: header row read from the source file",
              meta["pii-present/2023_Q4.csv"]["headers"],
              ["State", "KccAns", "Crop"])
        check("csv: single-file run recovers the extension",
              meta["single/msme - assam.csv"]["headers"], ["Enterprise Name"])
        check("csv: missing source file has no headers",
              meta["other/2023_Q4.csv"]["headers"], None)
        check("csv: blank score reads as None",
              [d["score"] for d in dets if d["uuid"] == "other/2023_Q4.csv"], [None])
        check("csv: a single detections file resolves too",
              sorted(load_csv([os.path.join(tmp, "other", "pii_detections.csv")])[1]),
              ["2023_Q4.csv"])
        try:
            load_csv([summary])
            check("csv: a summary file is rejected", "accepted", "ValueError")
        except ValueError as exc:
            check("csv: a summary file is rejected", "--summary-out" in str(exc), True)

        rows = with_file_context(classify_detections(dets, meta), meta)
        check("csv: classifies every (file, column)", len(rows), 4)
        sib = derive_sibling_headers(dets, meta)
        check("csv: real header row joins the detected columns",
              sib["pii-present/2023_Q4.csv"], {"State", "KccAns", "Crop"})
        check("csv: no header row keeps the detected columns",
              sib["other/2023_Q4.csv"], {"Name"})
        check("db: no metadata keeps the detected columns",
              derive_sibling_headers(dets)["pii-present/2023_Q4.csv"], {"KccAns"})
        check("csv: carries header row for Tier 3",
              json.loads(next(r["file_headers"] for r in rows
                              if r["uuid"] == "pii-present/2023_Q4.csv")),
              ["State", "KccAns", "Crop"])

    # -- dataset roll-up ---------------------------------------------------
    def crow(uuid, cls, n=1):
        return {"uuid": uuid, "lot": 0, "pii_class": cls, "n_detections": n,
                "rule_id": "R", "dataset_context": "unknown"}
    rolled = {r["uuid"]: r for r in rollup_datasets([
        crow("a", "undecided"), crow("a", "present", "2"),
        crow("b", "false_positive"), crow("b", "undecided"),
        crow("c", "false_positive"), crow("c", "permissible")])}
    check("rollup: present beats undecided", rolled["a"]["pii_class"], "present")
    check("rollup: undecided beats false_positive", rolled["b"]["pii_class"], "undecided")
    check("rollup: permissible beats false_positive", rolled["c"]["pii_class"], "permissible")
    check("rollup: sums detections read back from CSV", rolled["a"]["n_detections"], 3)

    if failures:
        print(f"FAILED {len(failures)} check(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("all self-tests passed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true",
                        help="run self-tests and exit")
    parser.add_argument("--snapshot", metavar="DIR",
                        help="directory of det_lot*.parquet / meta_lot*.parquet")
    parser.add_argument("--db", metavar="PATH",
                        help="metadata.db to read detections from")
    parser.add_argument("--csv", metavar="PATH", nargs="+",
                        help="detection CSVs from run_pii_s3.py --path, or "
                             "directories to search for them")
    parser.add_argument("--write", action="store_true",
                        help="write pii_column_class into --db (needs the "
                             "write lock; refuses if a scan holds it)")
    parser.add_argument("--out", metavar="PATH",
                        help="write the classified rows to this CSV")
    parser.add_argument("--report", metavar="PATH",
                        help="write the summary report to this file")
    args = parser.parse_args()

    if args.test:
        return _run_tests()
    if sum(bool(x) for x in (args.snapshot, args.db, args.csv)) != 1:
        parser.error("exactly one of --test, --snapshot, --db or --csv is required")
    if args.write and not args.db:
        parser.error("--write requires --db")

    if args.snapshot:
        detections, metadata = load_snapshot(args.snapshot)
    elif args.db:
        detections, metadata = load_from_db(args.db)
    else:
        detections, metadata = load_csv(args.csv)

    print(f"loaded {len(detections)} detections over "
          f"{len({d['uuid'] for d in detections})} datasets", file=sys.stderr)
    if not detections:
        print("nothing to classify", file=sys.stderr)
        return 0
    rows = classify_detections(detections, metadata)
    if args.csv:
        rows = with_file_context(rows, metadata)
    report = summarise(rows)
    print(report)

    if args.out:
        write_rows_csv(args.out, rows)
        print(f"\nwrote {len(rows)} rows to {args.out}", file=sys.stderr)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if args.write:
        write_to_db(args.db, rows)
        print(f"\nwrote {len(rows)} rows to pii_column_class in {args.db}",
              file=sys.stderr)
    return 0


def load_from_db(db_path):
    """Read detections and dataset metadata straight from metadata.db."""
    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    detections = []
    for row in con.execute(
            'SELECT uuid, "column", entity_type, entity_text, score, source, '
            "cardinality FROM pii_detections_lot1").fetchall():
        detections.append({"uuid": row[0], "lot": 1, "column": row[1],
                           "entity_type": row[2], "entity_text": row[3],
                           "score": row[4], "source": row[5],
                           "cardinality": row[6]})
    for row in con.execute(
            'SELECT uuid, "column", entity_type, entity_text, score, source '
            "FROM pii_detections_lot2").fetchall():
        detections.append({"uuid": row[0], "lot": 2, "column": row[1],
                           "entity_type": row[2], "entity_text": row[3],
                           "score": row[4], "source": row[5],
                           "cardinality": None})

    metadata = {}
    for row in con.execute(
            'SELECT "Identifier[UUID]", Title, "Relation[Catalog Title]" '
            "FROM dublin_core_metadata WHERE pii_tested").fetchall():
        metadata[row[0]] = {"title": row[1], "catalog_title": row[2],
                            "description": None}
    for row in con.execute(
            "SELECT r.uuid, r.title, r.catalog_title, d.\"Description\" "
            "FROM remain_raw_metadata r "
            "LEFT JOIN dublin_core_remaining d "
            "  ON d.\"Identifier[UUID]\" = r.uuid "
            "WHERE r.pii_tested").fetchall():
        metadata[row[0]] = {"title": row[1], "catalog_title": row[2],
                            "description": row[3]}
    con.close()
    return detections, metadata


if __name__ == "__main__":
    sys.exit(main())
