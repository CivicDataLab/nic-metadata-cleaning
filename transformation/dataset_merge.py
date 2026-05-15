
import argparse
import re
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"
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


def _has_contrasting_difference(a: str, b: str) -> bool:
    """
    Return True if keys a and b differ on a known contrasting word pair.
    Such pairs must not be merged regardless of fuzzy score.
    e.g. "in rural areas" vs "in urban areas" → True (block merge)
    """
    tokens_a = set(re.findall(r'\b\w+\b', a))
    tokens_b = set(re.findall(r'\b\w+\b', b))
    only_in_a = tokens_a - tokens_b
    only_in_b = tokens_b - tokens_a
    for pair in _CONTRASTING_PAIRS:
        if only_in_a & pair and only_in_b & pair:
            return True
    return False


# ── core normalisation ────────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Strip temporal and geographic variable parts from a title."""
    t = title.strip()

    # ── Pass 1: temporal stripping ────────────────────────────────────────────
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
        t = re.sub(rf"\s+({_STATE_ALT})\s*$", "", t, flags=re.I)

        changed = t != prev

    t = re.sub(r"\s*\(All\)\s*$", "", t)           # leftover "(All)"
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*[-:,;&]\s*$", "", t).strip()   # trailing punctuation
    t = re.sub(r"\s*\(\s*\)\s*$", "", t).strip()   # empty parens

    return t


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
            if len(groups[parent_key][1]) > len(titles):
                merge_map[key] = parent_key

    result: dict[str, tuple[str, list[str]]] = {}
    for key, (canonical, titles) in groups.items():
        if key in merge_map:
            continue
        result[key] = (canonical, list(titles))

    for from_key, to_key in merge_map.items():
        result[to_key][1].extend(groups[from_key][1])

    return result


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
    """
    from thefuzz import fuzz

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

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if _has_contrasting_difference(keys[i], keys[j]):
                continue   # e.g. rural vs urban — block regardless of score
            if fuzz.token_sort_ratio(keys[i], keys[j]) >= threshold:
                union(keys[i], keys[j])

    result: dict[str, tuple[str, list[str]]] = {}
    for key, (canonical, titles) in groups.items():
        root = find(key)
        if root not in result:
            result[root] = (groups[root][0], [])
        result[root][1].extend(titles)

    return result


def build_collection_map(conn: duckdb.DuckDBPyConnection,
                         batch: int | None = None) -> dict[str, str]:
    """
    Returns {title: collection_name} for every distinct Title.

    Passes:
      1. Regex normalisation — strip temporal + geographic parts
      2. _merge_into_parent — fold leftover district-name variants
      3. _fuzzy_merge — collapse surface variants (case, plural, separators)
    """
    query = f'SELECT DISTINCT "Title" FROM {TABLE}'
    if batch is not None:
        query += f" WHERE batch = {batch}"
    rows = conn.execute(query).fetchall()

    # Pass 1: regex normalisation
    groups: dict[str, tuple[str, list[str]]] = {}

    for (title,) in rows:
        base = normalize_title(title)

        # guard against trivially short bases becoming false collections
        if len(base.split()) < 2 or len(base) < 8:
            base = title   # treat original title as its own unique key

        key = _normalize_key(base)   # Option A: surface-variant collapse
        if key not in groups:
            groups[key] = (base, [])
        groups[key][1].append(title)

    # Pass 2: parent merge (multi-word district leftovers)
    groups = _merge_into_parent(groups)

    # Pass 3: fuzzy merge (Option B)
    groups = _fuzzy_merge(groups, threshold=FUZZY_THRESHOLD)

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

    mapping_df = pd.DataFrame(
        [(t, n) for t, n in collection_map.items()],
        columns=["title_key", "collection_name"],
    )

    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")
    conn.execute("CREATE TEMP TABLE _tmp_coll_map AS SELECT * FROM mapping_df")

    conn.execute(f"""
        UPDATE {TABLE} AS d
        SET "Collection" = m.collection_name
        FROM _tmp_coll_map m
        WHERE d."Title" = m.title_key
    """)

    conn.execute(f"""
        UPDATE {TABLE}
        SET dataset_merge = (
            SELECT COUNT(*) FROM {TABLE} AS t2
            WHERE t2."Collection" = {TABLE}."Collection"
        ) >= {MERGE_THRESHOLD}
        WHERE "Collection" IS NOT NULL
    """)

    conn.execute("DROP TABLE IF EXISTS _tmp_coll_map")


_UPTO_RE = re.compile(rf"\bupto\s+{_MONTH}", re.I)
_FOR_MONTH_RE = re.compile(rf"\bfor\s+{_MONTH}{_MY_SEP}{_YR}", re.I)


def split_temporal_collections(
    conn: duckdb.DuckDBPyConnection,
    collections: list[str],
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
            f'SELECT "Title" FROM {TABLE} WHERE "Collection" = ?',
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
                f'UPDATE {TABLE} SET "Collection" = ? '
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
                f'UPDATE {TABLE} SET "Collection" = ? '
                f'WHERE "Title" IN (SELECT t FROM _tmp_split)',
                [f"{collection} (upto)"],
            )
            conn.execute("DROP TABLE IF EXISTS _tmp_split")

        print(
            f"  Split '{collection}': "
            f"{len(for_titles)} → (for), {len(upto_titles)} → (upto)"
        )


def print_summary(conn: duckdb.DuckDBPyConnection) -> None:
    total  = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
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
            FROM {TABLE} WHERE "Title" ILIKE '{pattern}'
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
    parser.add_argument("--batch", type=int, default=None,
                        help="Process only this batch number")
    parser.add_argument(
        "--split-collections",
        nargs="+",
        default=["Item-wise report"],
        metavar="COLLECTION",
        help="Collections to split into (for) and (upto) sub-collections "
             "(default: 'Item-wise report')",
    )
    args = parser.parse_args()

    conn = duckdb.connect(DB_PATH)
    collection_map = build_collection_map(conn, batch=args.batch)

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
        for name, cnt in sorted(
            name_counts.items(), key=lambda x: x[1], reverse=True
        )[:40]:
            flag = "MERGE" if cnt >= MERGE_THRESHOLD else "     "
            print(f"  [{cnt:>7}] {flag}  {name}")
        conn.close()
        return

    print("\nApplying to database...")
    apply(conn, collection_map)

    print("\nSplitting temporal sub-collections...")
    split_temporal_collections(conn, args.split_collections)

    print_summary(conn)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()