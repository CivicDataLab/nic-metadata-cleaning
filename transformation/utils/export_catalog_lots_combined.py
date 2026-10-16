"""Export dublin_core_catalog_lot1 + dublin_catalog_lot2n3 stacked into one workbook,
with a 'raw' sheet stacking their source tables (catalog_metadata, remaining_catalog).
The stacked rows are also written to the table dublin_catalog_all_lots (full
Relation, no Excel truncation); it is a copy, re-run after either lot changes.

Usage: python export_catalog_lots_combined.py [--table-only | --no-table]
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
OUT = HERE.parent.parent / "data" / "dublin_core_transformed" / "dublin_catalog_all_lots.xlsx"
TABLE = "dublin_catalog_all_lots"
CELL_MAX = 32767
TABLE_ONLY, NO_TABLE = "--table-only" in sys.argv, "--no-table" in sys.argv
PAIRS = [("dublin_core_catalog_lot1", "catalog_metadata", "lot1"),
         ("dublin_catalog_lot2n3", "remaining_catalog", "lot2n3")]

con = duckdb.connect(DB_PATH, read_only=NO_TABLE)
dub, raw = [], []
for t, src, lot in PAIRS:
    d = con.execute(f'SELECT * FROM {t} ORDER BY new_catalog_title, "Title", nid').df()
    dub.append(d.assign(source_table=t))
    r = con.execute(f"SELECT * FROM {src} ORDER BY nid::BIGINT").df()
    r.columns = [c.replace(":", "_") for c in r.columns]
    raw.append(r.assign(source_table=src))
dub = pd.concat(dub, ignore_index=True)
raw = pd.concat(raw, ignore_index=True)
if not NO_TABLE:
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM dub")
    print(TABLE, con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0], "rows,", len(dub.columns), "columns")
con.close()
if TABLE_ONLY:
    sys.exit()

# Relation cells over Excel's limit: summarise, full list on sheet 'Relation'.
rel = dub["Relation"].fillna("")
long = rel.str.len() > CELL_MAX
links = (dub.loc[rel != "", ["nid", "Title", "Relation"]]
         .assign(Relation=lambda x: x["Relation"].str.split("; "))
         .explode("Relation")
         .rename(columns={"nid": "catalog_nid", "Title": "catalog_title", "Relation": "dataset_link"}))
dub.loc[long, "Relation"] = (rel[long].str.count("; ") + 1).astype(str) + " datasets; full list on sheet 'Relation'"
for name, f in (("dublin", dub), ("raw", raw)):
    m = f.astype(str).apply(lambda s: s.str.len().max())
    assert m.max() <= CELL_MAX, (name, m.idxmax())

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    for sheet, f in (("dublin_catalog_all_lots", dub), ("Relation", links), ("raw", raw)):
        f.to_excel(xw, sheet_name=sheet, index=False)
        ws = xw.sheets[sheet]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        w = f.astype(str).apply(lambda s: s.str.len().max())
        for i, c in enumerate(f.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(len(c), int(w[c])) + 2)
print(OUT, len(dub), len(raw), len(links), int(long.sum()))
