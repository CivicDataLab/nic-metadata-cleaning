"""Apply the standardised new_catalog_title of unmerged catalogs (merge_flag = 'No').

Source of truth: data/catalog_title_work/unmerged/unmerged_catalog_title_changes.csv
(table, nid, Title, old_new_catalog_title, new_catalog_title, convention). Three
conventions only, nothing else in a name is touched:
  1  State/UT-wise, States/UTs, State/UT
  2  Full Form (ABBR) when a name gives both
  3  <Topic> : <City> for a catalog about one city

Written by nid to the catalog tables (new_catalog_title and Relation[Is Part Of])
and to remaining_catalog, the source of dublin_catalog_lot2n3; then to the
datasets of those catalogs in dublin_core_remaining and dublin_core_lot3
(new_catalog_title only, matched on the old name and the catalog's Title).
Idempotent: a row already holding the new name is skipped, a catalog row
holding neither name aborts. Re-run after fix_new_catalog_title_remaining.py
--apply or fill_remaining_catalog_from_lot3.py, which put the old names back.

To change or revert a name, edit the CSV and re-run, then rebuild the copies:
build_dcat_mapping.py --profile lot3 --materialize, both export_all_lots.py
runs and the two export_*catalog_lots_combined.py scripts.

Usage: python fix_unmerged_catalog_titles.py [--dry-run]
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CHANGES = HERE.parent.parent / "data" / "catalog_title_work" / "unmerged" / "unmerged_catalog_title_changes.csv"
SOURCE = {"dublin_catalog_lot2n3": "remaining_catalog"}  # lot 1's source has no new_catalog_title
DATASETS = ["dublin_core_remaining", "dublin_core_lot3"]
DRY = "--dry-run" in sys.argv

ch = pd.read_csv(CHANGES, dtype=str)
assert not ch.new_catalog_title.duplicated().any(), "two catalogs would get the same name"
con = duckdb.connect(DB_PATH, read_only=DRY)
con.register("ch", ch)
con.execute("BEGIN")
for table, part in ch.groupby("table"):
    cur = con.execute(f"""
        SELECT c.nid, t.new_catalog_title AS cur, t.merge_flag, c.old_new_catalog_title AS old,
               c.new_catalog_title AS new
        FROM ch c LEFT JOIN {table} t ON t.nid = c.nid::BIGINT WHERE c."table" = ?""", [table]).df()
    bad = cur[~((cur.cur == cur.old) | (cur.cur == cur.new)) | (cur.merge_flag != "No")]
    assert bad.empty, f"{table}: rows that hold neither name or are merged\n{bad}"
    todo = cur[cur.cur == cur.old]
    # a new name must not equal any name another catalog keeps
    clash = con.execute(f"""
        SELECT c.nid, c.new_catalog_title FROM ch c
        JOIN (SELECT nid, new_catalog_title FROM dublin_catalog_lot2n3
              UNION ALL SELECT nid, new_catalog_title FROM dublin_core_catalog_lot1) t
          ON t.new_catalog_title = c.new_catalog_title AND t.nid <> c.nid::BIGINT
        WHERE c."table" = ?""", [table]).df()
    assert clash.empty, f"{table}: new names already used by another catalog\n{clash}"
    print(f"{table}: {len(part)} listed, {len(todo)} to write, {len(part) - len(todo)} already done")
    if DRY or todo.empty:
        continue
    targets = [(table, "nid", ', "Relation[Is Part Of]" = c.new_catalog_title')]
    if table in SOURCE:
        targets.append((SOURCE[table], "nid::BIGINT", ""))
    for t, key, extra in targets:
        n = con.execute(f"""
            UPDATE {t} AS t SET new_catalog_title = c.new_catalog_title{extra}
            FROM ch c WHERE c."table" = ? AND t.{key} = c.nid::BIGINT
              AND t.new_catalog_title = c.old_new_catalog_title RETURNING 1""", [table]).fetchall()
        assert len(n) == len(todo), (t, len(n), len(todo))
        print(f"  {t}: {len(n)} rows updated")
for t in DATASETS:
    match = f"""FROM ch c WHERE t.new_catalog_title = c.old_new_catalog_title
                AND trim(t."Relation[Catalog Title]") = trim(c."Title")"""
    if DRY:
        n = con.execute(f"SELECT count(*) FROM {t} AS t WHERE EXISTS (SELECT 1 {match})").fetchone()[0]
    else:
        n = len(con.execute(f"UPDATE {t} AS t SET new_catalog_title = c.new_catalog_title {match} "
                            "RETURNING 1").fetchall())
    left = con.execute(f"SELECT count(*) FROM {t} WHERE new_catalog_title IN "
                       "(SELECT old_new_catalog_title FROM ch)").fetchone()[0]
    print(f"{t}: {n} dataset rows {'to write' if DRY else 'updated'}, {left} still on an old name")
con.execute("ROLLBACK" if DRY else "COMMIT")
con.close()
