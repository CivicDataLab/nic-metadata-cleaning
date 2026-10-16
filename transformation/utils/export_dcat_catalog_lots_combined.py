"""DCAT version of export_catalog_lots_combined.py.

Renames the catalog-level Dublin Core columns of dublin_core_catalog_lot1 and
dublin_catalog_lot2n3 to DCAT terms (dataset-level MAPPING in build_dcat_mapping.py),
stacks them, and adds the same 'Relation' and 'raw' sheets plus a 'column_map' sheet.
The stacked rows are also written to the table dcat_catalog_all_lots (full
dcterms:relation, no Excel truncation); a copy, re-run after either lot changes.

Usage: python export_dcat_catalog_lots_combined.py [--table-only | --no-table]

  Publisher ("Ministry;Dept;...") -> dcterms:publisher = ministry,
      dcat:hadRole = 'publisher' where there is a further body,
      prov:qualifiedAttribution[n] = each further body (slots from the data);
      "Government of India" is not a body: dropped, and cut off "Dept, Government of India".
  Contributor -> dcterms:contributor; Identifier -> dcat:landingPage.
  nid, new_catalog_title, group_catalog_name, Relation_from_api, unmappable_*: unchanged.
"""
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build_dcat_mapping import MAPPING  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
OUT = HERE.parent.parent / "data" / "dcat_transformed" / "dcat_catalog_all_lots.xlsx"
TABLE = "dcat_catalog_all_lots"
CELL_MAX = 32767
TABLE_ONLY, NO_TABLE = "--table-only" in sys.argv, "--no-table" in sys.argv
PAIRS = [("dublin_core_catalog_lot1", "catalog_metadata"),
         ("dublin_catalog_lot2n3", "remaining_catalog")]
EXTRA = {"Contributor": "dcterms:contributor", "Identifier": "dcat:landingPage"}
KEEP = {"Subject[sector]"}  # MAPPING keeps the name (dcat:theme reserved for sector_resource)
# The datasets' rule too (build_dcat_mapping.py, user 2026-10-14).
GOI = re.compile(r"\s*,\s*Government of India\s*$", re.I)


def bodies(cell):
    """The ministry, then each further body; "Government of India" is none of them."""
    p = [x.strip() for x in cell.split(";") if x.strip()]
    rest = (GOI.sub("", x) for x in p[1:])
    return p[:1] + [x for x in rest if x and x.lower() != "government of india"]


def to_dcat(d):
    parts = d["Publisher"].fillna("").apply(bodies)
    n = max(parts.str.len().max() - 1, 0)
    cmap, cols = [], {}
    out = {}
    for c in d.columns:
        if c == "Publisher":
            out["dcterms:publisher"] = parts.str[0]
            cmap.append((c, "dcterms:publisher", "ministry (text before first ';')"))
            out["dcat:hadRole"] = parts.apply(lambda p: "publisher" if len(p) > 1 else None)
            cmap.append((c, "dcat:hadRole", "'publisher' where there is a prov:qualifiedAttribution"))
            for i in range(1, n + 1):
                out[f"prov:qualifiedAttribution[{i}]"] = parts.apply(
                    lambda p, i=i: p[i] if len(p) > i else None)
                cmap.append((c, f"prov:qualifiedAttribution[{i}]", f"body {i} after ministry"))
            continue
        term = EXTRA.get(c) or ("" if c in KEEP else MAPPING.get(c, ("",))[0])
        name = term or c
        out[name] = d[c]
        cmap.append((c, name, "renamed" if term else "unchanged"))
    return pd.DataFrame(out), cmap


con = duckdb.connect(DB_PATH, read_only=NO_TABLE)
dub, raw, cmaps = [], [], []
for t, src in PAIRS:
    d = con.execute(f'SELECT * FROM {t} ORDER BY new_catalog_title, "Title", nid').df()
    d, cm = to_dcat(d)
    dub.append(d.assign(source_table=t))
    cmaps.append(cm)
    r = con.execute(f"SELECT * FROM {src} ORDER BY nid::BIGINT").df()
    r.columns = [c.replace(":", "_") for c in r.columns]
    raw.append(r.assign(source_table=src))
dub = pd.concat(dub, ignore_index=True)
# slots seen in only one lot are appended last by concat; put them back after the role
att = [c for c in dub.columns if c.startswith("prov:qualifiedAttribution[")]
rest = [c for c in dub.columns if c not in att and c != "source_table"]
at = rest.index("dcat:hadRole") + 1
dub = dub[rest[:at] + att + rest[at:] + ["source_table"]]
raw = pd.concat(raw, ignore_index=True)
if not NO_TABLE:
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM dub")
    print(TABLE, con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0], "rows,", len(dub.columns), "columns")
con.close()
if TABLE_ONLY:
    sys.exit()
colmap = pd.DataFrame(dict.fromkeys([], []) or
                      [(a, b, c) for a, b, c in dict.fromkeys(x for cm in cmaps for x in cm)],
                      columns=["dublin_column", "dcat_column", "rule"])

rel = dub["dcterms:relation"].fillna("")
long = rel.str.len() > CELL_MAX
links = (dub.loc[rel != "", ["nid", "dcterms:title", "dcterms:relation"]]
         .assign(**{"dcterms:relation": lambda x: x["dcterms:relation"].str.split("; ")})
         .explode("dcterms:relation")
         .rename(columns={"nid": "catalog_nid", "dcterms:title": "catalog_title",
                          "dcterms:relation": "dataset_link"}))
dub.loc[long, "dcterms:relation"] = (rel[long].str.count("; ") + 1).astype(str) + \
    " datasets; full list on sheet 'Relation'"
for name, f in (("dcat", dub), ("raw", raw)):
    m = f.astype(str).apply(lambda s: s.str.len().max())
    assert m.max() <= CELL_MAX, (name, m.idxmax())

with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
    for sheet, f in (("dcat_catalog_all_lots", dub), ("Relation", links),
                     ("raw", raw), ("column_map", colmap)):
        f.to_excel(xw, sheet_name=sheet, index=False)
        ws = xw.sheets[sheet]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        w = f.astype(str).apply(lambda s: s.str.len().max())
        for i, c in enumerate(f.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(len(c), int(w[c])) + 2)
print(OUT, len(dub), len(raw), len(links), int(long.sum()))
print(list(dub.columns))
