"""
Rajya Sabha handling: catalog consolidation plus the recurring-series rescue.

RS is excluded from dataset-level grouping by decision — its catalogs are
per-session ("Answers Data of Rajya Sabha Questions for Session 256") holding
thousands of unrelated one-off answer tables, so title and header grouping both
shatter. Two things still need doing:

1. Catalog consolidation. All 195 session catalogs collapse to a single
   new_catalog_title, and every RS row is marked merge_method='non-mergeable'.

2. Exception scan. A question asked again in a later session IS a real series.
   Candidates need BOTH the same normalized header signature AND the same
   normalized title base across >= 2 sessions.

   Header recurrence ALONE is not enough and must not be used: 634 header sets
   recur across sessions covering 2,296 rows, but they are generic shapes
   ("Sl. No.,State/UT,202122,202223,202324") shared by unrelated questions.
   Requiring the title base too cuts that to 16 series / 33 rows, which is the
   honest number — RS really is almost entirely one-off.

Rescued series become merge_method='curate' with a Collection; everything else
stays non-mergeable.

Usage:
  python rajya_sabha.py --dry-run
  python rajya_sabha.py
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset_merge import normalize_title  # noqa: E402
from dataset_vertical_merge_exact import normalize_header_sig  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
MINISTRY = "Rajya Sabha"
NEW_CATALOG = "Rajya Sabha Questions and Answers"
MIN_SESSIONS = 2


def find_series(con, table: str) -> dict[str, str]:
    """Return {nid: collection_name} for questions recurring across sessions."""
    rows = con.execute(f"""
        SELECT nid, "Title", "Relation[Catalog Title]", "Conforms To"
        FROM "{table}" WHERE "Publisher[ministry_department]" = ?
    """, [MINISTRY]).fetchall()

    buckets = defaultdict(list)
    for nid, title, catalog, header in rows:
        sig = normalize_header_sig(header)
        if not sig:
            continue
        buckets[(sig, normalize_title(title or ""))].append((nid, catalog, title))

    series: dict[str, str] = {}
    n_series = 0
    for (_sig, base), members in buckets.items():
        if len({c for _, c, _ in members}) < MIN_SESSIONS:
            continue
        n_series += 1
        name = base.strip() or sorted(t for _, _, t in members)[0]
        for nid, _cat, _title in members:
            series[nid] = name

    print(f"recurring series found  : {n_series}")
    print(f"  rows rescued          : {len(series)}")
    return series


def apply(con, table: str, series: dict[str, str]) -> None:
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()}
    if "new_catalog_title" not in cols:
        con.execute(f'ALTER TABLE "{table}" ADD COLUMN new_catalog_title VARCHAR')
        print("Added column: new_catalog_title")

    # 1. Consolidate catalogs and mark the whole ministry non-mergeable.
    con.execute(f"""
        UPDATE "{table}"
        SET new_catalog_title = ?, merge_method = 'non-mergeable'
        WHERE "Publisher[ministry_department]" = ?
    """, [NEW_CATALOG, MINISTRY])

    # 2. Promote the rescued series back to curate with a Collection.
    if series:
        con.execute("DROP TABLE IF EXISTS _tmp_rs")
        con.execute("CREATE TEMP TABLE _tmp_rs(nid VARCHAR, name VARCHAR)")
        con.executemany("INSERT INTO _tmp_rs VALUES (?,?)",
                        [(str(k), v) for k, v in series.items()])
        con.execute(f"""
            UPDATE "{table}" AS d
            SET "Collection" = m.name, merge_method = 'curate', dataset_merge = TRUE
            FROM _tmp_rs m
            WHERE CAST(d.nid AS VARCHAR) = m.nid
        """)
        con.execute("DROP TABLE IF EXISTS _tmp_rs")

    print("\nWritten. Verification:")
    for method, n in con.execute(f"""
        SELECT merge_method, COUNT(*) FROM "{table}"
        WHERE "Publisher[ministry_department]" = ? GROUP BY 1 ORDER BY 2 DESC
    """, [MINISTRY]).fetchall():
        print(f"  {str(method):<15} : {n:>7}")
    n_cat = con.execute(
        f'SELECT COUNT(DISTINCT new_catalog_title) FROM "{table}" '
        f'WHERE "Publisher[ministry_department]" = ?', [MINISTRY]
    ).fetchone()[0]
    print(f"  distinct new_catalog_title : {n_cat}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Consolidate RS catalogs and rescue series.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    try:
        n_cat = con.execute(
            f'SELECT COUNT(DISTINCT "Relation[Catalog Title]") FROM "{args.table}" '
            f'WHERE "Publisher[ministry_department]" = ?', [MINISTRY]
        ).fetchone()[0]
        print(f"RS session catalogs     : {n_cat} -> 1 ({NEW_CATALOG!r})")
        series = find_series(con, args.table)
        if args.dry_run:
            print("\n[dry-run] No changes written.")
            return
        apply(con, args.table, series)
    finally:
        con.close()


if __name__ == "__main__":
    main()
