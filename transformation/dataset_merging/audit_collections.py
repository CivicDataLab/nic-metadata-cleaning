"""
Audit collections and exact groups for merges that cannot be explained.

The fuzzy pass guards against contrasting pairs (rural/urban, boys/girls,
sc/st …) by comparing group KEYS. That guard is blind to pairs that regex
normalisation already collapsed into the SAME key — those never reach the
comparison. This script checks the finished groups instead, where such merges
are visible.

Three checks, cheapest first, no model required:

  contrasting  - the group contains members on both sides of a contrasting
                 pair. A hard error: these are different datasets by
                 definition.
  unexplained  - the group's members differ on tokens that are not temporal,
                 not geographic, and not the axis merge_add_columns already
                 names. Usually an entity axis nobody has named yet
                 ("… of Air Asia" vs "… of Air Costa"), sometimes a bad merge.
  geo_unnamed  - members span several states or districts but
                 merge_add_columns does not mention that axis, so a merge
                 would silently stack incomparable rows.

Read-only. Writes reports/audit_<scope>.csv and prints a summary.

Usage:
  python audit_collections.py
  python audit_collections.py --scope exact
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset_merge import _CONTRASTING_PAIRS, state_ut  # noqa: E402

# north/south and east/west are dropped from the audit vocabulary: Indian
# district names are full of them ("Middle And North Andamans", "South
# Salmara-Mankachar", "North East District of Delhi"), so at group level they
# flag geography, not a contrast. They stay in dataset_merge's fuzzy-pass guard,
# where the comparison is between normalised keys rather than raw titles.
_DIRECTIONS = {frozenset({"north", "south"}), frozenset({"east", "west"})}
_AUDIT_PAIRS = [p for p in _CONTRASTING_PAIRS if p not in _DIRECTIONS]

# A restricted universe is marked by a MODIFIER PHRASE ("… for SC, 2011"), not
# by a bare token. Bare-token matching is unusable here because Indian district
# names embed these words — Kamrup-Rural, Bengaluru Urban, Mumbai Suburban —
# and produced false positives on 47 exact groups.
#
# When the phrase appears in SOME members and not others, the group mixes a
# subset with its superset. The fuzzy guard cannot see this: it fires only when
# BOTH sides carry a contrasting token, and the superset side carries none.
_SUBSET_RE = re.compile(
    r"\bfor\s+(SC|ST|Scheduled\s+Castes?|Scheduled\s+Tribes?|Rural|Urban|"
    r"Boys|Girls|Males?|Females?)\b",
    re.I,
)


def subset_marker(title: str) -> str | None:
    m = _SUBSET_RE.search(title or "")
    return re.sub(r"\s+", " ", m.group(1)).lower() if m else None

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"

_STATES = {s.lower() for s in state_ut}
_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}
# Structural words and slot markers that carry no dataset identity.
_STOP = {
    "for", "of", "in", "the", "and", "to", "from", "during", "upto", "as", "on",
    "at", "by", "with", "a", "an", "district", "districts", "state", "states",
    "year", "years", "census", "part", "session", "quarter", "total", "all",
}
_NUMERIC = re.compile(r"^\d[\d\-/]*$")


def tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (title or "").lower()))


def is_slot(tok: str) -> bool:
    """True when a differing token is an expected axis rather than identity."""
    return (
        tok in _STOP
        or tok in _MONTHS
        or tok in _STATES
        or _NUMERIC.match(tok) is not None
    )


def audit_group(titles: list[str], add_columns: str | None) -> dict:
    """Classify what varies across a group's titles."""
    tok_sets = [tokens(t) for t in titles]
    common = set.intersection(*tok_sets) if tok_sets else set()
    varying = Counter()
    for ts in tok_sets:
        for tok in ts - common:
            varying[tok] += 1

    contrasting = []
    for pair in _AUDIT_PAIRS:
        present = [w for w in pair if any(w in ts for ts in tok_sets)]
        # Both sides present AND both varying. If one side is in every member
        # it belongs to the dataset's name rather than marking a contrast —
        # "Gram Panchayat-wise Rural Sanitation Coverage" is rural throughout,
        # and an incidental "urban" elsewhere does not make it a mixed group.
        if len(present) == 2 and not (set(present) & common):
            contrasting.append("/".join(sorted(present)))

    # Subset mixed with superset: modifier phrase on some members, not others.
    markers = {subset_marker(t) for t in titles}
    subset_split = (
        sorted(m for m in markers if m) if len(markers) > 1 else []
    )

    axis = (add_columns or "").lower()
    unexplained = sorted(
        t for t in varying
        if not is_slot(t)
        # a district/state axis already declared explains open-ended geo tokens
        and not ("district" in axis and varying[t] < len(titles))
    )

    states_seen = {t for ts in tok_sets for t in ts if t in _STATES}
    geo_unnamed = len(states_seen) > 1 and "state" not in axis

    return {
        "contrasting": contrasting,
        "subset_split": subset_split,
        "unexplained": unexplained[:12],
        "n_unexplained": len(unexplained),
        "geo_unnamed": geo_unnamed,
        "n_states": len(states_seen),
    }


def run(con, table: str, scope: str, out_dir: Path) -> None:
    if scope == "curate":
        key, label = '"Collection"', "Collection"
        where = "merge_method = 'curate' AND \"Collection\" IS NOT NULL"
    else:
        key, label = "exact_merge_group_id", "exact_merge_group_id"
        where = "exact_merge_group_id IS NOT NULL"

    rows = con.execute(f"""
        SELECT {key}, "Title", merge_add_columns
        FROM "{table}" WHERE {where}
    """).fetchall()

    groups = defaultdict(list)
    axes = {}
    for gid, title, add_cols in rows:
        groups[gid].append(title)
        axes[gid] = add_cols

    findings = []
    n_contrasting = n_unexplained = n_geo = n_subset = 0
    for gid, titles in groups.items():
        if len(titles) < 2:
            continue
        r = audit_group(titles, axes.get(gid))
        flags = []
        if r["contrasting"]:
            flags.append("contrasting")
            n_contrasting += 1
        if r["subset_split"]:
            flags.append("subset_split")
            n_subset += 1
        if r["n_unexplained"]:
            flags.append("unexplained")
            n_unexplained += 1
        if r["geo_unnamed"]:
            flags.append("geo_unnamed")
            n_geo += 1
        if flags:
            findings.append([
                gid, len(titles), ",".join(flags),
                ";".join(r["contrasting"] + r["subset_split"]), r["n_unexplained"],
                " ".join(r["unexplained"]), r["n_states"],
                axes.get(gid) or "", " | ".join(titles[:2]),
            ])

    # Contrasting first, then widest unexplained variance.
    def rank(x):
        if "contrasting" in x[2]:
            return 0
        if "subset_split" in x[2]:
            return 1
        return 2
    findings.sort(key=lambda x: (rank(x), -x[4]))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"audit_{scope}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([label, "n_rows", "flags", "contrasting_or_subset",
                    "n_unexplained_tokens", "unexplained_tokens", "n_states",
                    "merge_add_columns", "sample_titles"])
        w.writerows(findings)

    total = sum(1 for t in groups.values() if len(t) >= 2)
    print(f"scope                  : {scope}")
    print(f"groups audited         : {total}")
    print(f"  contrasting-pair violations : {n_contrasting}")
    print(f"  subset mixed with superset  : {n_subset}")
    print(f"  unexplained token variance  : {n_unexplained}")
    print(f"  multi-state, axis unnamed   : {n_geo}")
    print(f"  clean                       : {total - len(findings)}")
    print(f"\nWrote {path} ({len(findings)} flagged)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit groups for unexplained merges.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--scope", choices=["curate", "exact"], default="curate")
    ap.add_argument("--out-dir", default=str(HERE / "reports"))
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    try:
        run(con, args.table, args.scope, Path(args.out_dir))
    finally:
        con.close()


if __name__ == "__main__":
    main()
