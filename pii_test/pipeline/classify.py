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
listed explicitly in PRESENTRULES so a future change that adds one is visible.

Usage
-----
run.py's ``classify`` step calls load, classify, withcontext and rollup over a
finished scan. load takes what the scan writes: a folder's
``pii_detections.csv`` or a single file's ``<name>_pii_detections.csv``, or a
directory to search for them. Each scanned *file* becomes one dataset. See
load for what that maps onto and what it cannot supply.
"""

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

from filters import (GAZETTEER, columntokens, headerrule, median, namelike, normalize,
                     phonekind, readlist)

# The public office-holder allow-list, built by
# archive/build_public_office_gazetteer.py. Absent, R6 is simply inert --
# every other rule is unaffected.
OFFICEPATH = os.path.join(GAZETTEER, "public_office_holders.txt")
OFFICEHOLDERS = frozenset(
    normalize(line)
    for line in readlist(
        OFFICEPATH,
        "public office holders will not be recognised (the list is built by "
        "pii_test/archive/build_public_office_gazetteer.py --all)"))


# A single match decides nothing: "Ram Singh" is an MP and several hundred
# thousand other people. A share of the column's distinct values has to match
# before the column reads as a roster of office holders, and a column with
# only one or two distinct values cannot clear that bar meaningfully.
OFFICERATE = 0.30
OFFICEMIN = 3

CLASSES = ("false_positive", "permissible", "present", "undecided")
ROLES = ("not_person", "public_office", "org_contact",
         "private_individual", "personal_contact", "unknown")

# Rules whose verdict is "present". Any addition here widens what the pipeline
# treats as a live privacy problem, so the set is written out rather than
# derived, and the self-tests assert its contents.
PRESENTRULES = ("R5-private-absolute", "R9-private-contextual",
                 "R10-individual-records", "R11-personal-channel")


# --------------------------------------------------------------------------
# Header vocabularies
# --------------------------------------------------------------------------

# Controlled vocabularies that headerrule does not already skip.
# Every entry was read off the stored detection table: these headers hold a
# closed list of categories, never people. Kept separate from
# SKIPTOKENS because that set governs *whether to scan* and
# is load-bearing for the live pipeline; this one only governs how an
# already-stored detection is read, so it can be extended without
# invalidating any scan.
VOCABTOKENS = {
    # census / NCRB / statistical row labels.
    #
    # "head" is deliberately absent. It is the person word in "Name of
    # Vice-Chancellor/Director/Principal/Head" and the category word in
    # "Crime Head" and "Budget Head", and NOTPERSON
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
FREETEXT = {
    "answer", "ans", "question", "query", "remark", "remarks", "comment",
    "comments", "note", "notes", "detail", "details", "description",
    "abstract", "summary", "text", "feedback", "complaint", "grievance",
    "faq", "faqanswer", "response", "narrative",
}

# Office-holder words. A person named in one of these columns is named in a
# public capacity: DPDP Act 2023 s.3(c)(ii) puts personal data published under
# a legal obligation outside the Act, and office-bearer directories are
# published under exactly such obligations.
OFFICETOKENS = {
    "mp", "mla", "mlc", "minister", "chairman", "chairperson", "chair",
    "vicechancellor", "chancellor", "registrar", "commissioner",
    "cpio", "apio", "pio", "nodal", "incharge", "hod", "dean", "warden",
    "sarpanch", "pradhan", "mayor", "collector", "magistrate", "speaker",
    "governor", "ambassador", "judge", "justice", "mayor",
}

# Weaker office words: real in a directory, ambiguous elsewhere. "Director"
# heads an institute and also a private company; "Officer" appears in both
# staff lists and beneficiary tables. These need the dataset to agree.
WEAKOFFICE = {
    "director", "principal", "secretary", "officer", "official", "head",
    "president", "member", "representative", "authority", "coordinator",
}

# Private-individual words that no dataset title can override. A patient is a
# patient in a table calling itself a directory.
PRIVATEALWAYS = {
    "beneficiary", "beneficiaries", "patient", "victim", "accused",
    "complainant", "deceased", "borrower", "applicant", "candidate",
    "prisoner", "inmate", "orphan", "widow", "migrant", "labourer",
}

# Private-individual words that a genuine official directory does override --
# the relatives named in a parliamentary member biography are published with
# the member's own record.
PRIVATECONTEXT = {
    "father", "mother", "spouse", "husband", "wife", "guardian", "parent",
    "child", "children", "son", "daughter", "student", "pupil", "farmer",
    "worker", "resident", "household", "respondent", "customer",
    "subscriber", "tenant", "trainee", "employee", "staff",
}

# Quasi-identifier headers. Two or more of these among a dataset's other
# detected columns means the table describes individuals, whatever any single
# header says. Without the file's header row, siblings are only the columns
# that produced detections, so a clean sibling is invisible (see
# siblingheaders); load reads the real header row and sees all.
QUASI = {
    "age", "gender", "sex", "caste", "religion", "income", "disease",
    "diagnosis", "aadhaar", "aadhar", "bank", "account", "village",
    "house", "household", "scheme", "disability", "marital", "pregnancy",
    "vaccination", "treatment",
}

# Things that get named in a "Name of ..." column and are not people. Without
# these, any column whose header contains "name" reads as a person column, and
# "Name of the Monument" convicts a heritage list. Observation-driven, like the
# gazetteers: extended as the corpus turns up more, never guessed at.
NOTPEOPLE = {
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
DIRECTORYMARKERS = {
    "position", "positions", "constituency", "party", "tenure", "portfolio",
    "publication", "publications", "book", "books", "profession",
    "professions", "achievement", "achievements", "biography", "elected",
    "term", "ministry", "office", "designation",
}

ADDRESS = {"address", "addr", "residence", "domicile"}

OFFICEDOMAINS = (
    ".gov.in", ".nic.in", ".ac.in", ".edu.in", ".res.in", ".org.in",
    "@gov.in", "@nic.in",
)

# --------------------------------------------------------------------------
# Dataset context patterns
# --------------------------------------------------------------------------

DIRECTORY = re.compile(
    r"\b(director(y|ies)|who\s*'?s\s*who|office\s+bearer|list\s+of\s+"
    r"(officer|official|member|minister|employee|faculty|staff)|"
    r"members?\s+of\s+(parliament|rajya|lok|assembly|council)|"
    r"(former|current|sitting)\s+members?|contact\s+(detail|list|director)|"
    r"nodal\s+officer|cpio|public\s+information\s+officer|rti|"
    r"awardee|award\s+winner|recipients?\s+of|padma|"
    r"vice[-\s]?chancellor|telephone\s+director)", re.IGNORECASE)

INDIVIDUAL = re.compile(
    r"\b(survey|schedule|beneficiar|applicant|enrol|enrol?lment|registration|"
    r"call\s*cent(re|er)|transcript|kisan\s+call|complaint|grievance|"
    r"patient|household|houselist|respondent|individual\s+record|"
    r"pension(er)?s?\s+list|ration\s+card|job\s+card|scholarship|"
    r"admission|candidate\s+list|voter)", re.IGNORECASE)

AGGREGATE = re.compile(
    r"\b(performance|statistic|number\s+of|distribution|classification|"
    r"amenit|traffic|consumption|incidence|production|area\s+under|"
    r"year[-\s]wise|state[-\s]wise|district[-\s]wise|total\s+|"
    r"annual\s+report|comparative\s+statement|census|indicator)",
    re.IGNORECASE)

CONTEXTS = ("official_directory", "individual_records",
            "aggregate_statistics", "unknown")


def datasetcontext(title, catalog_title=None, description=None):
    """Classify a dataset by what kind of thing its rows are.

    Returns ``(context, reason)``. The directory and individual-record tests
    run before the aggregate test because an aggregate word is common in both
    ("Annual Report of Members ..."), while the reverse is rare.
    """
    blob = " ".join(str(p) for p in (title, catalog_title, description) if p)
    if not blob.strip():
        return "unknown", "no title"

    directory = DIRECTORY.search(blob)
    individual = INDIVIDUAL.search(blob)
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

    aggregate = AGGREGATE.search(blob)
    if aggregate:
        return "aggregate_statistics", f"title matches {aggregate.group(0)!r}"
    return "unknown", "no context pattern"


MARKERMIN = 2


def schemacontext(headers):
    """Context read off the dataset's column schema, or ``(None, reason)``.

    The schema comes from the scanned file; the title comes from the
    catalogue, and in this corpus the two can disagree outright. Where the
    schema speaks, it outranks the title -- see DIRECTORYMARKERS.
    """
    tokens = set()
    for header in headers:
        tokens |= headertokens(header)
    markers = sorted(tokens & DIRECTORYMARKERS)
    if len(markers) >= MARKERMIN and (tokens & {"name", "member"}):
        return "official_directory", (
            f"column schema carries office-bearer markers "
            f"{', '.join(markers[:4])}")
    return None, "no schema signal"


# --------------------------------------------------------------------------
# Header helpers
# --------------------------------------------------------------------------

def headertokens(column):
    """Lowercase tokens of a header, plus naive singulars."""
    raw = columntokens(column)
    tokens = set(raw)
    for t in raw:
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            tokens.add(t[:-1])
    # Headers written without separators ("fathername", "waterbodyname").
    if len(raw) == 1 and len(raw[0]) >= 8:
        glued = raw[0]
        for vocab in (OFFICETOKENS, PRIVATEALWAYS,
                      PRIVATECONTEXT, VOCABTOKENS,
                      FREETEXT, WEAKOFFICE):
            tokens.update(v for v in vocab if len(v) >= 5 and v in glued)
    return tokens


def first(tokens, vocab):
    """First matching token, alphabetically, or None. Stable for reasons."""
    common = tokens & vocab
    return sorted(common)[0] if common else None


def emailclass(values):
    """"institutional", "mixed", "consumer" or None for a set of emails."""
    emails = [v for v in values if "@" in str(v)]
    if not emails:
        return None
    institutional = sum(
        1 for e in emails
        if any(str(e).lower().rstrip(">.,;").endswith(s)
               or s in str(e).lower()
               for s in OFFICEDOMAINS))
    if institutional == len(emails):
        return "institutional"
    if institutional:
        return "mixed"
    return "consumer"


# --------------------------------------------------------------------------
# Feature extraction
# --------------------------------------------------------------------------

def siblingheaders(detections, metadata=None):
    """Map uuid -> the dataset's headers, as far as they are known.

    The base set is the columns that produced a detection -- strictly a
    subset, in which a clean column is invisible and the absence of a
    quasi-identifier sibling proves nothing. Rules therefore only ever read
    this set positively.

    Where ``metadata`` carries the real header row (load reads it off the
    scanned file), it is added. That matters most for directories whose
    descriptive columns are in a script the detector does not read: the Hindi
    Lok Sabha member lists share the English lists' schema, but their
    ``Hobbies`` and ``Activity(s)`` columns produce no detections, so the
    detected-only view misses the directory the English lists are read as.
    """
    siblings = defaultdict(set)
    for d in detections:
        siblings[d["uuid"]].add(d["column"])
    for uuid, meta in (metadata or {}).items():
        if uuid in siblings and meta.get("headers"):
            siblings[uuid].update(meta["headers"])
    return siblings


def features(detections, frequency, siblings=()):
    """Aggregate one (dataset, column) group into the features rules read."""
    values = [d["entity_text"] for d in detections]
    distinct = list(dict.fromkeys(values))
    types = sorted({d["entity_type"] for d in detections})

    persons = [d for d in detections if d["entity_type"] == "PERSON"]
    person_distinct = list(dict.fromkeys(d["entity_text"] for d in persons))
    phones = [d for d in detections if d["entity_type"] == "PHONE_NUMBER"]
    emails = [d for d in detections if d["entity_type"] == "EMAIL_ADDRESS"]

    name_shaped = (
        sum(1 for v in person_distinct if namelike(v))
        / len(person_distinct)) if person_distinct else None
    office_matches = sum(1 for v in person_distinct
                         if normalize(v) in OFFICEHOLDERS)
    median_frequency = median(
        [frequency.get(normalize(v), 1)
         for v in person_distinct]) if person_distinct else None

    phone_kinds = Counter(
        phonekind(d["entity_text"]) or "not-a-number"
        for d in phones)

    cardinalities = [d["cardinality"] for d in detections
                     if d.get("cardinality") is not None]

    sibling_tokens = set()
    for header in siblings:
        sibling_tokens |= headertokens(header)

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
            dialled(d["entity_text"]) for d in phones),
        "email_domain_class": emailclass(
            d["entity_text"] for d in emails),
        "has_regex_source": any(d.get("source") == "regex" for d in detections),
        "sample_values": distinct[:15],
        "sibling_quasi_identifiers": sorted(
            sibling_tokens & QUASI),
    }


# --------------------------------------------------------------------------
# Q1 helpers
# --------------------------------------------------------------------------

SHAPEFLOOR = 0.5
CARDFLOOR = 0.5

# Corpus frequency alone does not reject a column, and this is the correction
# that matters most in the file.
#
# Measured over the stored table: the columns known to hold real people
# (the parliamentary member directories) sit at a median frequency of exactly
# 6, because the same directory is published six times -- across years and in
# both languages -- and every member therefore appears in six "different"
# datasets. Columns that really are controlled vocabularies sit at a median of
# 17 with a 90th percentile of 90. The two ranges overlap, so no threshold on
# frequency alone separates them, and the threshold that ``datasetflag``
# uses for flagging (> 1) rejects the genuine directories outright.
#
# Frequency therefore only rejects when the values are also less than
# uniformly name-shaped. A column that is 100% name-shaped and highly
# distinct is left for the later tiers rather than dismissed here.
FREQFLOOR = 10
FREQSHAPE = 0.9


def dialled(value):
    """Whether a phone match is written the way a number is written.

    ``phonekind`` reads a digit run against the national numbering
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


# --------------------------------------------------------------------------
# The rule cascade
# --------------------------------------------------------------------------

def classifypair(feat, context, why=""):
    """Apply the Tier-1 cascade to one (dataset, column) pair.

    Returns a dict with ``pii_class``, ``role``, ``rule_id``,
    ``rule_strength`` and ``reason``. The first matching rule decides.
    ``why`` is the reason the dataset has its context.
    """
    tokens = headertokens(feat["column"])

    def verdict(pii_class, role, rule_id, strength, reason):
        return {"pii_class": pii_class, "role": role, "rule_id": rule_id,
                "rule_strength": strength, "reason": reason}

    # ---- Q1: is this personal data at all? --------------------------------
    decision, headerwhy = headerrule(feat["column"])
    if decision == "skip":
        return verdict("false_positive", "not_person", "R1-skip-header",
                       "high", f"header is a non-PII column: {headerwhy}")

    vocab = first(tokens, VOCABTOKENS)
    if vocab and feat["entity_types"] == ["PERSON"]:
        return verdict("false_positive", "not_person", "R1-controlled-vocab",
                       "high",
                       f"header token {vocab!r} marks a controlled "
                       f"vocabulary, and only PERSON was detected")

    # Q1 for the PERSON detections: True, False, or None when shape alone
    # cannot decide -- which is a real answer here: it routes the column to
    # the later tiers instead of convicting it.
    shape = feat["name_shaped_fraction"]
    frequency = feat["median_corpus_frequency"]
    if not feat["n_person_distinct"]:
        person, personwhy = None, "no PERSON detections"
    elif shape is not None and shape < SHAPEFLOOR:
        person, personwhy = False, f"{shape:.0%} of distinct values are name-shaped"
    elif feat["cardinality"] is not None and feat["cardinality"] <= CARDFLOOR:
        person, personwhy = False, f"cardinality {feat['cardinality']:.2f}"
    elif frequency is not None and frequency > FREQFLOOR:
        if shape is not None and shape < FREQSHAPE:
            person, personwhy = False, (f"median value appears in {frequency:g} datasets "
                                        f"and only {shape:.0%} of values are name-shaped")
        else:
            person, personwhy = None, (f"median value appears in {frequency:g} datasets, "
                                       f"but {shape:.0%} of values are name-shaped")
    else:
        person, personwhy = True, "name-shaped, corpus-rare"

    # Q1 for PHONE/EMAIL, the same three answers.
    kinds = feat["phone_kinds"]
    email = feat["email_domain_class"] is not None
    if not kinds and not email:
        contact, contactwhy = None, "no contact detections"
    elif email:
        contact, contactwhy = True, "email address present"
    elif not kinds.keys() - {"not-a-number"}:
        contact, contactwhy = False, "no phone match fits the national numbering plan"
    elif not feat["phone_values_look_dialled"] and decision != "force-pii":
        contact, contactwhy = False, ("phone matches are bare digit runs in a column "
                                      "whose header names no contact channel")
    else:
        contact, contactwhy = True, "contact channel present"

    if person is False and contact is not True:
        return verdict("false_positive", "not_person", "R2-column-shape",
                       "high", f"PERSON values rejected: {personwhy}")
    if person is not True and contact is False:
        return verdict("false_positive", "not_person", "R3-not-a-number",
                       "high", contactwhy)

    # ---- Q2: permissible or present? --------------------------------------
    # What the column itself says it holds: "contact", "person" or None. The
    # context rules (R6, R9) may only convict a column that shows one of
    # these. Dataset context says what the *rows* are; it cannot say that a
    # particular column is about people, and letting it try is what labelled
    # "Name of the Monument" and "Depth range (m)" as personal data.
    if decision == "force-pii":
        signal = "contact"
    elif decision == "force-person":
        signal = "person"
    elif tokens & NOTPEOPLE or tokens & VOCABTOKENS:
        signal = None
    elif "name" in tokens:
        signal = "person"
    # An address is personal data in its own right, and the header carries no
    # "name" or contact token to say so. In a directory this makes the MP's
    # listed address permissible; in a survey it makes a respondent's address
    # present. Both are decided by the context rules below, not here.
    elif tokens & ADDRESS or email or kinds:
        signal = "contact"
    else:
        signal = None
    if signal is None:
        return verdict("undecided", "unknown", "R12-residual", "none",
                       f"no person or contact signal in the header; dataset "
                       f"context ({context}) alone cannot convict a column")

    officephone = bool(kinds) and not (
        kinds.keys() - {"institutional", "landline", "not-a-number"})
    officeemail = feat["email_domain_class"] == "institutional"

    if person is not True and (officephone or officeemail) \
            and not (kinds.keys() & {"mobile"}):
        channel = "toll-free/landline" if officephone else "institutional domain"
        return verdict("permissible", "org_contact", "R4-institutional-channel",
                       "high",
                       f"every contact value is an office channel ({channel})")

    absolute = first(tokens, PRIVATEALWAYS)
    if absolute:
        return verdict("present", "private_individual", "R5-private-absolute",
                       "high",
                       f"header token {absolute!r} names a private individual "
                       f"regardless of dataset context")

    matches = feat["office_holder_matches"]
    rate = feat["office_holder_match_rate"]
    if matches >= OFFICEMIN and rate >= OFFICERATE:
        return verdict("permissible", "public_office", "R6-office-allowlist",
                       "high",
                       f"{rate:.0%} of this column's distinct values "
                       f"({matches}) are known public office holders")

    if context == "official_directory":
        return verdict("permissible", "public_office", "R7-directory-context",
                       "medium",
                       f"dataset is an office-bearer directory ({why})")

    office = first(tokens, OFFICETOKENS)
    if office:
        return verdict("permissible", "public_office", "R8-office-header",
                       "high",
                       f"header token {office!r} names a public office holder")

    contextual = first(tokens, PRIVATECONTEXT)
    if contextual:
        return verdict("present", "private_individual", "R9-private-contextual",
                       "high",
                       f"header token {contextual!r} names a private "
                       f"individual, and the dataset is not a directory")

    if context == "individual_records":
        return verdict("present", "private_individual", "R10-individual-records",
                       "medium",
                       f"dataset holds individual records ({why})")

    freetext = first(tokens, FREETEXT)
    if ("mobile" in kinds) or (feat["email_domain_class"] in ("consumer", "mixed")):
        where = f"free-text column ({freetext!r})" if freetext else "column"
        return verdict("present", "personal_contact", "R11-personal-channel",
                       "high",
                       f"subscriber mobile or personal email address in this "
                       f"{where}")

    weak = first(tokens, WEAKOFFICE)
    hint = f"; header token {weak!r} hints at an office" if weak else ""
    quasi = feat["sibling_quasi_identifiers"]
    if quasi:
        hint += f"; sibling columns include {', '.join(quasi[:3])}"
    return verdict("undecided", "unknown", "R12-residual", "none",
                   f"real names in a {context} dataset with no role "
                   f"signal in the header{hint}")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def classify(detections, metadata):
    """Classify every (uuid, lot, column) group.

    ``detections`` is a list of dicts with uuid, lot, column, entity_type,
    entity_text, score, source and optionally cardinality. ``metadata`` maps
    uuid -> dict with title, catalog_title, description.
    """
    # Normalized PERSON value -> number of distinct datasets holding it,
    # counted over the detections being classified rather than read from
    # ``gazetteer/cross_dataset_common.txt``. The file is built from
    # post-filter detections that were themselves produced using the file, so
    # it can only ever grow; counting here at least keeps the count current
    # with what is being classified. It is still the same feedback loop and is
    # used only as one of three Q1 tests, never alone.
    seen = defaultdict(set)
    for d in detections:
        if d["entity_type"] == "PERSON" and normalize(d["entity_text"]):
            seen[normalize(d["entity_text"])].add(d["uuid"])
    frequency = {k: len(v) for k, v in seen.items()}
    siblings = siblingheaders(detections, metadata)

    groups = defaultdict(list)
    for d in detections:
        groups[(d["uuid"], d["lot"], d["column"])].append(d)

    contexts = {}
    rows = []
    for (uuid, lot, column), group in sorted(groups.items()):
        meta = metadata.get(uuid, {})
        if uuid not in contexts:
            fromtitle = datasetcontext(
                meta.get("title"), meta.get("catalog_title"),
                meta.get("description"))
            fromschema, schemawhy = schemacontext(siblings[uuid])
            # The schema is read from the file; the title is read from the
            # catalogue, and the two demonstrably disagree in this corpus.
            # Where the schema speaks, it wins.
            contexts[uuid] = (fromschema, schemawhy) if fromschema else fromtitle
        context, why = contexts[uuid]

        others = siblings[uuid] - {column}
        feat = features(group, frequency, others)
        result = classifypair(feat, context, why)

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
                "context_reason": why,
            }, ensure_ascii=False),
            "classified_at": datetime.now(),
        })
    return rows


# Loudest first: the loudest column decides the dataset.
LOUDEST = ("present", "permissible", "undecided", "false_positive")


def rollup(rows):
    """One row per dataset: present > permissible > undecided > false_positive."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["uuid"], r["lot"])].append(r)
    out = []
    for (uuid, lot), group in sorted(groups.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        classes = {r["pii_class"] for r in group}
        out.append({
            "uuid": uuid,
            "lot": lot,
            "pii_class": next(c for c in LOUDEST if c in classes),
            "n_columns": len(group),
            "n_detections": sum(int(r["n_detections"]) for r in group),
            "rule_ids": ",".join(sorted({str(r["rule_id"]) for r in group})),
            "dataset_context": group[0]["dataset_context"],
        })
    return out


# What the scan writes. Duplicated rather than imported: importing scan.py
# loads torch, transformers and presidio, which Tier 1 never needs.
DETECTIONS = "pii_detections.csv"       # scan.DETECTIONS
SINGLESUFFIX = "_pii_detections.csv"
TABULAR = (".csv", ".xls", ".xlsx")     # scan.TABULAR
# The lot a scanned file is in: none, written as 0.
CSVLOT = 0
# data.gov.in resource ids, which is how S3-downloaded files are named.
UUIDSTEM = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def finddetections(paths):
    """Expand files and directories into the detection CSVs they hold."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            for dirpath, _, filenames in sorted(os.walk(path)):
                for name in sorted(filenames):
                    if name == DETECTIONS or name.endswith(SINGLESUFFIX):
                        found.append(os.path.join(dirpath, name))
        elif os.path.isfile(path):
            found.append(path)
        else:
            raise FileNotFoundError(path)
    return found


def headerrow(path):
    """The source file's header row, or None if it cannot be read.

    Tier 1 adds it to the detected columns its schema and quasi-identifier
    rules read, and Tier 3 shows it to the judge.
    """
    try:
        if os.path.splitext(path)[1].lower() in (".xls", ".xlsx"):
            import pandas as pd
            headers = list(pd.read_excel(path, nrows=0).columns)
        else:
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


def load(paths):
    """Read the detection CSVs the scan writes: (detections, metadata).

    * **One scanned file is one dataset.** The ``uuid`` field keeps its name
      from the database days, but here it is a file key, not a data.gov.in id:
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
      (see siblingheaders) and Tier 3 shows it to the judge.
    * **No cardinality, no catalog title or description.** The folder CSVs
      do not store them; run.py adds the catalogue fields for a lot.
    """
    files = finddetections(paths)
    roots = [os.path.abspath(p if os.path.isdir(p) else os.path.dirname(p) or ".")
             for p in paths]
    root = os.path.commonpath(roots)

    detections, metadata = [], {}
    for path in files:
        folder = os.path.dirname(os.path.abspath(path))
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
            missing = {"column", "entity_type", "entity_text"} - fields
            if missing or not fields & {"file", "uuid"}:
                hint = (" -- this looks like a --summary-out file; pass the "
                        "scanned folder or its pii_detections.csv instead"
                        if "pii_found" in fields else "")
                raise ValueError(
                    f"{path} is not a detections CSV (missing "
                    f"{', '.join(sorted(missing)) or 'file/uuid'}){hint}")
            for row in reader:
                # The scanned file the row came from. Folder runs record it in
                # ``file``. Single-file runs record only the stem in ``uuid``,
                # so the extension is recovered from what sits beside it.
                if row.get("file"):
                    source = os.path.join(folder, row["file"])
                else:
                    stem = os.path.join(folder, row["uuid"])
                    source = next((stem + ext for ext in TABULAR
                                   if os.path.exists(stem + ext)), stem)
                uuid = os.path.relpath(source, root).replace(os.sep, "/")
                if uuid not in metadata:
                    stem = os.path.splitext(os.path.basename(source))[0]
                    metadata[uuid] = {
                        "title": None if UUIDSTEM.match(stem) else stem,
                        "catalog_title": None,
                        "description": None,
                        "source_file": source,
                        "headers": headerrow(source),
                    }
                score = row.get("score")
                detections.append({
                    "uuid": uuid, "lot": CSVLOT, "column": row["column"],
                    "entity_type": row["entity_type"],
                    "entity_text": row["entity_text"],
                    "score": float(score) if score not in (None, "") else None,
                    "source": row.get("source"), "cardinality": None,
                })
    return detections, metadata


def withcontext(rows, metadata):
    """Add the columns Tier 3 reads: ``source_file``, ``title`` and
    ``file_headers`` (a JSON list)."""
    out = []
    for r in rows:
        meta = metadata.get(r["uuid"], {})
        headers = meta.get("headers")
        out.append({**r,
                    "source_file": meta.get("source_file"),
                    "title": meta.get("title"),
                    "file_headers": json.dumps(headers, ensure_ascii=False) if headers else ""})
    return out


def writecsv(path, rows, fields=None):
    """Write dict rows to a CSV, the first row's keys as the header."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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

