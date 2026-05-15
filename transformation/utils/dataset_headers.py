"""
Header normalisation utilities for vertical-merge detection.

`Conforms To` in dublin_core_metadata is a comma-separated header list. To
decide if two datasets can be vertically concatenated we need to compare
their column sets while ignoring cosmetic noise (case, dots, presence of a
serial-number column, stray whitespace).
"""

import re

_PUNCT_RE = re.compile(r"[.,/\\()\"']")
_WS_RE = re.compile(r"\s+")

# Matches serial-number columns AFTER normalize_header has run
# (dots are gone, whitespace is collapsed, lowercased).
_SERIAL_NO_RE = re.compile(
    r"^(?:slno|sno|srno|sl no|s no|sr no|serial no|serial number|#)$"
)


def normalize_header(h: str) -> str:
    """Canonical form of a single column header. May return '' for empty inputs."""
    h = h.strip().lower()
    h = _PUNCT_RE.sub("", h)
    h = _WS_RE.sub(" ", h).strip()
    return h


def header_signature(conforms_to: str) -> tuple[str, ...]:
    """
    Stable mergeable signature from a `Conforms To` string.

    Returns a sorted tuple of normalised header tokens, with serial-number
    columns and empties dropped. Sorted (set semantics) because vertical
    concat is column-name-keyed in pandas/DuckDB, so column order does not
    affect mergeability.
    """
    if not conforms_to:
        return ()
    parts = [normalize_header(p) for p in conforms_to.split(",")]
    parts = [p for p in parts if p and not _SERIAL_NO_RE.match(p)]
    return tuple(sorted(set(parts)))
