"""
Parse (district, state, time_period) out of an NIC dataset title.

Used by dataset_vertical_merge.py to classify each merge group by the axis
of variation across its members (temporal / geographic / both / unknown).

District extraction is anchored on the closed-list state regex from
dataset_merge.py — only titles whose location follows the recognised
"... <DISTRICT> of <STATE> ..." shape are parsed. Titles whose location is
just a state (e.g. "... at District level of Karnataka ...") return
state-only with district=None.
"""

import re
import sys
from pathlib import Path

# Import dataset_merge from this module's own directory. parent.parent would
# resolve to transformation/, whose older dataset_merge.py exposes only the
# private _STATE_ALT/_MONTH names and shadows the sibling copy.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataset_merge import STATE_ALT, MONTH_RE, YEAR_RE, YR_RE, MY_SEP_RE


# ── district + state patterns (ordered; first match wins) ────────────────────
# Each pattern captures (district, state). Wildcard for district uses .+? and
# is bounded by the closed-list STATE_ALT plus a trailing anchor, which keeps
# multi-word district names like "Agar Malwa" or "Aizawl East" intact without
# overshooting.

_DISTRICT_PATTERNS = [
    # "for <DISTRICT> of <STATE>[ Old|New] (for|upto) ..."
    re.compile(
        rf"\bfor\s+(?P<district>.+?)\s+of\s+(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s+(?:for|upto)\b",
        re.I,
    ),
    # "for <DISTRICT> of <STATE>[ Old|New]" at end of string
    re.compile(
        rf"\bfor\s+(?P<district>.+?)\s+of\s+(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s*$",
        re.I,
    ),
    # "of the district <DISTRICT> (<STATE>[ Old|New])"
    re.compile(
        rf"\bof\s+the\s+district\s+(?P<district>.+?)\s*\(\s*(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s*\)",
        re.I,
    ),
    # "of <DISTRICT> (<STATE>[ Old|New])"
    re.compile(
        rf"\bof\s+(?P<district>[^()]+?)\s*\(\s*(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s*\)",
        re.I,
    ),
    # "for <DISTRICT> (<STATE>[ Old|New])"
    re.compile(
        rf"\bfor\s+(?P<district>[^()]+?)\s*\(\s*(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s*\)",
        re.I,
    ),
]

# State-only fallback patterns — used when no district pattern matches.
# "for <STATE>" is included to catch state-level titles like
# "Item wise Cumulative Comparison Report for Chhattisgarh for 2016-2017 ...".
# It is safe to run only after the district patterns have failed, since
# "for <DISTRICT> of <STATE>" is consumed by those patterns first and
# STATE_ALT is a closed list — generic words won't match.
_STATE_ONLY_PATTERNS = [
    re.compile(rf"\bof\s+(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\b", re.I),
    re.compile(rf"\bin\s+(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\b", re.I),
    re.compile(rf"\bfor\s+(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\b", re.I),
    re.compile(rf"\(\s*(?P<state>{STATE_ALT})(?:\s+Old|\s+New)?\s*\)", re.I),
]


# ── time-period patterns (ordered; first match wins) ─────────────────────────
# Mirror of the temporal rules in dataset_merge.normalize_title, but used as
# search-and-capture (return the matched substring) rather than substitute.
# Most-specific patterns come first so we don't return a generic year match
# when a richer "for MONTH YEAR to MONTH YEAR" form is present.

_TIME_PATTERNS = [
    # Quarter N: MONTH YEAR to MONTH YEAR (with or without leading "for")
    re.compile(
        rf"\b(?:for\s+)?Quarter\s+\d+\s*:\s*{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\s+to\s+{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\b",
        re.I,
    ),
    # upto MONTH YR
    re.compile(rf"\bupto\s+{MONTH_RE}{MY_SEP_RE}{YR_RE}\b", re.I),
    # for YR (and|&) YR  — must come before the bare "for MONTH YR" / "for YR"
    re.compile(rf"\bfor\s+{YR_RE}\s*(?:&|and)\s*{YR_RE}\b", re.I),
    # (for) Financial Year: YR
    re.compile(rf"\b(?:for\s+)?Financial\s+Year:\s*{YR_RE}\b", re.I),
    # for MONTH to MONTH during YR
    re.compile(rf"\bfor\s+{MONTH_RE}\s+to\s+{MONTH_RE}\s+during\s+{YR_RE}\b", re.I),
    # (MONTH to MONTH) — RCH-style parenthetical
    re.compile(rf"\(\s*{MONTH_RE}\s+to\s+{MONTH_RE}\s*\)", re.I),
    # for the year YR (and|&) YR
    re.compile(rf"\bfor\s+the\s+year\s+{YR_RE}\s*(?:&|and)\s*{YR_RE}\b", re.I),
    # for the year YR
    re.compile(rf"\bfor\s+the\s+year\s+{YR_RE}\b", re.I),
    # for MONTH YR
    re.compile(rf"\bfor\s+{MONTH_RE}{MY_SEP_RE}{YR_RE}\b", re.I),
    # for MONTH YEAR to MONTH YEAR
    re.compile(
        rf"\bfor\s+{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\s+to\s+{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\b",
        re.I,
    ),
    # - MONTH YEAR to MONTH YEAR (RCH)
    re.compile(
        rf"-\s*{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\s+to\s+{MONTH_RE}{MY_SEP_RE}{YEAR_RE}\b",
        re.I,
    ),
    # (as on [Nth ]MONTH[,] YEAR)
    re.compile(rf"\(as\s+on\s+(?:\d+\w*\s+)?{MONTH_RE},?\s*{YEAR_RE}\)", re.I),
    # as on [Nth ]MONTH[,] YEAR
    re.compile(rf"\bas\s+on\s+(?:\d+\w*\s+)?{MONTH_RE},?\s*{YEAR_RE}\b", re.I),
    # from YR to YR — YR_RE, not YEAR_RE: the fiscal form "from 2013-14 to
    # 2015-16" is the common UDISE shape, and \d{4} cannot match it. With
    # YEAR_RE this fell through to the bare trailing-year rule below and
    # returned just "2015-16", silently reporting a point instead of a range.
    re.compile(rf"\bfrom\s+{YR_RE}\s+to\s+{YR_RE}\b", re.I),
    # - YR to YR
    re.compile(rf"-\s*{YR_RE}\s+to\s+{YR_RE}\b"),
    # during YR
    re.compile(rf"\bduring\s+{YR_RE}\b", re.I),
    # bare trailing YR (year or year-range like 2015-16) — MUST be last
    re.compile(rf"\b{YR_RE}\s*$"),
]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_title_components(title: str) -> dict:
    """
    Return {"district": str|None, "state": str|None, "time_period": str|None}.

    `time_period` is lowercased so trivially-different casings ("upto" vs
    "Upto") collapse to the same key when compared as sets.
    """
    if not title:
        return {"district": None, "state": None, "time_period": None}

    t = title.strip()

    district: str | None = None
    state: str | None = None
    for pat in _DISTRICT_PATTERNS:
        m = pat.search(t)
        if m:
            district = _clean(m.group("district"))
            state = _clean(m.group("state"))
            break

    if state is None:
        for pat in _STATE_ONLY_PATTERNS:
            m = pat.search(t)
            if m:
                state = _clean(m.group("state"))
                break

    time_period: str | None = None
    for pat in _TIME_PATTERNS:
        m = pat.search(t)
        if m:
            time_period = _clean(m.group(0)).lower()
            break

    return {"district": district, "state": state, "time_period": time_period}
