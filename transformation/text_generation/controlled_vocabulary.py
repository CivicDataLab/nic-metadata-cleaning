"""Controlled keyword vocabulary — loader and matcher.

Loads the curated vocabulary from ``controlled_vocabulary.yaml`` and assigns a
bounded, consistent set of keywords to a dataset from its title/collection text.

The matcher is deterministic and pure (no I/O once the vocab is loaded), so it
runs over all ~207k rows cheaply and is trivially unit-testable. It replaces the
free-form, unbounded keywords the LLM produced with a controlled facet model:

    generic   -> Subject[keyword]            (layman search words)
    sponsored -> Subject[sponsored_keyword]  (specific values: states, HMIS, ...)

Usage:
    from controlled_vocabulary import load_vocab, assign_keywords
    vocab = load_vocab()
    generic, sponsored = assign_keywords({"Title": "...", "Collection": "..."}, vocab)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import yaml

VOCAB_PATH = os.path.join(os.path.dirname(__file__), "controlled_vocabulary.yaml")

# Fields combined into the search text, in priority order. Title first because
# it is the only field populated on every row (Collection is NULL on ~70%).
TEXT_FIELDS = [
    "Title",
    "Collection",
    "Relation[Catalog Title]",
    "Subject[sector_resource]",
    "Accrual Periodicity",
    "Coverage",
]


@dataclass
class Rule:
    facet: str
    category: str
    pattern: re.Pattern
    generic: list[str]
    sponsored: list[str]


@dataclass
class Vocab:
    rules: list[Rule]
    states: list[tuple[str, re.Pattern]]  # (canonical name, compiled pattern)
    baseline_generic: list[str]
    baseline_sponsored: list[str]
    generic_max: int
    sponsored_max: int


def _compile(patterns: list[str]) -> re.Pattern:
    """Combine a rule's patterns into one case-insensitive alternation."""
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


def load_vocab(path: str = VOCAB_PATH) -> Vocab:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules = [
        Rule(
            facet=r["facet"],
            category=r["category"],
            pattern=_compile(r["patterns"]),
            generic=r.get("generic", []) or [],
            sponsored=r.get("sponsored", []) or [],
        )
        for r in data.get("rules", [])
    ]

    states = [
        (canonical, _compile(variants))
        for canonical, variants in (data.get("states") or {}).items()
    ]

    limits = data.get("limits", {})
    baseline = data.get("baseline", {})
    return Vocab(
        rules=rules,
        states=states,
        baseline_generic=baseline.get("generic", []) or [],
        baseline_sponsored=baseline.get("sponsored", []) or [],
        generic_max=int(limits.get("generic_max", 10)),
        sponsored_max=int(limits.get("sponsored_max", 6)),
    )


def controlled_keyword_lists(vocab: Vocab) -> tuple[list[str], list[str]]:
    """Return the full sorted set of allowed (generic, sponsored) keywords.

    Used to constrain the LLM: free-text keyword invention is replaced by
    selection from this controlled list. States are part of the sponsored set.
    """
    generic: set[str] = set(vocab.baseline_generic)
    sponsored: set[str] = set(vocab.baseline_sponsored)
    for rule in vocab.rules:
        generic.update(rule.generic)
        sponsored.update(rule.sponsored)
    sponsored.update(canonical for canonical, _ in vocab.states)
    return sorted(generic), sorted(sponsored)


def _dedupe(items: list[str], cap: int) -> list[str]:
    """Order-preserving de-dup (case-insensitive), capped."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        x = x.strip()
        k = x.lower()
        if x and k not in seen:
            seen.add(k)
            out.append(x)
        if len(out) >= cap:
            break
    return out


# Age ranges named in titles ("Aged 15–49", "Children 6–59 Months"). These are
# extracted, not a closed list, and added to the sponsored tier so a user can
# search the cohort. Two patterns, both requiring either an "age" cue OR an
# explicit month/year unit, so plain year ranges ("2005–06", "2015-16") are
# never picked up. Dash = hyphen / en-dash / em-dash.
_DASH = "-–—"
_AGE_PATTERNS = [
    re.compile(rf"\bage[ds]?\s+(\d{{1,2}})\s*[{_DASH}]\s*(\d{{1,3}})\s*"
               r"(month|year)?s?\b", re.IGNORECASE),
    re.compile(rf"\b(\d{{1,2}})\s*[{_DASH}]\s*(\d{{1,3}})\s*"
               r"(month|year)s?\b", re.IGNORECASE),
]


def extract_age_ranges(title: str) -> list[str]:
    """Pull age-cohort ranges out of a title, e.g. '15-49', '6-59 months'."""
    if not title:
        return []
    out: list[str] = []
    for pat in _AGE_PATTERNS:
        for m in pat.finditer(str(title)):
            a, b, unit = m.group(1), m.group(2), m.group(3)
            kw = f"{a}-{b}"
            if unit:
                kw += " months" if unit.lower().startswith("month") else " years"
            out.append(kw)
    return out


# Short forms / acronyms the dataset author spelled out in parentheses, e.g.
# "(RCH)", "(ANC)", "(DPT3)", "(IMR)", "(U5MR)". Parentheses are the reliable
# signal: standalone ALL-CAPS tokens in these titles are mostly district names
# (KOZHIKKODE, VIKARABAD, ...), so we read acronyms ONLY from inside parens.
# The big standalone acronyms (HMIS, OPD, IPD, PHC, CHC) are already covered by
# their own rules.
_PAREN = re.compile(r"\(([A-Za-z][^)]*)\)")
_ACRONYM = re.compile(r"[A-Z][A-Z0-9]{1,7}")  # used with fullmatch
# Non-topic markers that show up parenthesised but are not useful keywords.
_SHORTFORM_STOP = {"FY", "UT", "BE", "RE"}


def extract_short_forms(title: str) -> list[str]:
    """Pull author-supplied acronyms out of a title's parentheses.

    '(DPT3)' -> 'DPT', '(TT10)' -> 'TT', '(U5MR)' -> 'U5MR', '(DLHS-3)' -> 'DLHS',
    '(FY 2014-15)' -> dropped. Dose-number suffixes are stripped to the base.
    """
    if not title:
        return []
    out: list[str] = []
    for content in _PAREN.findall(str(title)):
        tok = re.split(r"[\s,;:\-/]", content.strip())[0].strip(".&")
        base = re.sub(r"\d+$", "", tok)  # DPT3 -> DPT, TT10 -> TT
        cand = next((c for c in (base, tok) if _ACRONYM.fullmatch(c)), None)
        if cand and cand not in _SHORTFORM_STOP:
            out.append(cand)
    return out


def build_text(fields: dict) -> str:
    parts = []
    for f in TEXT_FIELDS:
        v = fields.get(f)
        if v is not None and str(v).strip().lower() not in ("", "nan", "none"):
            parts.append(str(v))
    return " | ".join(parts)


def assign_keywords(fields: dict, vocab: Vocab) -> tuple[list[str], list[str]]:
    """Return (generic, sponsored) controlled keyword lists for one dataset."""
    text = build_text(fields)

    generic: list[str] = []
    survey_sponsored: list[str] = []
    other_sponsored: list[str] = []
    for rule in vocab.rules:
        if rule.pattern.search(text):
            generic.extend(rule.generic)
            if rule.facet == "survey":
                survey_sponsored.extend(rule.sponsored)
            else:
                other_sponsored.extend(rule.sponsored)

    # Age cohorts ("15-49", "6-59 months") and author acronyms ("RCH", "DPT")
    # named in the title -> sponsored.
    title = fields.get("Title", "")
    age_ranges = extract_age_ranges(title)
    short_forms = extract_short_forms(title)

    # Geography: state/UT canonical names -> sponsored keywords.
    state_hits = [c for c, pat in vocab.states if pat.search(text)]

    # Ordering controls what survives the per-tier cap: the most specific,
    # most-searched tags first.
    #   * sponsored : age cohort -> survey name -> state -> acronym -> topic.
    #   * generic   : matched rule terms -> baseline.
    sponsored = (age_ranges + survey_sponsored + state_hits + short_forms
                 + other_sponsored + vocab.baseline_sponsored)
    generic = generic + vocab.baseline_generic

    return (
        _dedupe(generic, vocab.generic_max),
        _dedupe(sponsored, vocab.sponsored_max),
    )


# --------------------------------------------------------------------------- #
# Self-test: `python controlled_vocabulary.py` runs a few hand-picked titles.
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    vocab = load_vocab()
    samples = [
        "Item-wise report for Lucknow of Uttar Pradesh upto January-2018-19",
        "Range-wise Performance of Public Facilities for C-Section deliveries "
        "at facility of Arunachal Pradesh for May-2012",
        "RCH Report Indicator Wise: Performance Related to Family Planning: "
        "Sterilisation All India for the year 2017-18",
        "State/UT Wise Male Health Worker at Sub-centres in Tribal Areas",
        "Crude Birth Rate in India (2011)",
        "Performance of Key HMIS Indicators for Child Health of Assam",
    ]
    for s in samples:
        g, sp = assign_keywords({"Title": s}, vocab)
        print("\nTITLE:", s)
        print("  generic  :", g)
        print("  sponsored:", sp)
