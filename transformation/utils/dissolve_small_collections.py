"""
Dissolve collections that hold fewer than --min-size datasets.

A collection of one to four datasets is not worth publishing as a collection, so
its members are released: the Collection name is cleared and the rows are marked
merge_method='non-mergeable' -- a dataset with no collection has nothing to merge
with, and this keeps the invariant the rest of the pipeline relies on
(curate <=> Collection IS NOT NULL; catalog_merge_method_stats.py assumes a
Collection never spans two merge_methods).

Applies to every classified collection, 'direct' included: an exact merge group
of two to four datasets is dissolved like any other small collection.

Also cleared on the released rows:
  merge_add_columns  - names the dimension column needed to make the COLLECTION
  needs_review       - flags header variance WITHIN the collection
Both describe a collection that no longer exists. exact_merge_group_id / _name
are kept for traceability.

Idempotent: once dissolved the rows carry no Collection, so a re-run sees
nothing to do. NOTE refine_direct_merge_method.py skips 'non-mergeable' rows for
exactly this reason -- otherwise it would key off exact_merge_group_id and pull
the released direct groups back into collections.

Usage:
  python dissolve_small_collections.py --dry-run
  python dissolve_small_collections.py
  python dissolve_small_collections.py --min-size 10
"""

import argparse
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
LABEL = "non-mergeable"


def main(dry_run, db_path, table, min_size):
    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        con.execute(f"""
            CREATE TEMP TABLE _small AS
            SELECT "Collection" AS coll, COUNT(*) AS n
            FROM {table} WHERE "Collection" IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) < {min_size}
        """)
        colls, rows = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(n), 0) FROM _small").fetchone()
        print(f"collections with fewer than {min_size} datasets: {colls}  ({rows} datasets)\n")

        print(f"  {'merge_method':<18}{'collections':>12}{'datasets':>10}"
              f"{'of collections':>16}{'of datasets':>13}")
        for mm, c, n, tc, tn in con.execute(f"""
            WITH c AS (SELECT "Collection" AS coll, merge_method AS mm, COUNT(*) AS n
                       FROM {table} WHERE "Collection" IS NOT NULL GROUP BY 1, 2)
            SELECT COALESCE(mm, '(null)'),
                   COUNT(*) FILTER (WHERE n < {min_size}),
                   COALESCE(SUM(n) FILTER (WHERE n < {min_size}), 0),
                   COUNT(*), SUM(n)
            FROM c GROUP BY 1 ORDER BY 3 DESC
        """).fetchall():
            print(f"  {mm:<18}{c:>12}{n:>10}{tc:>16}{tn:>13}")

        by_size = con.execute(
            "SELECT n, COUNT(*) FROM _small GROUP BY 1 ORDER BY 1").fetchall()
        print("\n  size distribution: " +
              ", ".join(f"{n} dataset{'s' if n > 1 else ''}: {c}" for n, c in by_size))

        extra = con.execute(f"""
            SELECT COUNT(*) FILTER (WHERE merge_add_columns IS NOT NULL),
                   COUNT(*) FILTER (WHERE needs_review IS NOT NULL)
            FROM {table} WHERE "Collection" IN (SELECT coll FROM _small)
        """).fetchone()
        print(f"  of those rows, merge_add_columns set on {extra[0]}, "
              f"needs_review set on {extra[1]} (both cleared)")

        if dry_run:
            print("\nsample:")
            print(con.execute(f"""
                SELECT d."Collection", d.merge_method, s.n AS datasets, MIN(d."Title") AS sample_title
                FROM {table} d JOIN _small s ON d."Collection" = s.coll
                GROUP BY 1, 2, 3 ORDER BY 3 DESC, 1 LIMIT 8
            """).fetchdf().to_string(max_colwidth=52))
            print("\n[dry-run] No changes written.")
            return

        before = dict(con.execute(
            f"SELECT COALESCE(merge_method,'(null)'), COUNT(*) FROM {table} GROUP BY 1"
        ).fetchall())
        con.execute(f"""
            UPDATE {table} SET merge_method = '{LABEL}', "Collection" = NULL,
                               merge_add_columns = NULL, needs_review = NULL
            WHERE "Collection" IN (SELECT coll FROM _small)
        """)
        after = dict(con.execute(
            f"SELECT COALESCE(merge_method,'(null)'), COUNT(*) FROM {table} GROUP BY 1"
        ).fetchall())

        print("\nWritten. merge_method before -> after:")
        for mm in sorted(set(before) | set(after), key=lambda m: -after.get(m, 0)):
            print(f"  {mm:<18}{before.get(mm, 0):>8} -> {after.get(mm, 0):>8}")

        print("\nVerification:")
        checks = [
            (f"collections left with < {min_size} datasets (must be 0)",
             f'SELECT COUNT(*) FROM (SELECT "Collection" FROM {table} '
             f'WHERE "Collection" IS NOT NULL GROUP BY 1 HAVING COUNT(*) < {min_size})'),
            (f"'{LABEL}' rows holding a Collection (must be 0)",
             f'SELECT COUNT(*) FROM {table} WHERE merge_method = \'{LABEL}\' '
             f'AND "Collection" IS NOT NULL'),
            ("classified rows without a Collection (must be 0)",
             f"SELECT COUNT(*) FROM {table} WHERE merge_method IN "
             f"('curate','direct','change_in_header') AND \"Collection\" IS NULL"),
            ("collections spanning 2 merge_methods (must be 0)",
             f'SELECT COUNT(*) FROM (SELECT "Collection" FROM {table} '
             f'WHERE "Collection" IS NOT NULL AND merge_method IS NOT NULL GROUP BY 1 '
             f"HAVING COUNT(DISTINCT merge_method) > 1 "
             f"OR COUNT(DISTINCT COALESCE(merge_add_columns,'~')) > 1)"),
            (f"'{LABEL}' rows still carrying merge_add_columns (must be 0)",
             f"SELECT COUNT(*) FROM {table} WHERE merge_method = '{LABEL}' "
             f"AND merge_add_columns IS NOT NULL"),
            ("total rows",  f"SELECT COUNT(*) FROM {table}"),
        ]
        for label, q in checks:
            print(f"  {label:<52}: {con.execute(q).fetchone()[0]}")
        print("  collections remaining :",
              con.execute(f'SELECT COUNT(DISTINCT "Collection") FROM {table}').fetchone()[0])
    finally:
        con.execute("DROP TABLE IF EXISTS _small")
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Dissolve collections below a size threshold.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--table", default=TABLE)
    p.add_argument("--min-size", type=int, default=5,
                   help="Collections with fewer than this many datasets are dissolved.")
    a = p.parse_args()
    main(a.dry_run, a.db, a.table, a.min_size)
