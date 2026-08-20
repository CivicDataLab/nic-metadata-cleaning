"""
Split curate collections that span incompatible header schemas.

A title-derived collection can gather datasets whose schemas changed over time.
Two different situations look identical from the title side and must not be
treated the same:

  minor change - the columns are the same once year tokens are stripped
                 ("Pregnancies 201112" vs "Pregnancies 201213"), or renamed in
                 a purely cosmetic way. These stay ONE collection; the year is
                 the merge axis, which is the whole point of a curate merge.
  header era   - the column SETS genuinely differ (one schema carries a
                 school-management dimension the other lacks). These are
                 different tables and become separate sub-collections.

Only the second case is split, into "<Collection> (schema N)", N ordered by
member count so the largest era keeps the lowest number.

Run AFTER detect_merge_add_column.py: splitting changes collection membership,
so merge_add_columns and needs_review must be recomputed afterwards.

Usage:
  python split_collections_by_header_group.py --dry-run
  python split_collections_by_header_group.py
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset_vertical_merge_exact import normalize_header_sig  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"

# Year-ish tokens inside a column name: 2011, 201112, 2011-12. Bucket numbers
# like 1000 are deliberately not matched — they are part of the column meaning.
_YEAR_TOK = re.compile(r"(?:19|20)\d{2}(?:[-/]?\d{2,4})?")


def era_signature(header) -> str | None:
    """Header signature with year tokens removed, so eras of one schema agree."""
    sig = normalize_header_sig(header)
    if sig is None:
        return None
    cols = {_YEAR_TOK.sub("", c).strip() for c in sig.split(",")}
    return ",".join(sorted(c for c in cols if c))


def plan_splits(con, table: str) -> dict[str, str]:
    """{nid: new_collection_name} for members of collections that must split."""
    rows = con.execute(f"""
        SELECT nid, "Collection", "Conforms To"
        FROM "{table}"
        WHERE merge_method = 'curate' AND "Collection" IS NOT NULL
    """).fetchall()

    by_coll = defaultdict(list)
    for nid, coll, header in rows:
        by_coll[coll].append((nid, era_signature(header)))

    result: dict[str, str] = {}
    n_split = n_minor = 0
    for coll, members in by_coll.items():
        eras = {e for _, e in members if e is not None}
        if len(eras) < 2:
            # One era, or no header evidence at all — nothing to split on. A
            # collection whose signatures differ only by year lands here, which
            # is the minor-change case we deliberately keep together.
            if len({e for _, e in members}) > 1:
                n_minor += 1
            continue

        n_split += 1
        sizes = defaultdict(int)
        for _nid, era in members:
            if era is not None:
                sizes[era] += 1
        # Largest era first so it gets "(schema 1)".
        order = {era: i for i, (era, _n) in enumerate(
            sorted(sizes.items(), key=lambda x: (-x[1], x[0])), start=1)}
        for nid, era in members:
            # Members with no header cannot be placed; they stay in the parent
            # collection rather than being guessed into an era.
            if era is None:
                continue
            result[nid] = f"{coll} (schema {order[era]})"

    print(f"curate collections           : {len(by_coll)}")
    print(f"  span >1 header era (split) : {n_split}")
    print(f"  minor header change (kept) : {n_minor}")
    print(f"  rows reassigned            : {len(result)}")
    return result


def apply(con, table: str, splits: dict[str, str]) -> None:
    con.execute("DROP TABLE IF EXISTS _tmp_split_hdr")
    con.execute("CREATE TEMP TABLE _tmp_split_hdr(nid VARCHAR, name VARCHAR)")
    con.executemany("INSERT INTO _tmp_split_hdr VALUES (?,?)",
                    [(str(k), v) for k, v in splits.items()])
    con.execute(f"""
        UPDATE "{table}" AS d
        SET "Collection" = m.name
        FROM _tmp_split_hdr m
        WHERE CAST(d.nid AS VARCHAR) = m.nid
    """)
    con.execute("DROP TABLE IF EXISTS _tmp_split_hdr")

    n = con.execute(
        f'SELECT COUNT(DISTINCT "Collection") FROM "{table}" '
        f"WHERE merge_method = 'curate'"
    ).fetchone()[0]
    print(f"\nWritten. Distinct curate collections now: {n}")
    print("Re-run detect_merge_add_column.py — membership changed.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Split collections spanning header eras.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    try:
        splits = plan_splits(con, args.table)
        if args.dry_run:
            print("\n[dry-run] No changes written.")
            return
        if splits:
            apply(con, args.table, splits)
    finally:
        con.close()


if __name__ == "__main__":
    main()
