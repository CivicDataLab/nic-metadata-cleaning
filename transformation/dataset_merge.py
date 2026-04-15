"""
Detect and flag mergeable datasets in dublin_core_metadata.

Datasets with titles that differ only by state, district, date, or year
are grouped into a collection. Two columns are set:

  - Collection   : base name of the group (e.g. "Item-wise report")
  - dataset_merge: TRUE if the collection has >= 2 rows

The approach strips temporal and geographic parts from each Title
to produce a normalised base. Titles with the same base form a collection.

Usage:
  python dataset_merge.py                # apply to DB
  python dataset_merge.py --dry-run      # preview without writing
"""

import argparse
import re
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"
MERGE_THRESHOLD = 2


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
]

_STATE_ALT = "|".join(
    re.escape(s) for s in sorted(state_ut, key=len, reverse=True)
)

# ── Regex building blocks ──────────────────────────────────────────────────

_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_YEAR = r"\d{4}"
_YR = r"\d{4}(?:-\d{2,4})?"  # year or year-range  e.g. 2015-16


# ── Title normalisation ───────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Strip temporal and geographic variable parts from a title."""
    t = title.strip()

    # ── Pass 1: strip temporal suffixes (from end of string) ──────────

    changed = True
    while changed:
        prev = t

        # "upto MONTH-YEAR"
        t = re.sub(rf"\s+upto\s+{_MONTH}-{_YR}\s*$", "", t, flags=re.I)

        # "for YEAR(-YY)? & YEAR(-YY)?" or "for YEAR(-YY)? and YEAR(-YY)?"
        t = re.sub(rf"\s+for\s+{_YR}\s*(?:&|and)\s*{_YR}\s*$", "", t, flags=re.I)

        # "[for ]Financial Year: YEAR"
        t = re.sub(rf"\s+(?:for\s+)?Financial\s+Year:\s*{_YR}\s*$", "", t, flags=re.I)

        # "for MONTH to MONTH during YEAR"
        t = re.sub(
            rf"\s+for\s+{_MONTH}\s+to\s+{_MONTH}\s+during\s+{_YR}\s*$",
            "", t, flags=re.I,
        )

        # "for MONTH-YEAR(-YY)?" (single month-year at end)
        t = re.sub(rf"\s+for\s+{_MONTH}-{_YR}\s*$", "", t, flags=re.I)

        # "for MONTH YEAR to MONTH YEAR" (quarterly: "for Apr 2012 to Jun 2012")
        t = re.sub(
            rf"\s+for\s+{_MONTH}\s+{_YEAR}\s+to\s+{_MONTH}\s+{_YEAR}\s*$",
            "", t, flags=re.I,
        )

        # "- MONTH YEAR to MONTH YEAR" (RCH style: "- April 2008 to December 2008")
        t = re.sub(
            rf"\s*-\s*{_MONTH}\s+{_YEAR}\s+to\s+{_MONTH}\s+{_YEAR}\s*$",
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

        # bare trailing " YEAR(-YY)?"
        t = re.sub(rf"\s+{_YR}\s*$", "", t)

        changed = t != prev

    # ── Pass 2: strip geographic suffixes (state-list anchored) ───────

    changed = True
    while changed:
        prev = t

        # "(All) of STATE"
        t = re.sub(rf"\s*\(All\)\s+of\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

        # "in STATE" (RCH: "Indicators in A & N Islands")
        t = re.sub(rf"\s+in\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

        # "of the district DISTRICT (STATE)" (Annual Health Survey)
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

        # "of STATE" (safe: only strips the known state name at end)
        t = re.sub(rf"\s+of\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

        # "for STATE"
        t = re.sub(rf"\s+for\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

        # "for SINGLE_WORD" at end — likely a bare district name
        # (e.g. "Item-wise report for Baksa" after state was stripped)
        t = re.sub(r"\s+for\s+\w+\s*$", "", t)

        changed = t != prev

    # ── Pass 3: cleanup ──────────────────────────────────────────────

    t = re.sub(r"\s*\(All\)\s*$", "", t)          # leftover "(All)"
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*[-:,;&]\s*$", "", t).strip()   # trailing punctuation
    t = re.sub(r"\s*\(\s*\)\s*$", "", t).strip()   # empty parens

    return t


# ── Collection name overrides (optional, user-curated short names) ────────

COLLECTION_NAME_OVERRIDES: dict[str, str] = {
    # key = normalised base (lowercase), value = preferred display name
    # "item-wise report": "Item-wise report",
}


# ── Core logic ────────────────────────────────────────────────────────────

def _merge_into_parent(
    groups: dict[str, tuple[str, list[str]]],
) -> dict[str, tuple[str, list[str]]]:
    """
    Second pass: merge "PREFIX for/of X" into "PREFIX" when PREFIX already
    exists as a larger collection.

    This catches multi-word district names that weren't stripped in pass 1:
      "Item-wise report for Karbi Anglong" → merges into "Item-wise report"
      "Data Item Comparison Report of Nicobar" → merges into "Data Item Comparison Report"

    Type suffixes like "for OPD attendance" are safe because their prefix
    (e.g. "Range-wise Performance of Public Facilities") does NOT exist
    as a standalone collection.
    """
    merge_map: dict[str, str] = {}  # from_key → to_key

    for key, (canonical, titles) in groups.items():
        # Try "PREFIX for X" and "PREFIX of X" patterns
        m = re.match(r"^(.+?)\s+(?:for|of)\s+\S.+$", canonical, re.I)
        if not m:
            continue
        parent_key = m.group(1).strip().lower()
        if parent_key in groups and parent_key != key:
            if len(groups[parent_key][1]) > len(titles):
                merge_map[key] = parent_key

    # Apply merges
    result: dict[str, tuple[str, list[str]]] = {}
    for key, (canonical, titles) in groups.items():
        if key in merge_map:
            continue  # will be folded into parent
        result[key] = (canonical, list(titles))

    for from_key, to_key in merge_map.items():
        result[to_key][1].extend(groups[from_key][1])

    return result


def build_collection_map(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    Returns {title: collection_name} for every distinct Title.

    Titles that normalise to the same base share a collection name.
    Two passes:
      1. Regex normalisation (strip temporal + geographic parts)
      2. Merge district-variant collections that share a prefix
    """
    rows = conn.execute(f'SELECT DISTINCT "Title" FROM {TABLE}').fetchall()

    # Pass 1: regex normalisation
    # base_lower -> (canonical_base, [title, ...])
    groups: dict[str, tuple[str, list[str]]] = {}

    for (title,) in rows:
        base = normalize_title(title)
        key = base.lower()
        if key not in groups:
            groups[key] = (base, [])
        groups[key][1].append(title)

    # Pass 2: merge "PREFIX for X" into "PREFIX" when parent exists
    groups = _merge_into_parent(groups)

    # Build final mapping
    result: dict[str, str] = {}
    for key, (canonical, titles) in groups.items():
        name = COLLECTION_NAME_OVERRIDES.get(key, canonical)
        for t in titles:
            result[t] = name

    return result


def apply(conn: duckdb.DuckDBPyConnection,
          collection_map: dict[str, str]) -> None:
    """Add dataset_merge column (if needed), update Collection + dataset_merge."""
    import pandas as pd

    existing = {
        r[0] for r in conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()
    }
    if "dataset_merge" not in existing:
        conn.execute(
            f'ALTER TABLE {TABLE} ADD COLUMN dataset_merge BOOLEAN DEFAULT FALSE'
        )

    # Build a DataFrame: title → collection_name
    mapping_df = pd.DataFrame(
        [(t, n) for t, n in collection_map.items()],
        columns=["title_key", "collection_name"],
    )

    # Count rows per collection (using DB row count, not distinct title count)
    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")
    conn.execute("CREATE TEMP TABLE _tmp_coll_map AS SELECT * FROM mapping_df")

    # Compute row counts per collection via join
    conn.execute(f"""
        UPDATE {TABLE} AS d
        SET "Collection" = m.collection_name
        FROM _tmp_coll_map m
        WHERE d."Title" = m.title_key
    """)

    # Set dataset_merge based on collection row count
    conn.execute(f"""
        UPDATE {TABLE}
        SET dataset_merge = (
            SELECT COUNT(*) FROM {TABLE} AS t2
            WHERE t2."Collection" = {TABLE}."Collection"
        ) >= {MERGE_THRESHOLD}
        WHERE "Collection" IS NOT NULL
    """)

    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")


def print_summary(conn: duckdb.DuckDBPyConnection) -> None:
    total = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    merged = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE dataset_merge = TRUE"
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
        FROM {TABLE}
        WHERE "Collection" IS NOT NULL
        GROUP BY "Collection", dataset_merge
        ORDER BY cnt DESC
        LIMIT 25
    """).fetchall()
    print(f"  {'Collection':<65} {'Merge':>5} {'Rows':>8}")
    print(f"  {'-' * 80}")
    for name, merge, cnt in rows:
        flag = "YES" if merge else "no"
        display = name if len(name) <= 64 else name[:61] + "..."
        print(f"  {display:<65} {flag:>5} {cnt:>8}")

    # Spot-checks
    for pattern, label in [
        ("%Item-wise report%", "Item-wise report"),
        ("%Infant Mortality Rates%", "Infant Mortality Rates"),
        ("%Data Item Comparison%", "Data Item Comparison"),
    ]:
        print(f"\n  Spot-check: {label}")
        sample = conn.execute(f"""
            SELECT "Collection", dataset_merge, "Title"
            FROM {TABLE} WHERE "Title" ILIKE '{pattern}'
            LIMIT 3
        """).fetchall()
        for name, merge, title in sample:
            print(f"    [{merge}] Collection={name}")
            print(f"         Title={title}")


def main():
    parser = argparse.ArgumentParser(
        description="Detect and flag mergeable dataset collections"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without modifying the database")
    args = parser.parse_args()

    conn = duckdb.connect(DB_PATH)
    collection_map = build_collection_map(conn)

    # Summarise collections
    name_counts: dict[str, int] = {}
    for name in collection_map.values():
        name_counts[name] = name_counts.get(name, 0) + 1
    merge_count = sum(1 for c in name_counts.values() if c >= MERGE_THRESHOLD)

    print(f"Distinct titles        : {len(collection_map)}")
    print(f"Collections detected   : {len(name_counts)}")
    print(f"  mergeable (>= {MERGE_THRESHOLD})    : {merge_count}")
    print(f"  singletons           : {len(name_counts) - merge_count}")

    if args.dry_run:
        print(f"\n[DRY RUN] Top 40 collections:\n")
        for name, cnt in sorted(name_counts.items(), key=lambda x: x[1], reverse=True)[:40]:
            flag = "MERGE" if cnt >= MERGE_THRESHOLD else "     "
            print(f"  [{cnt:>7}] {flag}  {name}")
        conn.close()
        return

    print("\nApplying to database...")
    apply(conn, collection_map)
    print_summary(conn)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
