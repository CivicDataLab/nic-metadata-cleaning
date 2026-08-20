
import argparse
import csv
import re
from pathlib import Path

import duckdb

DB_PATH = str(Path(__file__).resolve().parent.parent / "metadata.db")
TABLE = "dublin_core_metadata"
# Column holding the comma-joined cleaned file headers. Present on
# dublin_core_metadata and dublin_core_remaining (filled by
# fill_headers_remaining.py). Used only as a *reported* coherence signal —
# never as a grouping key: on Rajya Sabha data there are ~28k distinct header
# signatures across ~33k rows, so blocking on it would shatter every group.
HEADER_COL = "Conforms To"
MERGE_THRESHOLD = 2
FUZZY_THRESHOLD = 92   # token_sort_ratio; 92 merges surface variants without
                       # merging genuinely different collections


# ── geographic constants ──────────────────────────────────────────────────────

state_ut = [
    "Andaman and Nicobar Islands", "A & N Islands", "A and N Islands",
    "Andhra Pradesh", "Andhra Pradesh Old",
    "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
    "Chhattisgarh", "Dadra & Nagar Haveli", "Dadra and Nagar Haveli",
    "Daman & Diu", "Daman and Diu", "Delhi",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
    "Jammu and Kashmir", "Jammu & Kashmir", "Jharkhand",
    "Karnataka", "Kerala", "Lakshadweep",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry",
    "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
    "All India", "India",
    "M/O Defence", "M/O Railways",
    # Post-2019 reorganisation, and the spellings batch-2 titles actually use.
    # _STATE_ALT sorts by length descending, so the merged UT name is tried
    # before its constituent "Dadra and Nagar Haveli" / "Daman and Diu" forms.
    "Ladakh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Dadra & Nagar Haveli & Daman & Diu",
    "NCT of Delhi", "NCT OF DELHI", "Delhi NCT",
    "Andaman & Nicobar Islands", "Andamans", "Nicobars",
    "Jammu & Kashmir Old", "Pondicherry",
    "Orissa", "Uttaranchal",   # pre-rename spellings still in older titles
]

_STATE_ALT = "|".join(
    re.escape(s) for s in sorted(state_ut, key=len, reverse=True)
)


# ── date / time constants ─────────────────────────────────────────────────────

_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_YEAR = r"\d{4}"
_YR   = r"\d{4}(?:-\d{2,4})?"   # bare year or year-range e.g. 2015-16

# Flexible MONTH-to-YEAR separator. Real OGD titles use any of:
#   "February 2014"   (space)
#   "February, 2014"  (comma + space)   ← most common in HMIS/RHS reports
#   "February-2014"   (bare hyphen, no surrounding whitespace)
# A character class covers all three uniformly: any run of whitespace, comma,
# or hyphen. Earlier versions hard-coded "-" between MONTH and YEAR, so the
# comma form went unmatched and "upto February" / "for February" leaked into
# the collection base, fragmenting collections across states + months.
_MY_SEP = r"[\s,\-]+"

# Constant parentheticals that identify a data programme rather than a variable
# slot. Deliberately NOT $-anchored: real titles put them mid-string, as in
# "… of Telangana (UDISE plus) during 2019-20", where they sit between the
# geographic and temporal tails and block both sets of $-anchored rules.
# normalize_title() detaches the marker wherever it occurs and re-attaches it
# to the finished base.
_CONST_SUFFIX = re.compile(
    r"\s*\(\s*(?:UDISE\s*\+?\s*plus|UDISE\+?|AISHE|NAS|PGI)\s*\)",
    re.I,
)


# Public aliases so sibling modules (e.g. utils/title_components.py) can
# reuse the same closed-list state regex and date primitives without
# duplicating definitions that have been tuned against real titles.
STATE_ALT  = _STATE_ALT
MONTH_RE   = _MONTH
YEAR_RE    = _YEAR
YR_RE      = _YR
MY_SEP_RE  = _MY_SEP


# ── contrasting word pairs that must NEVER be merged ─────────────────────────
# If two normalised bases differ specifically on one of these pairs they
# represent genuinely different datasets (e.g. rural hospitals != urban hospitals).

_CONTRASTING_PAIRS: list[frozenset] = [
    frozenset({"rural",     "urban"}),
    frozenset({"male",      "female"}),
    frozenset({"boys",      "girls"}),
    frozenset({"north",     "south"}),
    frozenset({"east",      "west"}),
    frozenset({"central",   "peripheral"}),
    frozenset({"public",    "private"}),
    frozenset({"scheduled", "general"}),
    frozenset({"sc",        "st"}),
]


# ── Option A helpers ──────────────────────────────────────────────────────────

def _normalize_key(base: str) -> str:
    """
    Collapse surface variants before grouping so that titles differing only
    in casing, separators, or plural/singular map to the same bucket key.

    Applied to the already date/geo-stripped base string.
    """
    t = base.lower()

    # "state/ut-wise" / "state/ut wise" / "state/Ut-wise" → canonical form
    t = re.sub(r'state\s*/\s*u\.?t\.?\s*[-\u2013]?\s*wise', 'state/ut-wise', t)

    # normalise spacing around parentheses: "centres(CHCs)" → "centres (chcs)"
    t = re.sub(r'\s*\(\s*', ' (', t)
    t = re.sub(r'\s*\)\s*', ') ', t)

    # singular/plural: "centres" → "centre"
    t = re.sub(r'\bcentres\b', 'centre', t)

    # collapse whitespace and strip trailing punctuation artefacts
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'[\s\-:,;&]+$', '', t).strip()

    return t


# A restricted-universe modifier: "… for SC, 2011" covers Scheduled Castes
# only, while the otherwise-identical title covers everyone. Stacking the two
# double-counts the subset inside the total.
#
# Matched as a PHRASE, never as a bare token — Indian district names embed
# these words (Kamrup-Rural, Bengaluru Urban, Mumbai Suburban), and bare-token
# matching flagged 47 legitimate district groups as violations.
_SUBSET_RE = re.compile(
    r"\bfor\s+(SC|ST|Scheduled\s+Castes?|Scheduled\s+Tribes?|Rural|Urban|"
    r"Boys|Girls|Males?|Females?)\b",
    re.I,
)


def _subset_marker(text: str) -> str | None:
    """The restricted universe a title is limited to, or None for the superset."""
    m = _SUBSET_RE.search(text or "")
    return re.sub(r"\s+", " ", m.group(1)).lower() if m else None


def _has_contrasting_difference(a: str, b: str) -> bool:
    """
    Return True if keys a and b differ on a known contrasting word pair.
    Such pairs must not be merged regardless of fuzzy score.
    e.g. "in rural areas" vs "in urban areas" → True (block merge)
    """
    # Subset vs superset. The paired-token test below cannot catch this: it
    # requires a contrasting token on BOTH sides, and "… for SC" vs "…" has one
    # on neither-but-one. The two are ~95% similar, far above FUZZY_THRESHOLD.
    if _subset_marker(a) != _subset_marker(b):
        return True

    tokens_a = set(re.findall(r'\b\w+\b', a))
    tokens_b = set(re.findall(r'\b\w+\b', b))
    only_in_a = tokens_a - tokens_b
    only_in_b = tokens_b - tokens_a
    for pair in _CONTRASTING_PAIRS:
        if only_in_a & pair and only_in_b & pair:
            return True
    return False


# Words that begin a district name whose last word is itself a state name:
# "North Tripura", "South Goa", "New Delhi", "Koch Bihar". Stripping the bare
# trailing state out of those leaves a fragment ("… for South") that collides
# across states — South Goa and South Tripura would land in one collection.
_DISTRICT_QUALIFIERS = frozenset({
    "north", "south", "east", "west", "new", "old",
    "upper", "lower", "central", "koch",
})

_BARE_STATE_RE = re.compile(rf"\s+({_STATE_ALT})\s*$", re.I)


def _strip_bare_state(t: str) -> str:
    """
    Strip a trailing state name that has no preposition in front of it, unless
    it is the tail of a multi-word district name (see _DISTRICT_QUALIFIERS).
    """
    m = _BARE_STATE_RE.search(t)
    if not m:
        return t
    before = t[: m.start()].strip()
    words = before.split()
    if words and words[-1].lower() in _DISTRICT_QUALIFIERS:
        return t   # "… for North Tripura" — Tripura belongs to the district
    return before


# ── core normalisation ────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Strip temporal and geographic variable parts from a title."""
    t = title.strip()

    # Constant trailing parentheticals ("… of Telangana (UDISE plus)") are part
    # of the dataset's identity, not a variable slot, but sitting at the end
    # they block every $-anchored rule below. Detach now, re-attach at the end.
    suffix = ""
    m = _CONST_SUFFIX.search(t)
    if m:
        suffix = " " + m.group(0).strip()
        t = (t[: m.start()] + " " + t[m.end():]).strip()

    # Temporal and geographic stripping alternate until neither changes:
    # removing a trailing state can expose a temporal tail ("Primary Census
    # Abstract 2011 - Punjab" → "… 2011") and vice versa, so a single pass of
    # each is not enough.
    outer_changed = True
    while outer_changed:
        outer_prev = t

        # ── Pass 1: temporal stripping ────────────────────────────────────────
        changed = True
        while changed:
            prev = t

            # Quarter patterns MUST come before the generic "for MONTH YEAR to MONTH YEAR"
            # rule, otherwise the generic rule eats the date portion first and leaves
            # "for Quarter N:" as an unstrippable fragment.

            # "for Quarter N: MONTH[, /-]YEAR to MONTH[, /-]YEAR"
            t = re.sub(
                rf"\s+for\s+Quarter\s+\d+\s*:\s*{_MONTH}{_MY_SEP}{_YEAR}\s+to\s+{_MONTH}{_MY_SEP}{_YEAR}\s*$",
                "", t, flags=re.I,
            )
            # bare "Quarter N: MONTH[, /-]YEAR to MONTH[, /-]YEAR" (without leading "for")
            t = re.sub(
                rf"\s+Quarter\s+\d+\s*:\s*{_MONTH}{_MY_SEP}{_YEAR}\s+to\s+{_MONTH}{_MY_SEP}{_YEAR}\s*$",
                "", t, flags=re.I,
            )

            # "upto MONTH[, /-]YEAR"   (separator may be comma+space, space, or hyphen)
            t = re.sub(rf"\s+upto\s+{_MONTH}{_MY_SEP}{_YR}\s*$", "", t, flags=re.I)

            # "for YEAR(-YY)? & YEAR(-YY)?" or "for YEAR(-YY)? and YEAR(-YY)?"
            t = re.sub(rf"\s+for\s+{_YR}\s*(?:&|and)\s*{_YR}\s*$", "", t, flags=re.I)

            # "[for ]Financial Year: YEAR"
            t = re.sub(rf"\s+(?:for\s+)?Financial\s+Year:\s*{_YR}\s*$", "", t, flags=re.I)

            # "for MONTH to MONTH during YEAR"
            t = re.sub(
                rf"\s+for\s+{_MONTH}\s+to\s+{_MONTH}\s+during\s+{_YR}\s*$",
                "", t, flags=re.I,
            )

            # "(MONTH to MONTH)"  e.g. "(April to June)", "(April to December)"
            # RCH-style trailing period range. Stripped first so the inner "for the year"
            # and bare-year rules below can then anchor at the new $.
            t = re.sub(
                rf"\s*\(\s*{_MONTH}\s+to\s+{_MONTH}\s*\)\s*$",
                "", t, flags=re.I,
            )

            # "for the year YR (and|&) YR"   e.g. "for the year 2011-12 and 2010-11"
            # MUST be its own rule: the existing "for YR (and|&) YR" pattern below does
            # not allow the literal "the year" between "for" and the first year token.
            t = re.sub(
                rf"\s+for\s+the\s+year\s+{_YR}\s*(?:&|and)\s*{_YR}\s*$",
                "", t, flags=re.I,
            )

            # "for the year YR"   single-year variant of the above
            t = re.sub(rf"\s+for\s+the\s+year\s+{_YR}\s*$", "", t, flags=re.I)

            # "for MONTH[, /-]YEAR(-YY)?" (single month-year at end; comma/space/hyphen sep)
            t = re.sub(rf"\s+for\s+{_MONTH}{_MY_SEP}{_YR}\s*$", "", t, flags=re.I)

            # "for MONTH[, /-]YEAR to MONTH[, /-]YEAR" (generic quarterly range)
            t = re.sub(
                rf"\s+for\s+{_MONTH}{_MY_SEP}{_YEAR}\s+to\s+{_MONTH}{_MY_SEP}{_YEAR}\s*$",
                "", t, flags=re.I,
            )

            # "- MONTH[, /-]YEAR to MONTH[, /-]YEAR" (RCH style)
            t = re.sub(
                rf"\s*-\s*{_MONTH}{_MY_SEP}{_YEAR}\s+to\s+{_MONTH}{_MY_SEP}{_YEAR}\s*$",
                "", t, flags=re.I,
            )

            # "(as on [31st ]MONTH[,] YEAR)"
            t = re.sub(
                rf"\s*\(as\s+on\s+(?:\d+\w*\s+)?{_MONTH},?\s*{_YEAR}\)\s*$",
                "", t, flags=re.I,
            )

            # "as on [31st ]MONTH[,] YEAR"
            t = re.sub(
                rf"\s+as\s+on\s+(?:\d+\w*\s+)?{_MONTH},?\s*{_YEAR}\s*$",
                "", t, flags=re.I,
            )

            # "from YEAR to YEAR"
            t = re.sub(rf"\s+from\s+{_YEAR}\s+to\s+{_YEAR}\s*$", "", t, flags=re.I)

            # "- YEAR to YEAR"
            t = re.sub(rf"\s*-\s*{_YEAR}\s+to\s+{_YEAR}\s*$", "", t)

            # "during YEAR-YY"
            t = re.sub(rf"\s+during\s+{_YR}\s*$", "", t, flags=re.I)

            # "- SRS during YEAR-YEAR"
            t = re.sub(rf"\s*-\s*SRS\s+during\s+{_YR}\s*$", "", t, flags=re.I)

            # ", YEAR"
            t = re.sub(rf"\s*,\s*{_YR}\s*$", "", t)

            # "- YEAR(-YY)?" or "- RHS YEAR"
            t = re.sub(rf"\s*-\s*(?:RHS\s+)?{_YR}\s*$", "", t)

            # bare trailing " YEAR(-YY)?"  — MOST GENERAL, must be last among date rules
            t = re.sub(rf"\s+{_YR}\s*$", "", t)

            # dangling preposition left after temporal removal — always last in loop
            # e.g. "Item-wise HMIS report of Haryana for" → strips the trailing "for"
            # so the geographic loop can then match "of Haryana"
            t = re.sub(
                r'\s+(?:for|of|in|during|from|and|&|to|at|by|with|upto)\s*$',
                '', t, flags=re.I,
            )

            changed = t != prev

        # ── Pass 2: geographic stripping ──────────────────────────────────────────
        # NOTE: Only known State/UT names are stripped here.
        # The previous "for SINGLE_WORD" bare-district heuristic has been removed
        # because it incorrectly stripped meaningful type suffixes like
        # "for Sub Centres", "for PHCs", "for IPD Attendance" etc.
        # Residual multi-word district names are handled downstream by
        # _merge_into_parent() and the fuzzy merge pass.

        changed = True
        while changed:
            prev = t

            # "(All) of STATE"
            t = re.sub(rf"\s*\(All\)\s+of\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

            # "in STATE"
            t = re.sub(rf"\s+in\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

            # "in/for DISTRICT District of STATE" — the UDISE shape. The
            # explicit "District" keyword bounds the wildcard, so multi-word
            # district names stay intact without overshooting the subject.
            t = re.sub(
                rf"\s+(?:in|for)\s+.+?\s+District\s+of\s+({_STATE_ALT})\s*$",
                "", t, flags=re.I,
            )

            # "of the district DISTRICT (STATE)"
            t = re.sub(
                rf"\s+of\s+the\s+district\s+[^()]+\(\s*({_STATE_ALT})(?:\s+Old|\s+New)?\s*\)\s*$",
                "", t, flags=re.I,
            )

            # "of DISTRICT (STATE [Old/New]?)"
            t = re.sub(
                rf"\s+of\s+[^()]+\(\s*({_STATE_ALT})(?:\s+Old|\s+New)?\s*\)\s*$",
                "", t, flags=re.I,
            )

            # "for DISTRICT (STATE [Old/New]?)"
            t = re.sub(
                rf"\s+for\s+[^()]+\(\s*({_STATE_ALT})(?:\s+Old|\s+New)?\s*\)\s*$",
                "", t, flags=re.I,
            )

            # Whole-name match, before "of STATE" but after the district rules.
            # Some state names contain their own preposition ("NCT of Delhi"):
            # "of STATE" would eat only the " of Delhi" tail and strand "- NCT".
            # _STATE_ALT is sorted longest-first, so the full name wins here.
            # It must NOT run before the district rules, or "in Leh District of
            # Ladakh" loses its state and strands "in Leh District".
            t = _strip_bare_state(t)

            # "of STATE"
            t = re.sub(rf"\s+of\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

            # "for STATE"
            t = re.sub(rf"\s+for\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

            # bare " STATE$"   (no preposition)   — MUST be last in this loop.
            # Catches titles where a date pattern stripped the temporal tail and
            # left a bare state name flush at the end, e.g.
            #   "...Oral Pill Users All India for the year 2011-12 and 2010-11"
            #     ↓ temporal: strip "for the year YR and YR"
            #   "...Oral Pill Users All India"
            #     ↓ this rule: strip bare "All India"
            #   "...Oral Pill Users"
            # Safe because _STATE_ALT is a closed list; a generic word like
            # "centres" or "year" can never match.
            t = _strip_bare_state(t)

            changed = t != prev

        # Trailing punctuation exposed by this round's stripping would block the
        # $-anchored rules on the next one: "Primary Census Abstract 2011 -
        # India" loses " India" and is left with a dangling "-", which stops the
        # bare-year rule from ever seeing "2011" at the end. Clean it inside the
        # loop, not just after it.
        t = re.sub(r"\s*[-:,;&]\s*$", "", t).strip()

        outer_changed = t != outer_prev

    t = re.sub(r"\s*\(All\)\s*$", "", t)           # leftover "(All)"
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*[-:,;&]\s*$", "", t).strip()   # trailing punctuation
    t = re.sub(r"\s*\(\s*\)\s*$", "", t).strip()   # empty parens

    return (t + suffix).strip()


# ── collection building ───────────────────────────────────────────────────────

COLLECTION_NAME_OVERRIDES: dict[str, str] = {
    # key = normalised base (lowercase), value = preferred display name
    # "item-wise report": "Item-wise report",
}


def _merge_into_parent(
    groups: dict[str, tuple[str, list[str]]],
) -> dict[str, tuple[str, list[str]]]:
    """
    Pass 3 (post-regex): merge "PREFIX for/of X" into "PREFIX" when PREFIX
    already exists as a larger collection.

    Catches multi-word district names not stripped in Pass 2:
      "Item-wise report for Karbi Anglong" → merges into "Item-wise report"
      "Data Item Comparison Report of Nicobar" → merges into "Data Item..."
    """
    merge_map: dict[str, str] = {}

    for key, (canonical, titles) in groups.items():
        m = re.match(r"^(.+)\s+(?:for|of)\s+\S.+$", canonical, re.I)
        if not m:
            continue
        parent_key = m.group(1).strip().lower()
        if parent_key in groups and parent_key != key:
            # "… for SC" would otherwise fold straight into its own superset:
            # the trailing "for X" this pass is built to discard is sometimes a
            # restricted universe rather than a district name.
            if _subset_marker(canonical) != _subset_marker(groups[parent_key][0]):
                continue
            if len(groups[parent_key][1]) > len(titles):
                merge_map[key] = parent_key

    result: dict[str, tuple[str, list[str]]] = {}
    for key, (canonical, titles) in groups.items():
        if key in merge_map:
            continue
        result[key] = (canonical, list(titles))

    def _resolve(key: str) -> str:
        """
        Follow A -> B -> C chains to the group that actually survived.

        A merge target can itself be a merge source ("X for Y" -> "X", and
        "X" -> "X"'s own parent), in which case it was dropped from `result`
        above and extending it raises KeyError. Sizes increase strictly along
        a chain so cycles cannot form, but the seen-set keeps that assumption
        from becoming a hang if the size rule ever changes.
        """
        seen = {key}
        while key in merge_map:
            key = merge_map[key]
            if key in seen:
                break
            seen.add(key)
        return key

    for from_key in merge_map:
        to_key = _resolve(from_key)
        if to_key in result:
            result[to_key][1].extend(groups[from_key][1])

    return result


CDIST_CHUNK = 2000          # max keys per row-slice
CDIST_MAX_CELLS = 70_000_000   # ~525 MB at 8 bytes/cell; caps chunk x N


def _candidate_pairs(keys: list[str], threshold: int):
    """
    Yield (i, j) index pairs, i < j, whose token_sort_ratio >= threshold.

    Fast path: rapidfuzz.process.cdist over row-slices of CDIST_CHUNK keys, so
    peak memory is chunk x len(keys) rather than the full square (32k keys
    would otherwise be a ~1 GB uint8 matrix, and 538M pure-Python comparisons).
    Slow path: the original thefuzz double loop, kept so the script still runs
    where rapidfuzz is unavailable.
    """
    n = len(keys)
    try:
        from rapidfuzz import fuzz as rfuzz
        from rapidfuzz.process import cdist
        from rapidfuzz.utils import default_process
    except ImportError:
        from thefuzz import fuzz

        for i in range(n):
            for j in range(i + 1, n):
                if fuzz.token_sort_ratio(keys[i], keys[j]) >= threshold:
                    yield i, j
        return

    # thefuzz rounds the raw ratio to an int before comparing, so a raw 91.6
    # passes at threshold 92. Cut off half a point low to catch those, then
    # re-apply the exact int(round(...)) >= threshold test per surviving pair.
    cutoff = threshold - 0.5

    # Each slice materialises a chunk x (n - start) score matrix. Shrink the
    # chunk on large key sets so peak memory stays bounded: 33k Rajya Sabha
    # keys is ~525 MB at chunk 2000, but the full 116k-row dublin_core_remaining
    # would be ~1.8 GB.
    chunk = max(1, min(CDIST_CHUNK, CDIST_MAX_CELLS // max(n, 1)))

    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        # Only compare against keys at index >= start; the lower triangle is
        # redundant and the columns below `start` were covered by earlier chunks.
        scores = cdist(
            keys[start:end], keys[start:],
            scorer=rfuzz.token_sort_ratio,
            processor=default_process,
            score_cutoff=cutoff,
            workers=-1,
        )
        for local_i, row in enumerate(scores):
            i = start + local_i
            # row index k maps to key index start + k; keep strictly upper.
            for k in row.nonzero()[0]:
                j = start + int(k)
                if j > i and int(round(row[k])) >= threshold:
                    yield i, j


def _fuzzy_merge(
    groups: dict[str, tuple[str, list[str]]],
    threshold: int = FUZZY_THRESHOLD,
) -> dict[str, tuple[str, list[str]]]:
    """
    Option B — fuzzy merge pass.

    Groups whose _normalize_key() strings score >= threshold on
    fuzz.token_sort_ratio() are merged. The smaller group is always folded
    into the larger one so the canonical name comes from the most-represented
    base string.

    Groups that differ on a known contrasting word pair (rural/urban,
    male/female, north/south …) are blocked from merging regardless of score.

    Candidate pairs come from rapidfuzz.process.cdist when available (chunked
    so the score matrix never materialises in full) and fall back to the
    original thefuzz double loop otherwise. Both paths are score-identical:
    thefuzz applies default_process to its inputs, so the rapidfuzz path must
    pass processor=default_process to match. Without the processor the two
    disagree on ~70% of real pairs (punctuation like "state/ut-wise" changes
    token boundaries), which would silently change the grouping.
    """
    keys = list(groups.keys())

    # union-find with path compression
    parent = {k: k for k in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # merge smaller into larger to preserve the most-common canonical name
        if len(groups[ra][1]) >= len(groups[rb][1]):
            parent[rb] = ra
        else:
            parent[ra] = rb

    for i, j in _candidate_pairs(keys, threshold):
        if _has_contrasting_difference(keys[i], keys[j]):
            continue   # e.g. rural vs urban — block regardless of score
        union(keys[i], keys[j])

    result: dict[str, tuple[str, list[str]]] = {}
    for key, (canonical, titles) in groups.items():
        root = find(key)
        if root not in result:
            result[root] = (groups[root][0], [])
        result[root][1].extend(titles)

    return result


def _columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", [table],
        ).fetchall()
    }


def title_filter_sql(conn: duckdb.DuckDBPyConnection, table: str,
                     batch: str | None = None,
                     where: str | None = None) -> str:
    """
    Build the WHERE clause selecting the population to collect.

    "merge_method IS NULL" (skip rows an earlier pipeline stage already
    classified) is only applied when the target table actually has that
    column — dublin_core_remaining does not.
    """
    clauses = []
    if "merge_method" in _columns(conn, table):
        clauses.append('"merge_method" IS NULL')
    if batch is not None:
        # batch is INTEGER on dublin_core_metadata but VARCHAR on
        # dublin_core_remaining; cast both sides to text so either works.
        clauses.append(f"CAST(batch AS VARCHAR) = '{batch}'")
    if where:
        clauses.append(f"({where})")
    return " AND ".join(clauses) if clauses else "TRUE"


def build_collection_map(conn: duckdb.DuckDBPyConnection,
                         batch: str | None = None,
                         table: str = TABLE,
                         where: str | None = None,
                         return_bases: bool = False):
    """
    Returns {(ministry, title): collection_name} for every distinct Title.

    Both dicts are keyed by (ministry, title); see the blocking note below.
    so callers can audit what Pass 1 stripped.

    Passes:
      1. Regex normalisation — strip temporal + geographic parts
      2. _merge_into_parent — fold leftover district-name variants
      3. _fuzzy_merge — collapse surface variants (case, plural, separators)
    """
    filter_sql = title_filter_sql(conn, table, batch=batch, where=where)
    # ORDER BY is load-bearing, not cosmetic: DuckDB's parallel hash aggregate
    # returns DISTINCT rows in a different order on every run, and both the
    # union-find tie-break ("merge smaller into larger" — ties resolve by
    # encounter order) and the resulting canonical collection NAME depend on
    # that order. Without it, reruns produce identical group membership under
    # different collection names, which breaks anything joining on Collection.
    rows = conn.execute(
        f'SELECT DISTINCT "Publisher[ministry_department]", "Title" '
        f'FROM "{table}" WHERE {filter_sql} ORDER BY 1, 2'
    ).fetchall()

    # Group titles per ministry and run the three passes inside each block. A
    # collection must never span ministries (two departments publishing the
    # same title are two datasets), and blocking also keeps the O(k^2) fuzzy
    # pass small.
    by_ministry: dict[str, list[str]] = {}
    for ministry, title in rows:
        by_ministry.setdefault(ministry, []).append(title)

    bases: dict[tuple[str, str], str] = {}
    named: dict[tuple[str, str], str] = {}
    name_owners: dict[str, set[str]] = {}

    for ministry, titles in by_ministry.items():
        # Pass 1: regex normalisation
        groups: dict[str, tuple[str, list[str]]] = {}
        for title in titles:
            base = normalize_title(title)

            # guard against trivially short bases becoming false collections
            if len(base.split()) < 2 or len(base) < 8:
                base = title   # treat original title as its own unique key

            bases[(ministry, title)] = base
            key = _normalize_key(base)   # Option A: surface-variant collapse
            if key not in groups:
                groups[key] = (base, [])
            groups[key][1].append(title)

        # Pass 2: parent merge (multi-word district leftovers)
        groups = _merge_into_parent(groups)

        # Pass 3: fuzzy merge (Option B)
        groups = _fuzzy_merge(groups, threshold=FUZZY_THRESHOLD)

        for key, (canonical, group_titles) in groups.items():
            name = COLLECTION_NAME_OVERRIDES.get(key, canonical)
            name_owners.setdefault(name, set()).add(ministry)
            for t in group_titles:
                named[(ministry, t)] = name

    # A base that arose independently in two ministries would otherwise share
    # one Collection name and read as a single cross-ministry collection.
    # Qualify only the colliding names so the common case stays clean.
    result: dict[tuple[str, str], str] = {}
    for (ministry, title), name in named.items():
        if len(name_owners[name]) > 1:
            name = f"{name} [{ministry}]"
        result[(ministry, title)] = name

    return (result, bases) if return_bases else result



def apply(conn: duckdb.DuckDBPyConnection,
          collection_map: dict[str, str],
          table: str = TABLE,
          filter_sql: str = "TRUE") -> None:
    """Add dataset_merge column (if needed), update Collection + dataset_merge.

    filter_sql must be the same predicate build_collection_map() used, so a
    --ministry / --where run only ever writes to the rows it actually grouped.
    Without it a title shared across ministries would have its Collection
    overwritten outside the selected population.
    """
    import pandas as pd

    existing = {
        r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", [table],
        ).fetchall()
    }
    if "dataset_merge" not in existing:
        conn.execute(
            f'ALTER TABLE "{table}" ADD COLUMN dataset_merge BOOLEAN DEFAULT FALSE'
        )

    mapping_df = pd.DataFrame(
        [(ministry, title, name) for (ministry, title), name in collection_map.items()],
        columns=["ministry_key", "title_key", "collection_name"],
    )

    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")
    conn.execute("CREATE TEMP TABLE _tmp_coll_map AS SELECT * FROM mapping_df")

    # Join on ministry too: the map is blocked per ministry, and matching on
    # title alone would write one block's name onto another block's rows.
    conn.execute(f"""
        UPDATE "{table}" AS d
        SET "Collection" = m.collection_name
        FROM _tmp_coll_map m
        WHERE d."Title" = m.title_key
          AND d."Publisher[ministry_department]" IS NOT DISTINCT FROM m.ministry_key
          AND ({filter_sql})
    """)

    # Collection sizes in one aggregate pass. The previous form ran a
    # correlated COUNT(*) over the whole table once per row.
    conn.execute(f"""
        UPDATE "{table}" AS d
        SET dataset_merge = c.n >= {MERGE_THRESHOLD}
        FROM (
            SELECT "Collection" AS coll, COUNT(*) AS n
            FROM "{table}" WHERE "Collection" IS NOT NULL
            GROUP BY 1
        ) c
        WHERE d."Collection" = c.coll
    """)

    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")


CSV_COLUMNS = [
    "nid", "Title", "normalized_base", "Collection",
    "n_in_collection", "dataset_merge",
    "header_hash", "header_sig",
    "n_distinct_header_sigs", "n_rows_missing_header", "headers_consistent",
]

SUMMARY_COLUMNS = [
    "Collection", "n_rows", "dataset_merge",
    "n_distinct_header_sigs", "n_rows_missing_header", "headers_consistent",
    "sample_titles",
]

# Some "Conforms To" values are not header lists at all but multi-megabyte JSON
# dumps of the source file (the Rajya Sabha Synopsis feeds). Excel's cell limit
# is 32,767 chars, so the raw value is written truncated and the full value is
# identified by header_hash — distinctness is always computed on the full value.
HEADER_SIG_MAXLEN = 300


def _header_hash(value) -> str:
    """Stable short id for a header signature; "" when the header is unknown."""
    import hashlib

    if value is None or not str(value).strip():
        return ""
    return hashlib.md5(str(value).encode("utf-8", "replace")).hexdigest()[:10]


def _headers_consistent(sigs: set[str], missing: int) -> str:
    """
    TRUE / FALSE / "" for a collection's header coherence.

    Blank means *unknown*, not consistent: a collection whose rows all have a
    NULL "Conforms To" has one distinct (empty) signature, and reporting that
    as TRUE would read as "schema verified identical" when nothing was checked.
    """
    if not sigs:
        return ""            # no row has a header at all — unknown
    if len(sigs) == 1 and missing == 0:
        return "True"
    return "False"


def _header_display(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= HEADER_SIG_MAXLEN:
        return text
    return text[:HEADER_SIG_MAXLEN] + f"… [truncated, {len(text)} chars]"


def export_csv(conn: duckdb.DuckDBPyConnection,
               collection_map: dict[str, str],
               bases: dict[str, str],
               out_path: str,
               table: str = TABLE,
               batch: str | None = None,
               where: str | None = None,
               summary_path: str | None = None) -> tuple[int, int]:
    """
    Write the collection assignment to CSV at ROW grain, touching nothing in
    the database.

    dataset_merge is computed from the row count per Collection (not the
    distinct-title count), matching apply()'s COUNT(*) semantics — the two
    differ wherever a Title repeats across nids.

    Header coherence is reported, never used to group: header_sig is the row's
    "Conforms To" value, and n_distinct_header_sigs / headers_consistent say
    whether every row of the collection shares one signature. A collection
    flagged dataset_merge=True with headers_consistent=False is mergeable by
    title but would need schema reconciliation first.
    """
    cols = _columns(conn, table)
    filter_sql = title_filter_sql(conn, table, batch=batch, where=where)

    nid_expr = '"nid"' if "nid" in cols else 'NULL'
    header_expr = f'"{HEADER_COL}"' if HEADER_COL in cols else 'NULL'
    rows = conn.execute(
        f'SELECT {nid_expr}, "Title", {header_expr}, "Publisher[ministry_department]" '
        f'FROM "{table}" WHERE {filter_sql}'
    ).fetchall()

    # Pass 1 over rows: per-collection row counts and header signature sets.
    # Signatures are compared by hash so the multi-megabyte values above do not
    # get copied into a set 33k times.
    row_counts: dict[str, int] = {}
    header_sigs: dict[str, set] = {}
    missing_headers: dict[str, int] = {}
    hashes: list[str] = []
    for _nid, title, header, ministry in rows:
        h = _header_hash(header)
        hashes.append(h)
        name = collection_map.get((ministry, title))
        if name is None:
            continue
        row_counts[name] = row_counts.get(name, 0) + 1
        header_sigs.setdefault(name, set())
        missing_headers.setdefault(name, 0)
        if h:
            header_sigs[name].add(h)
        else:
            missing_headers[name] += 1

    merged_rows = 0
    samples: dict[str, list[str]] = {}
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for (nid, title, header, ministry), h in zip(rows, hashes):
            name = collection_map.get((ministry, title))
            if name is None:
                continue
            count = row_counts[name]
            n_sigs = len(header_sigs[name])
            missing = missing_headers[name]
            is_merge = count >= MERGE_THRESHOLD
            merged_rows += is_merge
            if len(samples.setdefault(name, [])) < 3:
                samples[name].append(title)
            writer.writerow([
                nid, title, bases.get((ministry, title), ""), name,
                count, is_merge,
                h, _header_display(header),
                n_sigs, missing, _headers_consistent(header_sigs[name], missing),
            ])

    if summary_path:
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(SUMMARY_COLUMNS)
            for name, count in sorted(
                row_counts.items(), key=lambda kv: (-kv[1], kv[0])
            ):
                n_sigs = len(header_sigs[name])
                missing = missing_headers[name]
                writer.writerow([
                    name, count, count >= MERGE_THRESHOLD,
                    n_sigs, missing,
                    _headers_consistent(header_sigs[name], missing),
                    " | ".join(samples.get(name, [])),
                ])

    return len(rows), merged_rows


_UPTO_RE = re.compile(rf"\bupto\s+{_MONTH}", re.I)
_FOR_MONTH_RE = re.compile(rf"\bfor\s+{_MONTH}{_MY_SEP}{_YR}", re.I)


def split_temporal_collections(
    conn: duckdb.DuckDBPyConnection,
    collections: list[str],
    table: str = TABLE,
) -> None:
    """
    For each named collection, split titles into a "(for)" and "(upto)"
    sub-collection based on the temporal keyword in the original title.

    "Item-wise report for April-2011-12"       → "Item-wise report (for)"
    "Item-wise report Upto February-2018-19"   → "Item-wise report (upto)"

    Titles with neither pattern keep the original collection name unchanged.
    """
    for collection in collections:
        rows = conn.execute(
            f'SELECT "Title" FROM "{table}" WHERE "Collection" = ?',
            [collection],
        ).fetchall()

        for_titles  = []
        upto_titles = []
        for (title,) in rows:
            if _UPTO_RE.search(title):
                upto_titles.append(title)
            elif _FOR_MONTH_RE.search(title):
                for_titles.append(title)

        if not for_titles and not upto_titles:
            continue

        if for_titles:
            import pandas as pd
            df = pd.DataFrame(for_titles, columns=["t"])
            conn.execute("DROP TABLE IF EXISTS _tmp_split")
            conn.execute("CREATE TEMP TABLE _tmp_split AS SELECT * FROM df")
            conn.execute(
                f'UPDATE "{table}" SET "Collection" = ? '
                f'WHERE "Title" IN (SELECT t FROM _tmp_split)',
                [f"{collection} (for)"],
            )
            conn.execute("DROP TABLE IF EXISTS _tmp_split")

        if upto_titles:
            import pandas as pd
            df = pd.DataFrame(upto_titles, columns=["t"])
            conn.execute("DROP TABLE IF EXISTS _tmp_split")
            conn.execute("CREATE TEMP TABLE _tmp_split AS SELECT * FROM df")
            conn.execute(
                f'UPDATE "{table}" SET "Collection" = ? '
                f'WHERE "Title" IN (SELECT t FROM _tmp_split)',
                [f"{collection} (upto)"],
            )
            conn.execute("DROP TABLE IF EXISTS _tmp_split")

        print(
            f"  Split '{collection}': "
            f"{len(for_titles)} → (for), {len(upto_titles)} → (upto)"
        )


def print_summary(conn: duckdb.DuckDBPyConnection, table: str = TABLE) -> None:
    total  = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    merged = conn.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE dataset_merge = TRUE'
    ).fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"  Total rows          : {total:>10}")
    print(f"  dataset_merge=TRUE  : {merged:>10}")
    print(f"  dataset_merge=FALSE : {total - merged:>10}")
    print(f"  Threshold           : >= {MERGE_THRESHOLD} rows")
    print(f"{'=' * 70}")

    print(f"\n  Top 25 collections:\n")
    rows = conn.execute(f"""
        SELECT "Collection", dataset_merge, COUNT(*) as cnt
        FROM "{table}"
        WHERE "Collection" IS NOT NULL
        GROUP BY "Collection", dataset_merge
        ORDER BY cnt DESC
        LIMIT 25
    """).fetchall()
    print(f"  {'Collection':<65} {'Merge':>5} {'Rows':>8}")
    print(f"  {'-' * 80}")
    for name, merge, cnt in rows:
        flag    = "YES" if merge else "no"
        display = name if len(name) <= 64 else name[:61] + "..."
        print(f"  {display:<65} {flag:>5} {cnt:>8}")

    for pattern, label in [
        ("%Item-wise report%",      "Item-wise report"),
        ("%Infant Mortality Rates%","Infant Mortality Rates"),
        ("%Data Item Comparison%",  "Data Item Comparison"),
    ]:
        print(f"\n  Spot-check: {label}")
        sample = conn.execute(f"""
            SELECT "Collection", dataset_merge, "Title"
            FROM "{table}" WHERE "Title" ILIKE '{pattern}'
            LIMIT 3
        """).fetchall()
        for name, merge, title in sample:
            print(f"    [{merge}] Collection={name}")
            print(f"         Title={title}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect and flag mergeable dataset collections"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without modifying the database")
    parser.add_argument("--batch", default=None,
                        help="Process only this batch number")
    parser.add_argument("--db", default=DB_PATH,
                        help=f"DuckDB file (default: {DB_PATH})")
    parser.add_argument("--table", default=TABLE,
                        help=f"Source table (default: {TABLE}). "
                             f"Use dublin_core_remaining for the remaining "
                             f"(header-filled) datasets.")
    parser.add_argument("--where", default=None,
                        help="Extra SQL predicate restricting the population, "
                             "e.g. \"\\\"Publisher[ministry_department]\\\" = "
                             "'Rajya Sabha'\"")
    parser.add_argument("--ministry", default=None,
                        help="Shorthand for --where on "
                             "Publisher[ministry_department] (case-insensitive "
                             "exact match), e.g. --ministry 'Rajya Sabha'")
    parser.add_argument("--output-csv", default=None, metavar="PATH",
                        help="Write results to CSV instead of the database. "
                             "The connection is opened read-only in this mode.")
    parser.add_argument("--summary-csv", default=None, metavar="PATH",
                        help="Also write a collection-grain summary CSV "
                             "(one row per Collection). Requires --output-csv.")
    parser.add_argument(
        "--split-collections",
        nargs="+",
        default=["Item-wise report"],
        metavar="COLLECTION",
        help="Collections to split into (for) and (upto) sub-collections "
             "(default: 'Item-wise report')",
    )
    args = parser.parse_args()

    where = args.where
    if args.ministry:
        ministry = args.ministry.replace("'", "''").lower()
        clause = f'lower("Publisher[ministry_department]") = \'{ministry}\''
        where = f"{where} AND {clause}" if where else clause

    csv_mode = args.output_csv is not None
    if args.summary_csv and not csv_mode:
        parser.error("--summary-csv requires --output-csv")
    # Read-only in CSV mode: the whole point of --output-csv is to leave the
    # database untouched, and this table has been corrupted by bulk writes before.
    conn = duckdb.connect(args.db, read_only=csv_mode)
    collection_map, bases = build_collection_map(
        conn, batch=args.batch, table=args.table, where=where,
        return_bases=True,
    )

    name_counts: dict[str, int] = {}
    for name in collection_map.values():
        name_counts[name] = name_counts.get(name, 0) + 1
    merge_count = sum(1 for c in name_counts.values() if c >= MERGE_THRESHOLD)

    print(f"Source table           : {args.table}")
    if where:
        print(f"Filter                 : {where}")
    print(f"Distinct titles        : {len(collection_map)}")
    print(f"Collections detected   : {len(name_counts)}")
    print(f"  mergeable (>= {MERGE_THRESHOLD})    : {merge_count} "
          f"(by distinct title; CSV counts rows)")
    print(f"  singletons           : {len(name_counts) - merge_count}")

    if csv_mode:
        total, merged = export_csv(
            conn, collection_map, bases, args.output_csv,
            table=args.table, batch=args.batch, where=where,
            summary_path=args.summary_csv,
        )
        print(f"\nWrote {total} rows to {args.output_csv}")
        if args.summary_csv:
            print(f"Wrote collection summary to {args.summary_csv}")
        print(f"  dataset_merge=TRUE  : {merged}")
        print(f"  dataset_merge=FALSE : {total - merged}")
        conn.close()
        print("\nDone (database not modified).")
        return

    if args.dry_run:
        print(f"\n[DRY RUN] Top 40 collections:\n")
        for name, cnt in sorted(
            name_counts.items(), key=lambda x: x[1], reverse=True
        )[:40]:
            flag = "MERGE" if cnt >= MERGE_THRESHOLD else "     "
            print(f"  [{cnt:>7}] {flag}  {name}")
        conn.close()
        return

    print("\nApplying to database...")
    apply(conn, collection_map, table=args.table,
          filter_sql=title_filter_sql(conn, args.table, batch=args.batch, where=where))

    print("\nSplitting temporal sub-collections...")
    split_temporal_collections(conn, args.split_collections, table=args.table)

    print_summary(conn, table=args.table)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()