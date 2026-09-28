"""
Summarise a final_archival.py run over dublin_core_remaining.

Read-only. Consumes the two CSVs the pipeline writes plus the exported
title/ministry CSV, and reports the three things asked for:
archival candidates, duplicates, and overlapping datasets.
"""

import os
import sys
import pandas as pd

REPO = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.join(REPO, "data", "archival_remaining")

REL = os.path.join(BASE, "dataset_relations_remaining.csv")
CANON = os.path.join(BASE, "canonical_datasets_remaining.csv")
SRC = os.path.join(BASE, "dublin_core_remaining_.csv")

OUT_DUP = os.path.join(BASE, "duplicates_remaining.csv")
OUT_OVERLAP = os.path.join(BASE, "overlaps_remaining.csv")
OUT_ARCH = os.path.join(BASE, "archival_candidates_remaining.csv")


def line(title):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


rel = pd.read_csv(REL)
canon = pd.read_csv(CANON)
src = pd.read_csv(SRC)

src_slim = src[["nid", "Relation[Catalog Title]",
                "Publisher[ministry_department]", "Collection",
                "merge_method"]].rename(
    columns={"Relation[Catalog Title]": "catalog",
             "Publisher[ministry_department]": "ministry"})

line("RELATIONS")
print(f"relation rows            : {len(rel):,}")
print(f"distinct unordered pairs : "
      f"{len(set(map(frozenset, zip(rel.source_nid, rel.target_nid)))):,}")
print("\nby family_type:")
print(rel.family_type.value_counts().to_string())
print("\nby relation predicate:")
print(rel.relation.value_counts().to_string())
print("\nconfidence by family_type:")
print(rel.groupby("family_type").confidence.describe()[
    ["count", "min", "50%", "max"]].to_string())

# ── duplicates ───────────────────────────────────────────────────────
line("DUPLICATES  (family_type = EXACT_DUPLICATE)")
dup = rel[rel.family_type == "EXACT_DUPLICATE"].copy()
dup_pairs = dup.drop_duplicates(
    subset=[c for c in ["source_nid", "target_nid"] if c in dup.columns])
print(f"EXACT_DUPLICATE rows      : {len(dup):,}")
print(f"distinct target_nids      : {dup.target_nid.nunique():,}")
print(f"distinct nids involved    : "
      f"{len(set(dup.source_nid) | set(dup.target_nid)):,}")

# does the title text actually match, or is this a metric-truncation artefact?
same_title = (dup.source_title.astype(str).str.strip().str.lower()
              == dup.target_title.astype(str).str.strip().str.lower())
print(f"pairs with identical titles : {int(same_title.sum()):,} "
      f"/ {len(dup):,}  ({100.0*same_title.mean():.1f}%)")
print("\nexamples where titles DIFFER (metric truncated at 6 tokens):")
diff = dup[~same_title][["source_nid", "source_title",
                         "target_nid", "target_title"]].head(8)
if len(diff):
    for _, r in diff.iterrows():
        print(f"  {r.source_nid}: {str(r.source_title)[:78]}")
        print(f"  {r.target_nid}: {str(r.target_title)[:78]}\n")
else:
    print("  (none)")

dup.merge(src_slim, left_on="target_nid", right_on="nid",
          how="left").to_csv(OUT_DUP, index=False)

# ── overlaps ─────────────────────────────────────────────────────────
line("OVERLAPPING / RELATED")
ov = rel[rel.family_type.isin(
    ["RELATED", "ANALYTICAL_VARIANT", "LONGITUDINAL"])].copy()
for ft in ["LONGITUDINAL", "ANALYTICAL_VARIANT", "RELATED"]:
    sub = rel[rel.family_type == ft]
    print(f"{ft:<20} rows {len(sub):>8,}   nids involved "
          f"{len(set(sub.source_nid) | set(sub.target_nid)):>8,}")
ov.merge(src_slim, left_on="source_nid", right_on="nid",
         how="left").to_csv(OUT_OVERLAP, index=False)

# ── canonical groups ─────────────────────────────────────────────────
line("CANONICAL GROUPS")
print(f"canonical rows            : {len(canon):,}")
print(f"canonical groups          : {canon.canonical_id.nunique():,}")
sizes = canon.groupby("canonical_id").size()
multi = sizes[sizes > 1]
print(f"singleton groups          : {int((sizes == 1).sum()):,}")
print(f"multi-member groups       : {len(multi):,} "
      f"covering {int(multi.sum()):,} datasets")
if len(multi):
    print(f"largest group size        : {int(multi.max()):,}")
    print("\ngroup-size distribution (multi-member only):")
    print(multi.value_counts().sort_index().head(15).to_string())
    print("\nlargest 10 families:")
    top = multi.sort_values(ascending=False).head(10)
    for cid, n in top.items():
        t = canon.loc[canon.canonical_id == cid, "canonical_title"].iloc[0]
        print(f"  {n:>5}  {str(t)[:72]}")

# ── archival ─────────────────────────────────────────────────────────
line("ARCHIVAL CANDIDATES  (canonical archival_flag)")
arch = canon[canon.archival_flag == True]  # noqa: E712
print(f"archival_flag = True      : {len(arch):,}")
print("  note: this flag only fires when EVERY title in a component "
      "normalises\n  identically, so longitudinal series never produce one.")
arch.merge(src_slim, on="nid", how="left").to_csv(OUT_ARCH, index=False)

if len(arch):
    print("\nby ministry:")
    am = arch.merge(src_slim, on="nid", how="left")
    print(am.ministry.value_counts().head(10).to_string())

# ── cross-check against true exact-title duplicates ──────────────────
line("CROSS-CHECK vs literal duplicate titles in the table")
norm = src.Title.astype(str).str.strip().str.lower().str.replace(
    r"\s+", " ", regex=True)
g = norm.groupby(norm).size()
dupg = g[g > 1]
print(f"literal duplicate-title groups : {len(dupg):,}")
print(f"redundant rows (n-1 per group) : {int(dupg.sum() - len(dupg)):,}")
lit_nids = set(src.loc[norm.isin(dupg.index), "nid"])
caught = lit_nids & (set(dup.source_nid) | set(dup.target_nid))
print(f"of those nids, caught as EXACT_DUPLICATE : {len(caught):,} "
      f"/ {len(lit_nids):,}")
missed = lit_nids - caught
print(f"missed by the pipeline                   : {len(missed):,}")

print(f"\nWrote:\n  {OUT_DUP}\n  {OUT_OVERLAP}\n  {OUT_ARCH}")
