"""
Assign the merge_method flag and clear Collection on exact-merge rows.

Two coupled steps on dublin_core_metadata:

1. merge_method (new VARCHAR column), with exact-group precedence:
     'direct'  - row has an exact_merge_group_name (merge directly / dedup)
     'curate'  - no exact group but has a Collection (needs curation to merge)
     NULL      - neither (no automatic merge path)

2. Clear Collection (set NULL) on every row that has an exact_merge_group_name.
   The exact group supersedes the collection grouping for those rows. (Done
   AFTER merge_method is computed; order is irrelevant since 'direct' keys off
   exact_merge_group_name, not Collection.)

ONE-WAY / idempotent: safe to re-run. NOTE: dataset_merge.py recomputes
Collection from titles on every run and would re-populate Collection on
exact-group rows, so run THIS script AFTER dataset_merge.py (and after
unflag_varying_header_collections.py).

Usage:
  python set_merge_method.py
  python set_merge_method.py --dry-run
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"


def main(dry_run: bool) -> None:
    con = duckdb.connect(DB_PATH)
    try:
        # Preview the resulting merge_method distribution (exact-group precedence).
        dist = con.execute(f"""
            SELECT
                CASE
                    WHEN exact_merge_group_name IS NOT NULL THEN 'direct'
                    WHEN "Collection" IS NOT NULL          THEN 'curate'
                    ELSE NULL
                END AS merge_method,
                COUNT(*) AS n
            FROM {TABLE}
            GROUP BY 1 ORDER BY n DESC
        """).fetchall()
        print("merge_method distribution (to be written):")
        for method, n in dist:
            print(f"  {str(method):<8} : {n:>8}")

        to_clear = con.execute(
            f'SELECT COUNT(*) FROM {TABLE} '
            f'WHERE exact_merge_group_name IS NOT NULL AND "Collection" IS NOT NULL'
        ).fetchone()[0]
        print(f"\nCollection values to clear (exact-group rows): {to_clear}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # Step 1: add column if missing, then assign merge_method.
        cols = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{TABLE}'"
        ).fetchall()}
        if "merge_method" not in cols:
            con.execute(f"ALTER TABLE {TABLE} ADD COLUMN merge_method VARCHAR")
            print("\nAdded column: merge_method")

        con.execute(f"""
            UPDATE {TABLE}
            SET merge_method = CASE
                WHEN exact_merge_group_name IS NOT NULL THEN 'direct'
                WHEN "Collection" IS NOT NULL          THEN 'curate'
                ELSE NULL
            END
        """)

        # Step 2: clear Collection on exact-group rows.
        con.execute(
            f'UPDATE {TABLE} SET "Collection" = NULL '
            f'WHERE exact_merge_group_name IS NOT NULL'
        )

        # Verify.
        print("\nWritten. Verification:")
        for method, n in con.execute(f"""
            SELECT merge_method, COUNT(*) FROM {TABLE}
            GROUP BY 1 ORDER BY COUNT(*) DESC
        """).fetchall():
            print(f"  merge_method={str(method):<8} : {n:>8}")

        leftover = con.execute(
            f'SELECT COUNT(*) FROM {TABLE} '
            f'WHERE exact_merge_group_name IS NOT NULL AND "Collection" IS NOT NULL'
        ).fetchone()[0]
        print(f"  exact-group rows still holding a Collection : {leftover}")

        # Sanity: every 'direct' must have an exact group; every 'curate' a Collection.
        bad_direct = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE merge_method='direct' AND exact_merge_group_name IS NULL"
        ).fetchone()[0]
        bad_curate = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE merge_method='curate' AND \"Collection\" IS NULL"
        ).fetchone()[0]
        print(f"  invalid 'direct' (no exact group)  : {bad_direct}")
        print(f"  invalid 'curate' (no collection)   : {bad_curate}")
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Set merge_method and clear Collection on exact-merge rows."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
