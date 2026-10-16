"""
Can two header lists be reconciled with minor edits?

change_in_header collections legitimately hold several header signatures: the
same table published in different years picks up spelling variants
("Females" / "Female", "Distt.Code" / "District Code"), loses or gains a serial
number column, glues the reference year into column names ("2011 Assessment
MDF" / "2013 Assessment MDF"), or appends a unit ("Closing Stocks in 000
Tonnes"). None of that stops a merge. What does is a different column set --
another admin level, another classification scheme (1991 census industrial
categories I..IX vs 2011's A-Cultivators..), another subject.

dataset_headers.header_signature() only removes case/punctuation/serial noise,
and fold_header_variant_collections.canon() drops digits but keeps plurals, so
both under-report how close two such lists are. This module goes one step
further and is used for evidence only -- it never writes.
"""

import difflib
import re

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
# a year, a fiscal year span, or the word introducing one
_YEARISH = re.compile(
    r"\b(?:fy|financial\s+year|fiscal\s+year|calendar\s+year)\b"
    r"|(?:19|20)\d{2}(?:\s*[-/]\s*\d{2,4})?", re.I)
_UNIT = re.compile(
    r"\b(?:in\s+)?(?:'?000|lakhs?|crores?|rs|tonnes?|mw|mkwh|kms?|hectares?|ha)\b", re.I)
_SYN = {
    "distt": "district", "dist": "district", "eb": "enumerationblock",
    "enumeration": "enumerationblock", "fem": "female", "persons": "person",
    "nos": "number", "no": "number", "num": "number", "yr": "year",
    "sl": "serial", "sr": "serial", "uts": "ut", "disablity": "disability",
}
_STOP = {"of", "the", "and", "in", "to", "for", "by", "as", "on", "at", "a", "an"}
_SERIAL = re.compile(r"^(?:serial(?: number)?|s ?no|number|#|index|unnamed)$")
# telling a male column from a female one is exactly what fuzzy matching must
# not blur
_GENDER = {"male", "female", "person", "men", "women", "boy", "girl"}
BROKEN = re.compile(
    r"token expired|not authori[sz]ed|access denied|<html|<!doctype|error page", re.I)


def col_tokens(col: str) -> list[str]:
    s = _CAMEL.sub(" ", col or "")
    s = _YEARISH.sub(" ", s)
    s = _UNIT.sub(" ", s)
    s = re.sub(r"[^A-Za-z]+", " ", s).lower()
    out = []
    for t in s.split():
        t = _SYN.get(t, t)
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        if t not in _STOP:
            out.append(t)
    return out


def reconcile_cols(conforms_to: str) -> dict[str, str]:
    """{reconciled key: an original column name} with serial columns dropped."""
    res = {}
    for c in (conforms_to or "").split(","):
        t = col_tokens(c)
        if not t or _SERIAL.match(" ".join(t)):
            continue
        res.setdefault(" ".join(sorted(t)), c.strip())
    return res


def _col_match(a: str, b: str) -> bool:
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if ta & _GENDER != tb & _GENDER:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True
    # one extra qualifier word: "Camels Female Total" vs "Female Total"
    return (ta <= tb or tb <= ta) and len(ta ^ tb) == 1


def header_match(a: set[str], b: set[str]) -> float | None:
    """Share of the smaller column set that finds a partner in the larger."""
    if not a or not b:
        return None
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    big_l = list(big)
    hit = sum(1 for x in small if x in big or any(_col_match(x, y) for y in big_l))
    return hit / len(small)
