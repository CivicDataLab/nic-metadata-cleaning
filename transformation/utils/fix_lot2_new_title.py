"""Put the subject back on lot 2 (dublin_core_remaining) new_title values that lost it.

84 non-mergeable datasets, nearly all Rajya Sabha answers, carried an LLM
new_title that named only the question ("Rajya Sabha Unstarred Question Answers
for Session 241, Question No. 212"), named another subject, or kept the subject
and dropped its period, date, number or scheme. For these rows new_title is the
portal title ("remaining-raw-datasets".title) with its wording kept and only
the form cleaned:
  - the "(From: Ministry ...)" source note dropped, as on the rest of lot 2
  - Title Case, small words lower, acronyms as written
  - spacing around brackets, slashes and commas; ";" used for "," put right
  - six misspellings or stray words (Appoved, incuding, "up gradation",
    "Cooperatives Societies", "District-wise of", "as on Dated")
Nothing is reworded, reordered, expanded or dropped. The titles were written by
hand, row by row, so there is no --build.

Source of truth: data/lot2_new_title_changes.csv
(nid, UUID, merge_method, raw_title, old_new_title, new_title). To change or
revert a title, edit the CSV and re-run, then rebuild the copies with both
export_all_lots.py runs.

Usage: python fix_lot2_new_title.py [--dry-run]
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CHANGES = HERE.parent.parent / "data" / "lot2_new_title_changes.csv"
TABLE = "dublin_core_remaining"
DRY = "--dry-run" in sys.argv

con = duckdb.connect(DB_PATH, read_only=DRY)
ch = pd.read_csv(CHANGES, dtype=str)
con.register("ch", ch)
cur = con.execute(f"""
    SELECT c.nid, d.new_title AS cur, d."Collection" AS coll, c.old_new_title AS old, c.new_title AS new
    FROM ch c LEFT JOIN {TABLE} d ON d.nid::VARCHAR = c.nid""").df()
bad = cur[~((cur.cur == cur.old) | (cur.cur == cur.new)) | cur.coll.notna()]
assert bad.empty, f"rows that hold neither name or are in a collection\n{bad}"
todo = cur[cur.cur != cur.new]
print(f"{TABLE}: {len(ch)} listed, {len(todo)} to write, {len(ch) - len(todo)} already done")
if not DRY and len(todo):
    n = con.execute(f"""
        UPDATE {TABLE} AS d SET new_title = c.new_title FROM ch c
        WHERE d.nid::VARCHAR = c.nid AND d.new_title = c.old_new_title AND d.new_title <> c.new_title
        RETURNING 1""").fetchall()
    assert len(n) == len(todo), (len(n), len(todo))
    print(f"  {len(n)} rows updated")
con.close()
