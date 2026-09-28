"""
Post-processing filters for PII detection results.

Two jobs:

1. Reject NER PERSON predictions that are categorically not people. Four
   mechanisms, in increasing order of generality:

   * closed vocabularies written out below -- location categories, academic
     qualifications, school schemes, management types, agricultural terms;
   * generated gazetteers under ``gazetteer/``, one file per vocabulary so a
     rejection stays traceable and a list can be dropped wholesale;
   * cross-dataset frequency: a value that appears in more than a handful of
     unrelated datasets is a category, not a person. This is the only signal
     here that scales past hand-curated lists;
   * a score floor. This *does* work, contrary to what this docstring said
     before: the earlier conclusion ("Urban" scores 0.997, so scores cannot
     separate) was an artifact of ``aggregation_strategy="simple"``, which
     reports inflated subword scores. Under the word-level ``"average"``
     aggregation now used in pii_utils, scores separate -- see
     PERSON_SCORE_FLOOR for the measured curve.

2. Decide whether a dataset as a whole should be flagged, which is a
   different and stricter question than whether any single cell matched.
"""

import logging
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

GAZETTEER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gazetteer")
GAZETTEER_PATH = os.path.join(GAZETTEER_DIR, "place_names.txt")

# Unicode combining marks -- Devanagari matras and the virama, Gujarati and
# Tamil vowel signs, Latin diacritics. Python's re does not count these as \w
# (they are categories Mn/Mc, not L*), so a punctuation class written as
# [^\w\s] treats every matra as punctuation and replaces it with a space.
# That shattered "दिनकर प्रसाद सिंह" into seven fragments -- "द नकर प रस द स ह"
# -- which made every Devanagari value fail looks_like_person_name and made
# the token-based organisation and phrase rules unreachable in Indic scripts.
_COMBINING_MARKS = "".join(
    chr(c) for c in list(range(0x0300, 0x0E00)) + list(range(0x1AB0, 0x1B00))
    + list(range(0x1DC0, 0x1E00)) + list(range(0x20D0, 0x2100))
    if unicodedata.category(chr(c))[0] == "M"
)
_PUNCT_RE = re.compile(r"[^\w\s" + re.escape(_COMBINING_MARKS) + r"]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_DIGIT_RE = re.compile(r"\d")


def normalize_entity_text(text):
    """Casefold, replace punctuation with spaces, collapse whitespace.

    Both sides of every comparison go through this, so "Ph.D"/"PhD",
    "URBAN"/"Urban" and "G.L.Puram"/"GL Puram" all land on the same key.
    Punctuation becomes a space rather than being deleted, so "Kendriya
    Vidyalaya / Central School" does not fuse into one token.
    """
    if not text:
        return ""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", str(text).casefold())).strip()


# --- Rejection vocabularies ---
#
# Closed sets of things that are categorically not people, grouped by origin
# so a rejection stays traceable and a group can be dropped wholesale if it
# turns out to over-reject.

# The two-valued Location column that produced 47% of all LOT 2 detections.
LOCATION_CATEGORIES = {
    "urban", "rural", "total", "semi urban", "semi-urban", "metro",
    "municipal", "municipality", "corporation", "cantonment", "notified area",
}

QUALIFICATIONS = {
    "b.el", "b.el.ed", "b.ed", "m.ed", "d.ed", "d.el.ed", "b.p.ed", "m.p.ed",
    "m.phil", "ph.d", "d.phil", "d.litt",
    "b.a", "m.a", "b.sc", "m.sc", "b.com", "m.com", "b.tech", "m.tech",
    "b.e", "m.e", "bba", "mba", "bca", "mca", "llb", "llm",
    "mbbs", "bams", "bhms", "bums", "bds", "md", "ms",
    "diploma", "certificate", "graduate", "post graduate", "under graduate",
    "matric", "matriculation", "intermediate", "secondary", "senior secondary",
    "higher secondary", "primary", "upper primary", "pre primary",
}

SCHOOL_SCHEMES = {
    "kendriya vidyalaya", "kendriya vidyalaya / central school",
    "central school", "jawahar navodaya vidyalaya", "navodaya vidyalaya",
    "sainik school", "eklavya model residential school",
    "model school", "ashram school", "sarva shiksha abhiyan",
    "samagra shiksha", "anganwadi", "madarsa", "madrasa",
}

MANAGEMENT_TYPES = {
    "government", "govt", "govt.", "pvt", "private", "private aided",
    "private unaided", "local body", "department of education",
    "tribal welfare department", "social welfare department",
    "central govt", "state govt", "aided", "unaided", "unrecognised",
    "unrecognized", "recognised", "recognized",
}

# Carried over from the KCC agricultural advisory data: scheme names, crops
# and chemicals that standard NER tags as PERSON because they are
# capitalised phrases.
AGRICULTURAL_TERMS = {
    # Schemes and programs
    "kisan samman", "nidhi yojna", "nidhi yojana", "kisan samman nidhi",
    "diesel subsidy", "seed subsidy", "weed control",
    "krishi vigyan kendra", "mantri krishi", "bihar rajya fasal",
    "pradhan mantri", "pm kisan",
    # Crops
    "pointed gourd", "bottle gourd", "banana", "rice", "wheat",
    "mung phalli", "moong", "arhar", "tur", "chana",
    # Chemicals/pesticides
    "cartap hydrochloride", "imidacloprid", "carbendazim", "mancozeb",
}

GENERIC_NON_NAMES = {
    "click", "aadhar", "aadhaar", "not available", "not applicable",
    "n a", "na", "nil", "none", "null", "unknown", "others", "other",
    "male", "female", "transgender", "yes", "no", "all", "total",
}

# Hindi common words IndicNER frequently mis-tags as PERSON.
HINDI_STOPWORDS = {
    # Address/relational
    "भाई", "बहन", "साहब", "जी", "श्री", "आप",
    # Weather/agriculture vocabulary
    "बारिश", "बादल", "तापमान", "हवा", "मौसम", "धूप",
    "संभावना", "अधिकतम", "न्यूनतम", "हल्की", "मध्यम", "भारी",
    # Scheme/government vocabulary
    "निधि", "योजना", "मंत्री", "प्रधान", "किसान", "सम्मान",
    "रजिस्ट्रेशन", "हेल्प", "लाईन", "केंद्र", "खाते",
    # Common verbs/particles getting flagged
    "हैं", "है", "रहे", "सकी", "होने", "की", "का", "के", "कि",
}

# Tokens that mark a *value* as an organisation rather than a person. Unlike
# the vocabularies above these are matched anywhere in the text, because the
# organisation word is embedded: "Nidhi Hostel", "Gujarat Vidyapith",
# "Kalu Kanya Mahavidhyalya". This is the only rule that reaches values in an
# ambiguous "name" column, or in a header too misspelled to tokenise
# ("instituionname", "hostelname").
#
# Deliberately excluded: honorifics (shri/shree/sri) and words that double as
# personal names (vidya, gyan, gandhi, patil, ambedkar, singh, devi, maharaj).
# Rejecting those would cost real names.
ORGANISATION_TOKENS = {
    # English
    "college", "colleges", "university", "universities", "institute",
    "institution", "institutions", "polytechnic", "academy", "school",
    "schools", "hostel", "campus", "trust", "society", "foundation",
    "mission", "council", "association", "federation", "corporation",
    "library", "hospital", "seminary", "conservatory",
    "education", "educational", "govt", "government", "acedemy",
    # Indic
    "vidyalaya", "vidyalay", "mahavidyalaya", "mahavidhyalya",
    "mahavidyalay", "vishwavidyalaya", "vishvavidyalaya", "vidyapith",
    "vidyapeeth", "shikshan", "sikshan", "shiksha", "siksha", "sanstha",
    "sansthan", "anstha", "samiti", "samaj", "mandal", "mandir", "ashram",
    "gurukul", "pathshala", "shala", "chhatralaya", "chatralaya",
    "adhyapak", "adhyapan", "prasarak", "parishad", "nigam", "vidyamandir",
    "bhawan", "bhavan", "vidyaniketan", "niketan", "peeth", "vihar",
}

# Sub-district administrative units. "Kharkutta Block" is the block around
# Kharkutta, "Ranikor Block" the one around Ranikor, "Vaseitlang MC" a
# municipal council -- administrative areas, not people. NER tags them PERSON
# because they are short capitalised phrases, and none of the existing tests
# catch them: the gazetteer matches exactly, so it knows "kharkutta" but not
# "kharkutta block"; each spelling is confined to the two or three datasets
# covering that district, so cross-dataset frequency stays under its
# threshold; and two capitalised tokens is exactly the shape of a name.
#
# On the LOT 1 corpus this was 244 of 655 datasets in batch 8 -- a 37% flag
# rate from one column of block names.
#
# Matched as whole tokens the way ORGANISATION_TOKENS are: no personal name
# in either reference fixture carries one of these words.
ADMINISTRATIVE_UNITS = {
    "block", "blocks", "tehsil", "tahsil", "taluk", "taluka", "taluq",
    "panchayat", "municipality", "palika", "nigam", "subdivision",
    "constituency", "circle", "ward", "zone", "sector",
    "district", "subdistrict", "village", "hamlet",
    "chc", "phc", "uphc", "anganwadi", "subcentre",
}

# The same idea for abbreviations too short to match safely anywhere in a
# value: "MC" (municipal council), "NAC" (notified area council), "CD"
# (community development). Required to be the final token of a multi-token
# value, so a bare initial inside a name cannot trigger them.
ADMINISTRATIVE_SUFFIXES = {"mc", "nac", "cd", "np", "tp", "mb"}


REJECTION_VOCABULARIES = {
    "location-category": LOCATION_CATEGORIES,
    "qualification": QUALIFICATIONS,
    "school-scheme": SCHOOL_SCHEMES,
    "management-type": MANAGEMENT_TYPES,
    "agricultural-term": AGRICULTURAL_TERMS,
    "generic-non-name": GENERIC_NON_NAMES,
}

_NORMALIZED_VOCABULARIES = {
    label: {normalize_entity_text(v) for v in vocab}
    for label, vocab in REJECTION_VOCABULARIES.items()
}


def compact(normalized):
    """Whitespace-free form of a normalised string.

    Qualifications appear with and without their punctuation -- "M.Phil",
    "M Phil", "MPhil" -- which normalisation alone cannot reconcile because
    it turns punctuation into a space. Compacting both sides does.
    """
    return normalized.replace(" ", "")


# Compact matching is applied to the vocabularies only. The place-name
# gazetteer comes from a structured source and already matches exactly, so
# it does not need the extra collision surface.
_COMPACT_VOCABULARIES = {
    label: {compact(v) for v in vocab}
    for label, vocab in _NORMALIZED_VOCABULARIES.items()
}

# Multi-word entries are also matched as a whole-token subsequence, so
# "Pradhan Mantri Kisan Samman Nidhi Yojana" is rejected by "kisan samman".
# Single-word entries are matched only against the whole string -- matching
# them as substrings is what would reject the real name "Maurice" for
# containing the crop "rice".
#
# Phrases made entirely of one-letter tokens are excluded from the
# subsequence pass for the same reason. "b.a" and "m.a" normalise to ("b","a")
# and ("m","a"), which appear inside every South Indian name written with
# initials -- "M.A. AKHIB AHMED", "CH.B.A.RAJU" -- and cost 85 real names on
# the reference directory. They still match when they are the whole value.
_VOCABULARY_PHRASES = {
    label: [tuple(v.split()) for v in vocab
            if " " in v and not all(len(t) == 1 for t in v.split())]
    for label, vocab in _NORMALIZED_VOCABULARIES.items()
}


# --- Generated gazetteers ---
#
# One file per vocabulary, so a rejection names the list it came from and any
# single list can be deleted if it turns out to over-reject. Each is generated
# from the corpus by build_gazetteer.py; a missing file is not fatal, it just
# loses that one rejection.
GAZETTEER_FILES = {
    "place-name": "place_names.txt",
    "crime-head": "crime_heads.txt",
    "language": "languages.txt",
    "commodity": "commodities.txt",
    "occupation": "occupations.txt",
    "species": "species.txt",
    "settlement": "settlements.txt",
}

# Gazetteer entries shorter than this are dropped at load: two- and
# three-letter entries collide with real name particles and initials, and a
# harvested list is not curated enough to trust at that length.
MIN_GAZETTEER_LENGTH = 4


def _read_name_file(path, warn_hint=None):
    """Read a generated list file into normalised strings.

    Blank lines and ``#`` comments are skipped, so each file can carry a
    provenance header saying what generated it and when.
    """
    if not os.path.exists(path):
        if warn_hint:
            logger.warning("%s not found -- %s", path, warn_hint)
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def _load_gazetteer(path, hint):
    names = set()
    for line in _read_name_file(path, hint):
        normalized = normalize_entity_text(line)
        if len(normalized) >= MIN_GAZETTEER_LENGTH:
            names.add(normalized)
    return frozenset(names)


GAZETTEERS = {
    label: _load_gazetteer(
        os.path.join(GAZETTEER_DIR, filename),
        f"{label} values will not be rejected. Run: python pii_test/build_gazetteer.py")
    for label, filename in GAZETTEER_FILES.items()
}

# Kept as a name of its own: it is the oldest and largest list, and callers
# (and the harness below) report on it separately.
PLACE_NAMES = GAZETTEERS["place-name"]


# --- Cross-dataset frequency ---
#
# A personal name is confined to the dataset that is about that person: of the
# 304 genuine names in the reference VC directory, 300 appear in exactly one
# dataset and none in more than three. A value that turns up in dozens of
# unrelated ministries' files is a category -- "Dacoity" appears in 584 -- and
# this is the only rejection here that generalises past a hand-curated list.
#
# The file maps a normalised value to the number of distinct datasets it was
# seen in, for every value seen in at least two. Everything above
# CROSS_DATASET_MAX is rejected outright; the counts below it are what lets
# evaluate_dataset_flag apply a stricter bar for the dataset-level flag.
CROSS_DATASET_PATH = os.path.join(GAZETTEER_DIR, "cross_dataset_common.txt")
CROSS_DATASET_MAX = 3


def _load_cross_dataset_counts(path=CROSS_DATASET_PATH):
    """Load ``count<TAB>value`` rows into {normalised value: dataset count}."""
    counts = {}
    for line in _read_name_file(
            path, "cross-dataset frequency rejection is disabled. "
                  "Run: python pii_test/build_frequency_blocklist.py"):
        count, _, value = line.partition("\t")
        normalized = normalize_entity_text(value)
        if len(normalized) < MIN_GAZETTEER_LENGTH:
            continue
        try:
            counts[normalized] = max(counts.get(normalized, 0), int(count))
        except ValueError:
            logger.warning("Malformed line in %s: %r", path, line)
    return counts


CROSS_DATASET_COUNTS = _load_cross_dataset_counts()


def cross_dataset_frequency(entity_text):
    """How many distinct datasets this value was seen in.

    1 for anything the blocklist has never seen -- a value absent from the
    file was seen in at most one dataset, or has not been scanned yet.
    """
    return CROSS_DATASET_COUNTS.get(normalize_entity_text(entity_text), 1)


def is_hindi_text(text):
    """True if text contains any Devanagari character."""
    return bool(_DEVANAGARI_RE.search(text or ""))


_AREA_MODIFIERS = None


def _strip_area_modifiers(tokens):
    """Drop leading/trailing area words, leaving the place they qualify.

    Built lazily so it picks up the vocabularies as loaded rather than
    freezing a copy at import time.
    """
    global _AREA_MODIFIERS
    if _AREA_MODIFIERS is None:
        _AREA_MODIFIERS = (ADMINISTRATIVE_UNITS | ADMINISTRATIVE_SUFFIXES
                           | _NORMALIZED_VOCABULARIES["location-category"])
    result = list(tokens)
    while result and result[0] in _AREA_MODIFIERS:
        result.pop(0)
    while result and result[-1] in _AREA_MODIFIERS:
        result.pop()
    return result


def rejection_reason(entity_text):
    """Why this text is not a person, or None if nothing rejects it."""
    normalized = normalize_entity_text(entity_text)
    if not normalized:
        return "empty"

    compacted = compact(normalized)
    for label, vocab in _NORMALIZED_VOCABULARIES.items():
        if normalized in vocab or compacted in _COMPACT_VOCABULARIES[label]:
            return label

    for label, gazetteer in GAZETTEERS.items():
        if normalized in gazetteer:
            return label

    if CROSS_DATASET_COUNTS.get(normalized, 0) > CROSS_DATASET_MAX:
        return "cross-dataset-common"

    tokens = normalized.split()

    organisation = ORGANISATION_TOKENS.intersection(tokens)
    if organisation:
        return f"organisation ({sorted(organisation)[0]})"

    administrative = ADMINISTRATIVE_UNITS.intersection(tokens)
    if administrative:
        return f"administrative-unit ({sorted(administrative)[0]})"

    if len(tokens) > 1 and tokens[-1] in ADMINISTRATIVE_SUFFIXES:
        return f"administrative-unit ({tokens[-1]})"

    # A known place carrying a modifier is still that place: the gazetteer
    # matches exactly, so "Kharkutta Block" and "Urban Rajpura" miss it even
    # though "kharkutta" and "rajpura" are both in the list.
    stripped = _strip_area_modifiers(tokens)
    if stripped and stripped != tokens:
        candidate = " ".join(stripped)
        if candidate in PLACE_NAMES:
            return "place-name (modified)"

    for label, phrases in _VOCABULARY_PHRASES.items():
        for phrase in phrases:
            n = len(phrase)
            if any(tuple(tokens[i:i + n]) == phrase for i in range(len(tokens) - n + 1)):
                return label

    return None


# Score floor for the NER path. Regex-sourced detections are exempt (they
# carry score 1.0 and structural constraints of their own).
#
# Tuned after the switch to word-level aggregation, against the two reference
# fixtures: 31,134 real names from the VC directory (581bc9f5) as the true
# set, 2,376 census village names from Kandhamal (c1418789) as the false set,
# scoring each value by its highest surviving PERSON span and applying the
# vocabulary rejections above first:
#
#     floor   TP recall   FP kept    marginal FP removed per TP lost
#     0.60      80.0%      14.8%     -- (the old value)
#     0.64      78.2%       9.8%     0.22
#     0.66      77.1%       6.5%     0.22
#     0.68      75.8%       4.3%     0.13
#     0.70      74.6%       3.6%     0.04
#     0.72      73.0%       3.0%     0.03
#
# 0.68 is the last point where each percentage point of recall still buys a
# meaningful amount of precision; past it the trade collapses by 3x. The false
# positives that survive it are single-token village names (Gudari, Malla,
# Papasi) -- the gazetteer and the cross-dataset frequency filter are what
# remove those, not a higher floor.
#
# Note this floor is inert for the spaCy/Presidio PERSON path, which emits a
# fixed 0.85. That path needs its own evaluation -- see the plan's "out of
# scope" section.
PERSON_SCORE_FLOOR = 0.68


def filter_person_detection(entity_text, score, source="presidio"):
    """True to keep a PERSON detection."""
    if source == "regex":
        return True

    text = (entity_text or "").strip()
    if not text:
        return False

    # 1. Length filter -- kills tokenization fragments like "रा", "कि", "RA"
    if len(text) <= 3:
        return False

    # 2. Hindi stopwords, checked per token
    if is_hindi_text(text):
        tokens = text.split()
        if any(tok in HINDI_STOPWORDS for tok in tokens):
            return False
        stopword_ratio = sum(1 for tok in tokens if tok in HINDI_STOPWORDS) / max(len(tokens), 1)
        if stopword_ratio >= 0.5:
            return False

    # 3. Digits -- a person's name does not contain one. This is what removes
    #    the coded survey identifiers ("W05UT_091104700040203") that the
    #    Annual Health Survey files put in a plain "SN" column, and the crop
    #    variety codes ("RAJ 3077", "RAJ-4120") in the KCC advisory answers.
    #    Measured on the Lok Sabha member directories it costs nothing: the
    #    40 true-set values it touches are NER span run-ons ("Akali Dal
    #    1958-60", "Eleventh Lok Sabha1996-98Member"), not names.
    if _DIGIT_RE.search(text):
        return False

    # 4. Closed-vocabulary and place-name rejection
    if rejection_reason(text) is not None:
        return False

    # 5. Score floor -- NER path only; see PERSON_SCORE_FLOOR.
    if score < PERSON_SCORE_FLOOR:
        return False

    return True


# --- Indian numbering plan (DoT / TRAI) ---
#
# Toll-free and short-code prefixes. A number in these ranges is published by
# construction -- it is printed on the scheme leaflet -- so it is a contact
# point, not a personal one. The KCC advisory answers are full of them:
# 18001800110 and 18001801551 are the Kisan Call Centre, 155261 is the PM-Kisan
# helpline.
INSTITUTIONAL_PREFIXES = ("1800", "1860", "1861", "180", "155", "108", "112")

# National trunk prefix plus a 2-4 digit STD code. Also published contact
# points in this corpus (011-24300606 is the Ministry of Agriculture,
# 0612-2233555 the Bihar agriculture department), but unlike a toll-free
# number a landline *can* be someone's home, so this is a demotion rather
# than a rejection -- see PERSONAL_PHONE_ENTITIES.
_STD_LANDLINE_RE = re.compile(r"^0\d{9,10}$")
# A subscriber mobile: exactly 10 digits opening 6-9. No Indian mobile series
# begins 0-5, which is what rejects the 10-digit "5653562621".
_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def phone_digits(entity_text):
    """Digits of a phone match, with any country code stripped."""
    digits = re.sub(r"\D", "", entity_text or "")
    for cc in ("0091", "91"):
        if digits.startswith(cc) and len(digits) - len(cc) >= 10:
            return digits[len(cc):]
    return digits


def classify_phone_number(entity_text):
    """"mobile", "landline", "institutional" or None if it is not a number.

    The distinction matters because PHONE_NUMBER is trusted to flag a dataset
    on a single hit, and 44 of the 58 phone numbers in the KCC sample are
    helplines and government office lines quoted inside advisory answers.
    """
    digits = phone_digits(entity_text)
    if any(digits.startswith(p) for p in INSTITUTIONAL_PREFIXES):
        return "institutional"
    if _MOBILE_RE.match(digits):
        return "mobile"
    if _STD_LANDLINE_RE.match(digits):
        return "landline"
    return None


def filter_phone_detection(entity_text, source="presidio"):
    """True to keep a PHONE_NUMBER detection.

    Presidio's own phone recognizer matches bare integers, so a column of
    school counts headed "Schools having Functional Mobile Phones ..." yields
    "169938" as a phone number. Requiring the match to fit some slot in the
    national numbering plan is a tighter test than the old 10-13 digit count,
    and it is what rejects a 10-digit aggregate that happens to open with 5.

    Toll-free and short-code numbers are dropped rather than demoted. There is
    no case in which 1800-180-1551 is somebody's personal number -- the range
    exists to be published -- so unlike a landline it carries no information
    that a reviewer would want back.
    """
    return classify_phone_number(entity_text) in ("mobile", "landline")


def filter_detection(detection):
    """True to keep one detection. Single decision point for every caller."""
    entity_type = detection["entity_type"]
    text = detection["entity_text"]
    source = detection.get("source", "presidio")
    if entity_type == "PERSON":
        return filter_person_detection(text, detection["score"], source)
    if entity_type == "PHONE_NUMBER":
        return filter_phone_detection(text, source)
    # EMAIL, AADHAAR, PAN, FARMER_REG_ID come from regexes with structural
    # constraints and are high-precision -- kept as-is.
    return True


# --- Column-aware filtering ---
#
# Everything above judges one detection at a time, with no view of the column
# it came from or of the other detections in it. That is what let "Farmer"
# through 62 times: the KCC advisory export has a QueryText column whose values
# are call-centre dropdown labels, and "Farmer asked query on Weather" appears
# in 60 of 250 sampled rows. Each occurrence is individually plausible; sixty
# identical ones are not sixty people.
#
# The column statistics were already being computed -- run_pii_s3 builds a
# cardinality map one line after filtering -- but only to decide the dataset
# flag, never to remove a detection. This pass closes that gap.

# A value holding more than this share of its column's PERSON detections is a
# repeated label, not a person. On the Lok Sabha member directories no true
# name reaches 5% of its column; in KCC QueryText "Farmer" holds 44%.
MAX_VALUE_SHARE_OF_COLUMN = 0.05

# Below this many detections a column has no distribution to speak of and the
# share test is not applied -- three values would each hold 33%.
MIN_COLUMN_DETECTIONS = 20

# looks_like_person_name requires two tokens, which is right for a full-name
# column and wrong for a "First Name" column. Where this share of a column's
# distinct values are single tokens, treat the column as mononymic and let
# single tokens through rather than emptying it.
MONONYM_COLUMN_SHARE = 0.6


def _column_keeps(values):
    """Which of one column's PERSON values survive the column's own statistics.

    Returns a predicate over the value text. Split out from
    filter_column_context so the two rules stay readable side by side.
    """
    total = len(values)
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1

    distinct = list(counts)
    single_token = sum(1 for v in distinct
                       if len(normalize_entity_text(v).split()) == 1)
    mononymic = distinct and single_token / len(distinct) >= MONONYM_COLUMN_SHARE

    def keep(value):
        if (total >= MIN_COLUMN_DETECTIONS
                and counts[value] / total > MAX_VALUE_SHARE_OF_COLUMN):
            return False
        if looks_like_person_name(value):
            return True
        # A mononymic column is allowed single tokens, but still not the
        # things a shape test exists to catch -- digits are already gone by
        # here, so this only re-admits a bare alphabetic token.
        return bool(mononymic
                    and len(normalize_entity_text(value).split()) == 1
                    and _LETTER_ONLY_RE.match(normalize_entity_text(value)))

    return keep


def filter_column_context(detections, cardinality_by_column=None):
    """Drop PERSON detections that their own column contradicts.

    Three questions, cheapest first: is this column a roster at all
    (cardinality), does the value sit in its cell the way a name sits in one
    (cell context), and does the value repeat like a label (the column\'s own
    distribution)?

    Non-PERSON detections pass through: they come from regexes with structural
    constraints, and a repeated email address is still an email address.
    """
    ratios = cardinality_by_column or {}

    def categorical(column):
        # A column of 23 crop names over 250 rows is a controlled vocabulary,
        # and "French Bean" is one of its terms rather than somebody called
        # French. evaluate_dataset_flag has always known this; until now it
        # knew it one line too late to remove the detection.
        ratio = ratios.get(column)
        return ratio is not None and ratio <= NAME_LIKE_CARDINALITY_RATIO

    def judged(d):
        return d["entity_type"] == "PERSON" and d.get("source") != "regex"

    surviving = [d for d in detections
                 if not judged(d)
                 or (not categorical(d["column"]) and survives_cell_context(d))]

    by_column = {}
    for d in surviving:
        if judged(d):
            by_column.setdefault(d["column"], []).append(d["entity_text"])

    keeps = {col: _column_keeps(vals) for col, vals in by_column.items()}
    return [d for d in surviving
            if not judged(d) or keeps[d["column"]](d["entity_text"])]


def filter_detections(detections, cardinality_by_column=None):
    """Drop detections the filters reject.

    Two passes: the stateless per-detection filters, then the column-aware
    pass over what survives. Single entry point, so every caller gets both.

    The cell-context keys are stripped from the survivors -- they exist to be
    read by the filters and would otherwise turn up as columns in every
    exported detections CSV.
    """
    kept = [d for d in detections if filter_detection(d)]
    kept = filter_column_context(kept, cardinality_by_column)
    return [{k: v for k, v in d.items() if k not in CELL_CONTEXT_KEYS}
            for d in kept]


# --- Dataset-level flag ---

# Regex-sourced entity types, which account for 288 of 1,120,818 LOT 2
# detections and so are trusted to flag a dataset on a single hit. How much
# structure actually backs each one varies, and the trust does not:
#
#   AADHAAR_NUMBER  Verhoeff check digit, verified in pii_utils.is_valid_aadhaar
#                   before the detection is ever produced. Exact.
#   EMAIL_ADDRESS   Presidio's recognizer; format-constrained.
#   PAN_NUMBER      Fixed 5-alpha/4-digit/1-alpha layout.
#   FARMER_REG_ID   2-alpha/9-digit layout, no check digit.
#   PHONE_NUMBER    Numbering-plan slot only -- the weakest member, and the
#                   one that produced the sole false flag in the 1,000-dataset
#                   sample (a 10-digit aggregate volume in "Aggregate
#                   Evapotranspiration Volume"). It is now qualified: see
#                   PERSONAL_PHONE_KINDS.
HIGH_PRECISION_ENTITIES = {
    "PHONE_NUMBER", "EMAIL_ADDRESS", "AADHAAR_NUMBER",
    "PAN_NUMBER", "FARMER_REGISTRATION_ID",
}

# Which phone numbers are allowed to flag a dataset by themselves. A toll-free
# or short-code number is published by construction, and an STD landline
# quoted in an advisory answer is an office. Both stay in the detection table
# -- a landline can be someone's home, and suppressing it outright would lose
# that -- but neither carries a dataset flag on its own.
#
# In the KCC sample this is the difference between flagging on 58 phone
# numbers, 44 of them helplines and ministry switchboards, and flagging on the
# 14 that are actually subscriber mobiles.
PERSONAL_PHONE_KINDS = {"mobile"}

# A column of real names is nearly all-distinct. Below this ratio, PERSON
# hits are certainly a repeated category -- but above it they are not
# necessarily people, which is why this is only the first of three tests.
NAME_LIKE_CARDINALITY_RATIO = 0.5

# --- Free-text context ---
#
# A PERSON detection that *is* its cell and a PERSON detection that is nine
# characters out of an 1,800-character advisory are not the same claim. The
# second is a span the model cut out of running prose, and in the KCC export
# every one of those was scheme boilerplate: " Samman" out of "Pradhan Mantri
# Kisan Samman Nidhi Yojna", "छिड़काव करे|" out of a spraying instruction,
# "करण नरेंद्र" out of a list of wheat cultivars. What separates the two real
# names buried in the very same column is not their shape -- "RAHUL KUMAR" and
# "करण नरेंद्र" are equally name-shaped -- but what precedes them:
# "Name Of Farmer\nRAHUL KUMAR", "कटिहार, श्री दिनकर प्रसाद सिंह". So inside
# prose a name has to be introduced.

# Below this share of its cell a PERSON detection is a fragment of running
# text rather than the cell's value, and needs a naming cue to survive.
FRAGMENT_COVERAGE = 0.5

# Cells this short are labels and codes, not prose. A detection inside one is
# not a fragment however small its share, so the cue is not required -- which
# is what keeps short "Surname, Firstname" cells intact.
MIN_PROSE_CELL_LEN = 40

# How far back of the span to look for the cue. Long enough for
# "Father/Spouse/Guardian Name:", short enough that the "श्रीमान जी" opening a
# 190-character advisory does not license a name 100 characters later.
NAME_CUE_WINDOW = 48

# Relationship and honorific words that introduce a name in running text.
_LATIN_NAME_CUE_RE = re.compile(
    r"\b(?:name|s/o|d/o|w/o|c/o|shri|sri|smt|kum|mr|mrs|ms|dr|prof)\b",
    re.IGNORECASE)
# Matched as substrings, not with \b: a word boundary is defined by \w, and
# Devanagari matras are not \w, so "\bश्री\b" would never match at all.
_DEVANAGARI_NAME_CUES = (
    "नाम", "श्री", "श्रीमती", "कुमारी", "पुत्र", "पुत्री", "पत्नी", "पिता",
)

# Keys run_pii_s3 attaches for the rules above. They are filter inputs, not
# results, so filter_detections strips them off the survivors and nothing
# downstream has to know they existed.
CELL_CONTEXT_KEYS = ("cell_len", "left_context")


def _is_introduced_name(detection):
    """Whether a naming cue sits just before this span in its cell."""
    context = (detection.get("left_context") or "")[-NAME_CUE_WINDOW:]
    if _LATIN_NAME_CUE_RE.search(context):
        return True
    return any(cue in context for cue in _DEVANAGARI_NAME_CUES)


def survives_cell_context(detection):
    """True to keep a PERSON detection given where it sits in its cell.

    Detections carrying no cell context are passed through: the rule is
    evidence-based, and a caller that did not supply the evidence must not
    have its detections silently dropped.
    """
    cell_len = detection.get("cell_len")
    if not cell_len or cell_len <= MIN_PROSE_CELL_LEN:
        return True
    if len(detection["entity_text"]) / cell_len >= FRAGMENT_COVERAGE:
        return True
    return _is_introduced_name(detection)

# Cross-dataset frequency bar for corroboration. Stricter than
# CROSS_DATASET_MAX, which governs individual detections: a column whose
# values are each shared with one or two other datasets passes the detection
# filter but is still a vocabulary, not a roster.
FLAG_MAX_MEDIAN_FREQUENCY = 1

# Share of sampled values that must look like a person's name.
FLAG_MIN_NAME_SHAPE = 0.5

# Share of the column's scanned rows that must carry a surviving PERSON value
# before the column can corroborate a dataset flag.
#
# The three tests above all read the detections, and a one-off place name
# defeats every one of them: "Buxar Sadar" is two capitalised tokens
# (name-shaped), unique to its district file (corpus-rare), in a column of
# distinct values (cardinality 1.00). What separates it from a roster is not
# the value but how much of the column looks like it -- the mohfw HMIS files
# yield one or two names in 250 rows, a roster yields one per row.
#
# Measured on LOT 1: the false-positive columns run 0.004-0.008 (one hit in
# 250 rows) and the wider indicator classes reach 0.18; genuine rosters --
# msme EnterpriseName, the VC directory -- run 0.21 and up. 0.10 sits in that
# gap with roughly a factor of two either side.
#
# This withdraws a flag, never a detection: a dataset with two real names in
# a 250-row column still records them, and they remain in the export. That
# trade is deliberate and is the same one PERSONAL_PHONE_KINDS makes.
FLAG_MIN_NAME_DENSITY = 0.10

# Distinct surviving PERSON values a column needs before it corroborates.
#
# Density cannot discriminate on a short file: the mohfw district tables list
# four blocks in four rows, two of which are name-shaped, and 2/4 clears any
# density bar a roster would. But this function is about corroboration, and a
# single name-shaped value is by definition uncorroborated -- it is one span,
# from one model, in one cell.
#
# Deliberately set at the weakest defensible value. On LOT 1 batch 8 a floor
# of 2 withdraws 32 of 94 flags, 3 would withdraw 62 and 4 would withdraw 73
# -- but 3 and 4 start discarding genuine small rosters, which is a policy
# call rather than a corroboration argument. The detections are recorded
# either way, so raising this later costs nothing but a re-derivation.
FLAG_MIN_DISTINCT_NAMES = 2

# 2-5 alphabetic tokens, no digits. Honorifics and initials ("Dr. P.M.
# Mohan") survive because normalize_entity_text turns the punctuation into
# spaces, and the token cap is generous enough to absorb them.
#
# The cap is 5 rather than 4 because Hindi stacks honorifics where English
# uses one: "स्व. श्रीमती कॉर्नेलिया बाई साल्वे" is five tokens before the name
# even starts. On the Lok Sabha member directories that one token buys 5.8
# points of recall (79.9% -> 85.7% of true name detections) for 0.9 points of
# precision on the KCC false positives.
#
# _LETTER spells out what [^\W\d_] alone cannot: combining marks are not \w in
# Python's re, so a bare letter class rejects every Devanagari word for its
# matras. Same root cause as the _PUNCT_RE note above.
_LETTER = r"(?:[^\W\d_]|[" + re.escape(_COMBINING_MARKS) + r"])"
_NAME_SHAPE_RE = re.compile(
    rf"^{_LETTER}+(?:\s+{_LETTER}+){{1,4}}$", re.UNICODE)
# The same letter class over a single token, for the mononym exemption in
# filter_column_context.
_LETTER_ONLY_RE = re.compile(rf"^{_LETTER}+$", re.UNICODE)


def looks_like_person_name(text):
    """Cheap structural check: does this value have the shape of a name?

    No model involved. Two to four alphabetic tokens and no digits keeps
    "Rahul Kumar" and "Dr. P.M. Mohan" while dropping "Dacoity", "BAJRA" and
    "Crime Head (Col. 2)". A single all-caps token is the shape of a census
    village or a crime head, so bare single tokens do not qualify.
    """
    normalized = normalize_entity_text(text)
    return bool(_NAME_SHAPE_RE.match(normalized))


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if not ordered:
        return 0
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _flags_on_its_own(detection):
    """Whether one high-precision detection may set the dataset flag alone.

    Only PHONE_NUMBER is qualified; every other member of
    HIGH_PRECISION_ENTITIES carries structure that a published contact point
    cannot fake.
    """
    if detection["entity_type"] != "PHONE_NUMBER":
        return True
    return classify_phone_number(detection["entity_text"]) in PERSONAL_PHONE_KINDS


def evaluate_dataset_flag(detections, cardinality_by_column=None,
                          rows_scanned=None):
    """Decide the dataset-level pii_detected flag, with a reason.

    Anything regex-sourced flags on its own. A PERSON-only signal has to come
    from a column that passes all three of:

    1. cardinality ratio above NAME_LIKE_CARDINALITY_RATIO -- a repeated
       category is not a roster of people;
    2. its surviving PERSON values are corpus-rare (median cross-dataset
       frequency at or below FLAG_MAX_MEDIAN_FREQUENCY);
    3. at least FLAG_MIN_NAME_SHAPE of those values have the shape of a name;
    4. it carries at least FLAG_MIN_DISTINCT_NAMES distinct values -- one
       span from one model in one cell corroborates nothing;
    5. and, when the row count is known, names cover at least
       FLAG_MIN_NAME_DENSITY of the column's scanned rows -- one name in 250
       rows is a stray span, not a roster.

    Cardinality alone used to be the whole test, and on this corpus it is
    anti-correlated with truth: NCRB tables are wide-format, one row per crime
    head, so ``Crime Head`` scores a perfect 1.00 and looked maximally
    name-like. 1,948 of 1,961 flags came from that path. Criteria 2 and 3 are
    what separate "30 crime types, one per row" from "30 people, one per row",
    which cardinality by construction cannot.

    Parameters
    ----------
    detections : list[dict]
        Post-filter detections for one dataset.
    cardinality_by_column : dict[str, float] | None
        Distinct/total ratio per scanned column. Columns missing from the
        map are treated as unknown and do not corroborate on their own.
    rows_scanned : int | None
        Rows actually read from this dataset. Omitted means the density test
        is skipped rather than failed -- a caller that did not supply the
        evidence must not have its flags silently withdrawn.

    Returns
    -------
    (bool, str)
        The flag and a human-readable reason, naming the criterion that
        failed when it fails, so a flag decision stays reviewable.
    """
    if not detections:
        return False, "no detections"

    cardinality_by_column = cardinality_by_column or {}

    high_precision = [d for d in detections
                      if (d["entity_type"] in HIGH_PRECISION_ENTITIES
                          or d.get("source") == "regex")
                      and _flags_on_its_own(d)]
    if high_precision:
        types = sorted({d["entity_type"] for d in high_precision})
        columns = sorted({d["column"] for d in high_precision})
        return True, f"regex-verified {','.join(types)} in {','.join(columns[:3])}"

    values_by_column = {}
    for d in detections:
        if d["entity_type"] == "PERSON":
            values_by_column.setdefault(d["column"], []).append(d["entity_text"])
    if not values_by_column:
        return False, "no qualifying detections"

    corroborated, rejected = [], []
    for col in sorted(values_by_column):
        values = values_by_column[col]
        ratio = cardinality_by_column.get(col, 0.0)
        if ratio <= NAME_LIKE_CARDINALITY_RATIO:
            rejected.append(f"{col} (cardinality {ratio:.2f})")
            continue

        distinct = list(dict.fromkeys(values))
        frequency = _median(cross_dataset_frequency(v) for v in distinct)
        if frequency > FLAG_MAX_MEDIAN_FREQUENCY:
            rejected.append(f"{col} (median cross-dataset frequency {frequency:g})")
            continue

        name_shaped = sum(1 for v in distinct if looks_like_person_name(v)) / len(distinct)
        if name_shaped < FLAG_MIN_NAME_SHAPE:
            rejected.append(f"{col} ({name_shaped:.0%} name-shaped)")
            continue

        if len(distinct) < FLAG_MIN_DISTINCT_NAMES:
            rejected.append(f"{col} ({len(distinct)} distinct name-shaped value)")
            continue

        if rows_scanned:
            density = len(distinct) / rows_scanned
            if density < FLAG_MIN_NAME_DENSITY:
                rejected.append(f"{col} (names on {density:.1%} of rows)")
                continue

        corroborated.append(f"{col} (cardinality {ratio:.2f}, {name_shaped:.0%} name-shaped)")

    if corroborated:
        return True, f"name-like PERSON columns: {', '.join(corroborated[:3])}"
    return False, f"PERSON hits not corroborated: {', '.join(rejected[:3])}"


if __name__ == "__main__":
    # (entity_text, score, source, expected_kept, why)
    test_cases = [
        # Hindi noise
        ("भाई", 0.85, "presidio", False, "Hindi address word, not a name"),
        ("बारिश", 0.85, "presidio", False, "means 'rain'"),
        ("निधि योजना", 0.85, "presidio", False, "scheme name fragment"),
        ("कि", 0.45, "presidio", False, "tokenization fragment"),
        ("रा", 0.52, "presidio", False, "fragment of 'Rahul' or similar"),
        ("RA", 0.47, "presidio", False, "English fragment, too short"),
        # KCC agricultural vocabulary
        ("Kisan Samman", 0.85, "presidio", False, "scheme name"),
        ("Nidhi Yojna", 0.85, "presidio", False, "scheme name"),
        ("Diesel Subsidy", 0.85, "presidio", False, "program name"),
        ("Pointed Gourd", 0.85, "presidio", False, "crop"),
        ("Cartap Hydrochloride", 0.85, "presidio", False, "chemical"),
        ("Pradhan Mantri Kisan Samman Nidhi", 0.9, "presidio", False,
         "compound scheme name, matched as a phrase"),
        # LOT 1 administrative areas: block and council names that NER reads
        # as PERSON because they are short capitalised phrases.
        ("Kharkutta Block", 0.85, "presidio", False, "block, not a person"),
        ("Ranikor Block", 0.85, "presidio", False, "block, not a person"),
        ("Urban Block", 0.85, "presidio", False, "block with a category word"),
        ("Vaseitlang MC", 0.85, "presidio", False, "municipal council"),
        ("Khagaria Sadar", 0.85, "presidio", True,
         "one-off block name is name-shaped; the dataset flag, not the "
         "detection, is what withholds it"),
        # The LOT 2 offenders the previous rewrite targeted
        ("Urban", 0.997, "presidio", False, "location category, 47% of LOT 2"),
        ("URBAN", 0.997, "presidio", False, "same, different case"),
        ("Rural", 0.99, "presidio", False, "location category"),
        ("M.Phil", 0.996, "presidio", False, "qualification"),
        ("MPhil", 0.996, "presidio", False, "same, no punctuation"),
        ("Ph.D", 0.676, "presidio", False, "qualification"),
        ("B.El", 0.85, "presidio", False, "qualification"),
        ("Kendriya Vidyalaya / Central School", 0.85, "presidio", False, "school scheme"),
        ("Jawahar Navodaya Vidyalaya", 0.85, "presidio", False, "school scheme"),
        ("KHIMYANG", 0.694, "presidio", False, "census block, via gazetteer"),
        ("RAJGARH", 0.85, "presidio", False, "district, via gazetteer"),
        ("JAISALMER", 0.85, "presidio", False, "district, via gazetteer"),
        # Organisations found in ambiguous "name" columns (LOT 2 re-run)
        ("Gujarat Vidyapith", 0.85, "presidio", False, "university"),
        ("Ramakrishna Mission", 0.85, "presidio", False, "organisation"),
        ("Sanskrit Vishwavidyalaya", 0.85, "presidio", False, "university"),
        ("Kalu Kanya Mahavidhyalya", 0.85, "presidio", False, "college"),
        ("Nidhi Hostel", 0.85, "presidio", False, "hostel, not a person"),
        ("Shri M. T. Doshi Kanya Chhatralaya", 0.85, "presidio", False,
         "hostel named after a person -- still a building"),
        ("SAMAJ WADI", 0.85, "presidio", False, "organisation"),
        # Round 2: the families the harvested gazetteers cover. Every one of
        # these was a whole-word false positive that no list matched before,
        # because the stored spans were subword fragments ("Robb", "lerks").
        ("Dacoity", 0.9, "presidio", False, "NCRB crime head"),
        ("Robbery", 0.9, "presidio", False, "NCRB crime head -- stored as 'Robb' before"),
        ("Arson", 0.9, "presidio", False, "NCRB crime head"),
        ("Clerks", 0.9, "presidio", False, "NCO occupation -- stored as 'lerks' before"),
        ("Stock Clerks", 0.9, "presidio", False, "NCO occupation"),
        ("BAJRA", 0.9, "presidio", False, "crop, largest single commodity FP"),
        ("PADDY", 0.9, "presidio", False, "crop"),
        ("POTTERY", 0.9, "presidio", False, "handicraft commodity"),
        ("Hindi", 0.9, "presidio", False, "language, from Mother Tongue Name"),
        ("Assamese", 0.9, "presidio", False, "language"),
        ("Hilsa Ilisha", 0.9, "presidio", False, "fish species"),
        ("JHUNJHUNUN", 0.9, "presidio", False,
         "district -- only reaches the gazetteer once un-fragmented"),
        # Round 2: score floor
        ("Some Person", PERSON_SCORE_FLOOR - 0.01, "presidio", False,
         "below the tuned score floor"),
        ("Some Person", PERSON_SCORE_FLOOR, "presidio", True, "exactly at the floor"),
        # True positives that must survive
        ("Rahul Kumar", 0.92, "presidio", True, "real English name"),
        ("Vidya Balan", 0.9, "presidio", True,
         "'vidya' is a personal name -- must not be an organisation token"),
        ("Gyan Prakash", 0.9, "presidio", True, "same for 'gyan'"),
        ("Shri Ram Sharma", 0.9, "presidio", True, "honorific, still a person"),
        ("राहुल कुमार", 0.88, "presidio", True, "real Hindi name"),
        ("Maurice Fernandes", 0.9, "presidio", True,
         "must not be rejected for containing the crop 'rice'"),
        ("Priya Sharma", 0.75, "presidio", True, "real name, moderate score"),
        ("M.A. AKHIB AHMED", 0.9, "presidio", True,
         "initials, not the qualification 'M.A.' -- single-letter phrases "
         "must not match inside a name"),
        ("9876543210", 1.0, "regex", True, "phone via regex"),
        ("ABCDE1234F", 1.0, "regex", True, "PAN via regex"),
        ("Dacoity", 1.0, "regex", True, "regex source is exempt from every entity rule"),
    ]

    print(f"{'Entity':<38} {'Score':>6} {'Source':<10} {'Kept?':<6} {'Expected':<9} OK?")
    print("-" * 88)
    failures = 0
    for entity, score, source, expected, _why in test_cases:
        kept = filter_person_detection(entity, score, source)
        ok = kept == expected
        failures += not ok
        print(f"{entity:<38} {score:>6.2f} {source:<10} {str(kept):<6} {str(expected):<9} "
              f"{'yes' if ok else 'NO'}")

    # Phone-number length, from the "Schools having Functional Mobile
    # Phones ..." count columns that a force token pulls into the scan.
    print()
    phone_cases = [
        ("9866295303", True, "10-digit Indian mobile"),
        ("+91 98662 95303", True, "with country code"),
        ("169938", False, "school count, not a phone"),
        ("1644", False, "school count"),
        ("356819", False, "school count"),
    ]
    for text, expected, _why in phone_cases:
        kept = filter_phone_detection(text)
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} phone {text!r:20} -> {kept} (expected {expected})")

    # Aadhaar: the shape regex alone accepts any 12-digit code, so the
    # Verhoeff check is what earns AADHAAR_NUMBER its place in
    # HIGH_PRECISION_ENTITIES. Exercised through regex_pii_matches rather than
    # the validator directly, so the wiring is covered too.
    print()
    try:
        from pii_utils import regex_pii_matches
    except Exception as exc:                                    # pragma: no cover
        print(f"skipped aadhaar cases: pii_utils not importable ({exc})")
        aadhaar_cases = []
    else:
        aadhaar_cases = [
            ("234567890124", True, "valid check digit"),
            ("2345 6789 0124", True, "same number, printed in groups"),
            ("Aadhaar: 987654321096", True, "embedded in a sentence"),
            ("234512345678", False, "right shape, wrong check digit"),
            ("999999999999", False, "repeated-digit filler; passes Verhoeff, is a palindrome"),
            ("333333333333", False, "the other repdigit Verhoeff accepts"),
            ("202512345678", False, "year-prefixed serial, the common FP shape"),
            ("123456789012", False, "leading 1 -- never issued"),
            ("23456789012", False, "11 digits"),
        ]
        for text, expected, _why in aadhaar_cases:
            found = any(label == "AADHAAR_NUMBER"
                        for label, *_ in regex_pii_matches(text))
            ok = found == expected
            failures += not ok
            print(f"{'yes' if ok else 'NO ':<4} aadhaar {text!r:20} -> {found} "
                  f"(expected {expected})")

    # Column classification: the negative-bigram rule and the split force
    # bypass. Imported here rather than at module scope so pii_filters stays
    # importable without torch/presidio installed.
    print()
    try:
        from pii_utils import classify_column_name
    except Exception as exc:                                    # pragma: no cover
        print(f"skipped column cases: pii_utils not importable ({exc})")
        column_cases = []
    else:
        column_cases = [
            ("Sub District Head Quarter (Name)", "skip", "census geography, 8,434 detections"),
            ("District Head Quarter (Name)", "skip", "census geography, 3,889 detections"),
            ("Head Quarters Name", "skip", "plural form of the same bigram"),
            ("Mother Tongue Name", "skip", "census language list, 2,005 detections"),
            ("MotherTongueName", "skip", "same header, camelCase"),
            ("mothertonguename", "skip", "same header, glued"),
            ("Name of Vice-Chancellor/ Director/ Principal/ Head", "force-person",
             "the genuine name column the person-token override exists for"),
            ("District_Officer_Name", "force-person",
             "'district' skip token overridden by 'officer'"),
            ("Mother Name", "force-person", "'mother' with no negative bigram"),
            ("Name of Head Master", "force-person", "'head' with no negative bigram"),
            ("Contact No", "force-pii", "int64 phone column must bypass the dtype checks"),
            ("E-mail id", "force-pii", "'id' must not skip it"),
            ("Village Name", "skip", "geography"),
        ]
        for column, expected, _why in column_cases:
            decision, reason = classify_column_name(column)
            ok = decision == expected
            failures += not ok
            print(f"{'yes' if ok else 'NO ':<4} column {column!r:52} -> {decision} ({reason})")

    # Devanagari normalisation. Combining marks are not \w in Python's re, so
    # the old punctuation class shattered every matra into a space.
    print()
    script_cases = [
        ("दिनकर प्रसाद सिंह", 3, True, "3-token Hindi name, was 7 fragments"),
        ("स्व. श्रीमती कॉर्नेलिया बाई साल्वे", 5, True,
         "stacked honorifics -- the case the token cap was widened to 5 for"),
        ("माध्यम", 1, False, "single Hindi word is not name-shaped"),
        ("G.L.Puram", 3, True, "initials still split on punctuation"),
        ("Dr. P.M. Mohan", 4, True, "English honorific plus initials"),
    ]
    for text, tokens, shaped, _why in script_cases:
        n = normalize_entity_text(text)
        ok = len(n.split()) == tokens and looks_like_person_name(text) == shaped
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} normalise {text!r:40} -> "
              f"{len(n.split())} token(s), shaped={looks_like_person_name(text)}")

    # Numbering plan. 44 of the 58 phone numbers in the KCC sample are
    # helplines and ministry switchboards quoted inside advisory answers.
    print()
    phone_cases = [
        ("7739668923", "mobile", True, "the genuine one in the KCC sample"),
        ("+91-8102372649", "mobile", True, "country code stripped"),
        ("99346 93130", "mobile", True, "printed with a space"),
        ("18001800110", "institutional", False, "Kisan Call Centre toll-free"),
        ("1800-1800-110", "institutional", False, "same number, hyphenated"),
        ("155261", "institutional", False, "PM-Kisan short code"),
        ("011-24300606", "landline", True, "Ministry of Agriculture -- kept, but demoted"),
        ("0612-2233555", "landline", True, "Bihar agriculture department"),
        ("5653562621", None, False, "10 digits opening 5 -- no such mobile series"),
        ("169938", None, False, "a school count, not a phone"),
    ]
    for text, kind, kept, _why in phone_cases:
        got = classify_phone_number(text)
        ok = got == kind and filter_phone_detection(text) == kept
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} phone {text!r:18} -> {str(got):14} "
              f"kept={filter_phone_detection(text)}")

    # Column-aware pass. These are the rules that need more than one detection
    # to decide, so each case is a whole column.
    print()
    def _person_column(column, values):
        return [{"column": column, "entity_type": "PERSON", "entity_text": v,
                 "score": 0.85, "source": "presidio"} for v in values]

    column_context_cases = [
        ("QueryText", ["Farmer"] * 62 + ["Weather"] * 60
         + ["Rahul Kumar", "Amar Singh", "दिनकर प्रसाद सिंह"], 3,
         "boilerplate label repeated 60x is not 60 people"),
        ("Member Name",
         [f"Shri {first} {last}" for first in
          ("Amar", "Rahul", "Suresh", "Vijay", "Mohan", "Arun", "Kiran", "Deepak")
          for last in ("Kumar", "Singh", "Sharma", "Yadav", "Patel")], 40,
         "an all-distinct roster is untouched"),
        ("First Name", ["Alphonse", "Devi", "Chauhan", "Ghanshyam", "Dave",
                        "Indira", "Ramesh", "Sunita", "Kavita", "Mohan",
                        "Priya", "Rajesh", "Anita", "Vijay", "Suresh",
                        "Meena", "Arun", "Geeta", "Kiran", "Deepa",
                        "Nidhi"], 21,
         "mononym column keeps single tokens rather than emptying"),
        ("Notes", ["Rahul Kumar", "Farmer", "Amar Singh"], 2,
         "under 20 detections the share test is skipped, but shape still applies"),
        ("Notes", ["Rahul Kumar"] * 3 + ["Amar Singh"], 4,
         "a value repeated 3 of 4 times survives -- too few to judge a share"),
    ]
    # Where a PERSON span sits inside its cell, and whether its column is a
    # roster at all. Both taken from the KCC advisory export -- the cells are
    # the real ones, truncated only where length is not the point.
    print()
    kcc_answer = (" जिन किसान का बैंक खाता एवं NPCI से नहीं जुड़ा है वैसे किसान "
                  "तुरंत पोस्ट ऑफिस जा कर खाता खुलवाएं |\n\nRegistration NO.\n"
                  "BR259782384\nName Of Farmer\nRAHUL KUMAR\nAddress\n"
                  "Parasrampur\nFather/Spouse/Guardian Name:\nDEVENDRA SINGH\n"
                  "Mobile No\n7739668923\n")
    query_text = "Query Related to Pradhan Mantri Kisan Samman Nidhi Yojna "
    advisory = ("किसान भाई  बैगन के फसल में तना और फल छेदक किट के नियंत्रण के लिए "
                "इमामेक्टिन बेंजोएट 5% SG 4 ग्राम प्रति 10 लीटर पानी में घोल बनाकर "
                "छिड़काव  करे| ")
    cell_context_cases = [
        (kcc_answer, "RAHUL KUMAR", True,
         "0.8% of its cell, but introduced by 'Name Of Farmer'"),
        (kcc_answer, "DEVENDRA SINGH", True,
         "introduced by 'Father/Spouse/Guardian Name:'"),
        (" कटिहार, श्री दिनकर प्रसाद सिंह                      9431818755 ",
         "दिनकर प्रसाद सिंह", True, "introduced by the honorific श्री"),
        (query_text, "Samman", False, "a fragment of scheme boilerplate"),
        (query_text, "Query Related", False,
         "23% of the cell and nothing introduces it"),
        (advisory, "छिड़काव  करे|", False, "a fragment of a spraying instruction"),
        ("गेहूं की- डीबीडबल्यू 303 (करण वैष्णवी), करण नरेंद्र आदि किस्में बोयें",
         "करण नरेंद्र", False, "a wheat cultivar listed among cultivars"),
        ("Rahul Kumar", "Rahul Kumar", True, "the whole of a short cell"),
        ("Kumar, Rahul (Bihar)", "Rahul", True,
         "a short cell is a label, not prose -- no cue required"),
    ]
    for cell, entity, expected, why in cell_context_cases:
        start = cell.index(entity)
        detection = {"column": "KccAns", "entity_type": "PERSON",
                     "entity_text": entity, "score": 0.85, "source": "presidio",
                     "cell_len": len(cell),
                     "left_context": cell[max(0, start - 64):start]}
        got = survives_cell_context(detection)
        ok = got == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} cell-context {entity[:22]!r:26} "
              f"-> {str(got):<5} ({why})")

    print()
    cardinality_cases = [
        ("Crop", ["French Bean", "Beet Root"], {"Crop": 0.09}, 0,
         "23 crop names over 250 rows is a vocabulary, not a roster"),
        ("Crop", ["French Bean", "Beet Root"], {}, 2,
         "an unmeasured column is not judged categorical"),
        ("Member Name", ["Rahul Kumar", "Amar Singh"], {"Member Name": 0.98}, 2,
         "an all-distinct roster is untouched"),
    ]
    for column, values, ratios, expected, why in cardinality_cases:
        kept = len(filter_column_context(_person_column(column, values), ratios))
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} cardinality  {column!r:14} "
              f"{len(values)} -> {kept} (expected {expected}; {why})")

    print()
    for column, values, expected, _why in column_context_cases:
        kept = len(filter_column_context(_person_column(column, values)))
        ok = kept == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} column-context {column!r:14} "
              f"{len(values):>3} -> {kept:>3} (expected {expected})")

    # Dataset-level flag. The frequency map is injected per case so these stay
    # deterministic regardless of what the generated blocklist currently holds.
    print()
    flag_cases = [
        ("regex hit alone flags",
         [{"entity_type": "PHONE_NUMBER", "column": "Contact", "entity_text": "9866295303",
           "source": "regex"}],
         {}, {}, True),
        ("PERSON in a name-like column flags",
         [{"entity_type": "PERSON", "column": "Father_Name", "entity_text": n,
           "source": "presidio"}
          for n in ("Rahul Kumar", "Priya Sharma", "Amit Verma")],
         {"Father_Name": 0.94}, {}, True),
        ("PERSON in a categorical column does not flag",
         [{"entity_type": "PERSON", "column": "Location", "entity_text": "Urban",
           "source": "presidio"}],
         {"Location": 0.03}, {}, False),
        ("PERSON in an unmeasured column does not flag alone",
         [{"entity_type": "PERSON", "column": "Mystery", "entity_text": "Rahul Kumar",
           "source": "presidio"}],
         {}, {}, False),
        ("wide-format vocabulary does not flag despite ratio 1.00",
         [{"entity_type": "PERSON", "column": "Crime Head", "entity_text": t,
           "source": "presidio"}
          for t in ("Extortion", "Kidnapping", "Rioting", "Cheating")],
         {"Crime Head": 1.00},
         {"extortion": 400, "kidnapping": 380, "rioting": 360, "cheating": 350},
         False),
        ("single-token village names do not flag despite ratio 1.00",
         [{"entity_type": "PERSON", "column": "VILLNAME", "entity_text": t,
           "source": "presidio"}
          for t in ("Gudari", "Papasi", "Bandika", "Pikusi")],
         {"VILLNAME": 1.00}, {}, False),
        ("a real roster still flags",
         [{"entity_type": "PERSON", "column": "Name of Awardee", "entity_text": t,
           "source": "presidio"}
          for t in ("Rahul Kumar", "Priya Sharma", "Dr. P.M. Mohan", "Amit Verma")],
         {"Name of Awardee": 0.98}, {}, True),
        ("no detections", [], {}, {}, False),
        # Density: the one-off place names that defeat all three of the
        # earlier tests. Two names in a 250-row column is not a roster.
        ("sparse one-off place names do not flag",
         [{"entity_type": "PERSON", "column": "Indicator", "entity_text": t,
           "source": "presidio"}
          for t in ("Buxar Sadar", "Chowki Chowra")],
         {"Indicator": 1.00}, {}, False, 250),
        ("a dense roster still flags at the same row count",
         [{"entity_type": "PERSON", "column": "Name",
           "entity_text": f"Rahul {chr(97 + i // 26)}{chr(97 + i % 26)}sharma",
           "source": "presidio"} for i in range(40)],
         {"Name": 0.98}, {}, True, 250),
        ("a lone name-shaped value does not corroborate",
         [{"entity_type": "PERSON", "column": "Indicator",
           "entity_text": "Mipi Anini", "source": "presidio"}],
         {"Indicator": 1.00}, {}, False, 4),
        ("density is skipped when the row count is unknown",
         [{"entity_type": "PERSON", "column": "Indicator", "entity_text": t,
           "source": "presidio"}
          for t in ("Buxar Sadar", "Chowki Chowra")],
         {"Indicator": 1.00}, {}, True, None),
    ]
    for label, dets, card, frequencies, expected, *rest in flag_cases:
        rows = rest[0] if rest else None
        saved = dict(CROSS_DATASET_COUNTS)
        CROSS_DATASET_COUNTS.update(frequencies)
        try:
            flagged, reason = evaluate_dataset_flag(dets, card, rows_scanned=rows)
        finally:
            CROSS_DATASET_COUNTS.clear()
            CROSS_DATASET_COUNTS.update(saved)
        ok = flagged == expected
        failures += not ok
        print(f"{'yes' if ok else 'NO ':<4} {label:<52} -> {flagged} ({reason})")

    print()
    total = (len(cell_context_cases) + len(cardinality_cases)
             + len(test_cases) + len(phone_cases) + len(aadhaar_cases)
             + len(column_cases) + len(script_cases) + len(phone_cases)
             + len(column_context_cases) + len(flag_cases))
    print(f"{total - failures}/{total} passed, {failures} failed")
    for label, names in sorted(GAZETTEERS.items()):
        print(f"gazetteer {label:<12} {len(names):>6,} entries")
    print(f"cross-dataset counts   {len(CROSS_DATASET_COUNTS):>6,} values "
          f"({sum(1 for c in CROSS_DATASET_COUNTS.values() if c > CROSS_DATASET_MAX):,} "
          f"above CROSS_DATASET_MAX={CROSS_DATASET_MAX})")
    print(f"PERSON_SCORE_FLOOR     {PERSON_SCORE_FLOOR}")
    raise SystemExit(1 if failures else 0)
