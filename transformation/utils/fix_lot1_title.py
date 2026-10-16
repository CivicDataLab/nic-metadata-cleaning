"""Replace the lot 1 Titles whose LLM rewrite got a fact wrong.

Title on dublin_core_metadata is an LLM rewrite of the raw title on 5,362 rows.
A rewording that keeps every fact stays ("Data Item Comparison Report of Haora
(West Bengal) for 2012-2013 & 2011-2012" -> "District Level Health Data Item
Comparison for Haora, West Bengal (2011-2012 and 2012-2013)"). A Title is
replaced by the raw title, cleaned in form only (fix_lot1_new_title.clean),
where the rewrite
  - dropped or added a year, a month or another number
  - dropped or changed the measure (Number of, Percentage, Rate, Average, Ratio)
  - dropped or added a qualifier (rural, tribal, male, female, provisional ...)
  - turned "as on" into "upto", or State/UT into State
  - dropped a district, a survey or another named term, or a state whose
    district name two states share
  - or, read by hand, changed the subject or added something the raw title
    does not say
A dropped state next to a district that stays is left alone, and so are
respelt districts (Haora -> Howrah).

Source of truth: data/lot1_title_changes.csv
(nid, UUID, merge_method, Collection, raw_title, old_title, Title, reason).
To change or revert a Title, edit the CSV and re-run. new_unmerged_dataset_title
and new_unmerged_dataset_description are built from Title: re-run
fill_new_unmerged_dataset_title.py and fill_new_unmerged_dataset_description.py
afterwards, then both export_all_lots.py runs.

Usage: python fix_lot1_title.py [--dry-run]
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CHANGES = HERE.parent.parent / "data" / "lot1_title_changes.csv"
TABLE = "dublin_core_metadata"
DRY = "--dry-run" in sys.argv

ch = pd.read_csv(CHANGES, dtype=str)
assert not ch.nid.duplicated().any(), "a nid is listed twice"
con = duckdb.connect(DB_PATH, read_only=DRY)
con.register("ch", ch)
cur = con.execute(f"""
    SELECT c.nid, d."Title" AS cur, c.old_title AS old, c."Title" AS new
    FROM ch c LEFT JOIN {TABLE} d ON d.nid::VARCHAR = c.nid""").df()
bad = cur[~((cur.cur == cur.old) | (cur.cur == cur.new))]
assert bad.empty, f"rows that hold neither title\n{bad}"
todo = cur[cur.cur != cur.new]
print(f"{TABLE}: {len(ch)} listed, {len(todo)} to write, {len(ch) - len(todo)} already done")
if not DRY and len(todo):
    n = con.execute(f"""
        UPDATE {TABLE} AS d SET "Title" = c."Title" FROM ch c
        WHERE d.nid::VARCHAR = c.nid AND d."Title" = c.old_title AND d."Title" <> c."Title"
        RETURNING 1""").fetchall()
    assert len(n) == len(todo), (len(n), len(todo))
    print(f"  {len(n)} rows updated")
con.close()
