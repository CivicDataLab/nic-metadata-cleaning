"""
Split 'group based on state' collections into per-header-group sub-collections,
naming each by its fiscal-year (FY) span.

Background
----------
Many `merge_add_columns='group based on state'` collections (e.g. the HMIS
Item-wise district/sub-district reports) span several years during which the
published schema changed. Within ONE collection there are therefore several
distinct sets of `Conforms_To` headers, each used for a contiguous run of years.
Example - "HMIS Item-wise Cumulative Report for Districts in Delhi":
    16-col header set used for FY 2008-09 .. 2016-17
    64-col header set used for FY 2017-18 .. 2019-20
These two header eras cannot be merged as one collection, so we split them and
encode the FY span in the name:
    "... for Districts in Delhi (FY 2008-09 to 2016-17)"
    "... for Districts in Delhi (FY 2017-18 to 2019-20)"

What this script does
---------------------
Input  table: `collection` (singular)  - has Conforms_To + Fiscal_Year/Year.
Output table: `collections` (plural)    - same 7-column shape as before, with the
              Collection column rewritten for the split rows.

Only `merge_add_columns='group based on state'` rows are regrouped. Every other
row is copied through with its Collection unchanged.

Grouping key = the collection's members bucketed by a NORMALIZED HEADER SET:
  - split Conforms_To on commas,
  - drop pure index columns (S.No., Sr No, Serial Number, ...),
  - lower-case + collapse whitespace + strip punctuation per column name,
  - compare as an ORDER-INDEPENDENT set.
This collapses spurious splits from column reordering / an index column while
keeping genuine schema differences (added/removed measure columns).

Naming: a collection is only renamed when it has >1 header group. Each group's
suffix is its FY span:
  one year   -> " (FY 2017-18)"
  many years -> " (FY 2009-10 to 2016-17)"   (min .. max of the group's FYs)
If two groups would collide on the same suffix, the column count is appended for
disambiguation, e.g. " (FY 2009-10) [11 cols]".

Idempotent / one-way: rebuilds `collections` from `collection` every run.

Usage:
  python split_collections_by_header_group.py --dry-run
  python split_collections_by_header_group.py
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
SRC = "collection"          # input  (singular)
DST = "collections"         # output (plural)
TARGET_FLAG = "group based on state"

# Columns carried through to the output table (the existing `collections` shape).
OUT_COLS = [
    "nid", "Title", "merge_method", "merge_add_columns",
    "Collection", "Conforms_To", "Spatial_Coverage",
]

_INDEX = re.compile(
    r"^(s\.?\s*no\.?|sr\.?\s*no\.?|serial\s*(no\.?|number)?|sl\.?\s*no\.?|#)$", re.I
)


def cols_of(sig: str) -> list[str]:
    return [c.strip() for c in (sig or "").split(",") if c.strip()]


def norm_name(c: str) -> str:
    c = c.lower()
    c = re.sub(r"[^a-z0-9 ]", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def header_set(sig: str) -> frozenset:
    """Order-independent, index-dropped, normalized set of column names."""
    out = set()
    for c in cols_of(sig):
        if _INDEX.match(c.strip()):
            continue
        n = norm_name(c)
        if n:
            out.add(n)
    return frozenset(out)


def fy_span(fys: set) -> str | None:
    """' (FY 2009-10 to 2016-17)' / ' (FY 2017-18)' / None if no FY available."""
    vals = sorted(f for f in fys if f)
    if not vals:
        return None
    if vals[0] == vals[-1]:
        return f"FY {vals[0]}"
    return f"FY {vals[0]} to {vals[-1]}"


def build_rename_map(con) -> dict[int, str]:
    """Return {nid: new_collection_name} for the rows that get a split name."""
    rows = con.execute(
        f'SELECT nid, "Collection", Conforms_To, Fiscal_Year '
        f"FROM {SRC} "
        f'WHERE merge_add_columns = ? AND "Collection" IS NOT NULL',
        [TARGET_FLAG],
    ).fetchall()

    # collection -> header_set -> {"nids": [...], "fys": set, "ncols": int}
    # Rows with empty/blank Conforms_To are skipped entirely: they have no header
    # to group by, so (per spec) they keep their original Collection name.
    by_coll: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {"nids": [], "fys": set(), "ncols": 0}
    ))
    for nid, coll, sig, fy in rows:
        if not cols_of(sig):
            continue
        g = by_coll[coll][header_set(sig)]
        g["nids"].append(nid)
        g["fys"].add(fy)
        g["ncols"] = len(cols_of(sig))

    rename: dict[int, str] = {}
    for coll, groups in by_coll.items():
        if len(groups) < 2:
            continue  # single header era -> leave the name untouched

        # Deterministic group order so the disambiguation index is stable.
        ordered = sorted(
            groups.items(),
            key=lambda kv: (sorted(f for f in kv[1]["fys"] if f),
                            kv[1]["ncols"], tuple(sorted(kv[0]))),
        )
        used: set[str] = set()
        for idx, (hs, g) in enumerate(ordered, 1):
            suf = fy_span(g["fys"])
            ncols = g["ncols"]
            base = f"{coll} ({suf})" if suf else f"{coll} ({ncols} cols)"
            # Guarantee one distinct name per header group: try the FY-span name,
            # then add the column count, then a stable group index.
            name = base
            if name in used:
                name = f"{base} [{ncols} cols]"
            if name in used:
                name = f"{base} #{idx}"
            used.add(name)
            for nid in g["nids"]:
                rename[nid] = name
    return rename


def main(dry_run: bool) -> None:
    con = duckdb.connect(DB_PATH, read_only=dry_run)
    try:
        rename = build_rename_map(con)

        n_target = con.execute(
            f'SELECT COUNT(*) FROM {SRC} WHERE merge_add_columns = ? '
            f'AND "Collection" IS NOT NULL',
            [TARGET_FLAG],
        ).fetchone()[0]
        affected_colls = len({v.split(" (")[0] for v in rename.values()})
        print(f"'{TARGET_FLAG}' rows                : {n_target}")
        print(f"rows getting a split FY name        : {len(rename)}")
        print(f"collections split (>1 header group) : {affected_colls}")

        # Preview a few splits.
        sample_coll = None
        for nid, name in rename.items():
            base = name.split(" (")[0]
            if sample_coll is None:
                sample_coll = base
            if base == sample_coll:
                continue
        if rename:
            base0 = next(iter(rename.values())).split(" (")[0]
            new_names = sorted({
                v for v in rename.values() if v.split(" (")[0] == base0
            })
            print(f"\nexample split of '{base0}':")
            for nm in new_names:
                print(f"    {nm}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # Materialize the rename map via a registered DataFrame (fast bulk load;
        # row-by-row executemany over ~140k rows is far too slow).
        import pandas as pd
        items = list(rename.items())
        rename_df = pd.DataFrame(
            {"nid": [k for k, _ in items], "new_coll": [v for _, v in items]}
        ).astype({"nid": "int64", "new_coll": "object"})
        con.register("_rename_map", rename_df)

        con.execute(f"DROP TABLE IF EXISTS {DST}")
        con.execute(f"""
            CREATE TABLE {DST} AS
            SELECT
                c.nid, c."Title", c.merge_method, c.merge_add_columns,
                COALESCE(m.new_coll, c."Collection") AS "Collection",
                c.Conforms_To, c.Spatial_Coverage
            FROM {SRC} c
            LEFT JOIN _rename_map m ON c.nid = m.nid
        """)
        con.unregister("_rename_map")

        # Verify.
        total = con.execute(f"SELECT COUNT(*) FROM {DST}").fetchone()[0]
        renamed = con.execute(
            f'SELECT COUNT(*) FROM {DST} WHERE "Collection" LIKE \'%(FY %\' '
            f"OR \"Collection\" LIKE '% cols)'"
        ).fetchone()[0]
        ncoll_before = con.execute(
            f'SELECT COUNT(DISTINCT "Collection") FROM {SRC} '
            f'WHERE merge_add_columns = ?', [TARGET_FLAG]
        ).fetchone()[0]
        ncoll_after = con.execute(
            f'SELECT COUNT(DISTINCT "Collection") FROM {DST} '
            f'WHERE merge_add_columns = ?', [TARGET_FLAG]
        ).fetchone()[0]
        print(f"\nWritten {DST}: {total} rows")
        print(f"  rows with split FY/col name        : {renamed}")
        print(f"  group-based collections before     : {ncoll_before}")
        print(f"  group-based collections after split: {ncoll_after}")
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Split 'group based on state' collections by header group + FY span."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
