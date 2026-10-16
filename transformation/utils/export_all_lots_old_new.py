#!/usr/bin/env python3
"""
Export the combined all-lots sheet in the old / new layout: every dataset's raw
(OGD) value beside its mapped value, field by field.

  dublin_core_all_lots_old_new.xlsx  sheet "raw_vs_dublin"  <- dublin_core_all_lots
  dcat_all_lots_old_new.xlsx         sheet "raw_vs_dcat"    <- dcat_all_lots  (--dcat)

The layout is the one of dataset_distribution_ogd_dcat_mapping.csv, as in the
top 50 workbook (hvd_scoring/Top 50 High value Datasets - Dublin and DCAT.xlsx):

  row 1  lot, nid, then "old", "new" for each field
  row 2  under old the raw field's name -- "<term> (no OGD field)" where no
         lot's raw table has one, the names joined with " | " where the lots
         spell it differently -- and under new the Dublin Core column or DCAT
         term, "<name> (no DCAT field)" for a column carried without a term
  rows   one per dataset, in the combined table's order. old is the value in
         the lot's raw table (raw_metadata, remaining-raw-datasets, lot3_raw),
         matched on nid, or "NA" where that raw table has no such field. new is
         the combined table's cell. A new cell that differs from its old cell
         is filled yellow; a blank prov:qualifiedAttribution is not a change.

Fields come in the reference sheet's order first, then as the combined sheet has
them. A field with nothing on either side in any lot is left out, unless it is a
Dublin Core element (a reference field, for --dcat).

The new side is read from the combined table, so run export_all_lots.py (with
--dcat for the DCAT one) first if a lot table changed. Nothing is written to the
database.

The sheet is about 200 columns by 354,000 rows. To keep its XML under the 2 GiB
a plain zip entry may hold, text goes to xl/sharedStrings.xml wherever that is
shorter: every value of a column that repeats its values, and a value that is
the same on the old and the new side of a row.

Like the other exports, it does not overwrite a workbook that is open in
WPS/LibreOffice/Excel: it writes a timestamped copy beside it and says so.

A few datasets only (--nids): only those rows, written to
<table name>_old_new_<n>_nids.xlsx. With --nids, --one-header-row or --csv the sheet is in
the format of the user's edit of the 6-dataset sheets: no lot column, and the
fields, their order and their old names are those of data/old_new_sample_layout.csv
when it lists the sheet. With --one-header-row the two header rows
become one, "old <OGD field>" / "new <column>" (the OGD field names of the lots
in the sheet; "old <column> (no OGD field)" where there is none).
--csv writes the same rows as CSV (<table name>_old_new.csv): one header row,
UTF-8, nothing coloured, no cell cut to Excel's 32,767 characters.
With --unmerged-titles the new Title (dcterms:title) is new_unmerged_dataset_title
and the new Relation[Catalog Title] (dcat:inCatalog) is new_catalog_title, which
on a catalog with merge_flag No is that catalog's own, unmerged title.

Usage:
  python3 export_all_lots_old_new.py            # raw vs Dublin Core
  python3 export_all_lots_old_new.py --dcat     # raw vs DCAT
  python3 export_all_lots_old_new.py --out /path/to/file.xlsx
  python3 export_all_lots_old_new.py --nids 604859456 603491108 --one-header-row --unmerged-titles
  python3 export_all_lots_old_new.py --one-header-row --unmerged-titles   # all datasets, same format
  python3 export_all_lots_old_new.py [--dcat] --csv --unmerged-titles     # the same as CSV
"""

import argparse
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb

import add_raw_sheet as raw
import export_all_lots as eal
import export_dublin_metadata as edm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import metdata_transform_dublin as mt  # noqa: E402

q = eal.q
TRANSFORMATION = Path(edm.REPO) / "transformation"
# DCAT manifest (build_dcat_mapping.py) of each lot, by its Dublin Core table.
MANIFESTS = {
    edm.TABLE: "dcat_mapping_manifest.csv",
    edm.REMAINING_TABLE: "dcat_mapping_manifest_remaining.csv",
    edm.LOT3_TABLE: "dcat_mapping_manifest_lot3.csv",
}
SHEETS = {"dublin_core_all_lots": "raw_vs_dublin", "dcat_all_lots": "raw_vs_dcat"}
NO_OGD, NO_DCAT, NA = " (no OGD field)", " (no DCAT field)", "NA"
# The reference sheet's fields, in its order, under their DCAT names.
REF_ORDER = [
    "dcterms:title", "dcterms:description", "dcat:theme", "dcterms:created", "dcterms:issued",
    "dcterms:modified", "dcterms:type", "dcat:byteSize", "dcat:mediaType", "dcterms:relation",
    "dcterms:identifier", "dcat:landingPage", "dcterms:source", "dcterms:spatial",
    "dcterms:temporal", "dcatin:jurisdictionLevel", "dcatin:applicableLegislation",
    "dcterms:accessRights", "dcterms:accrualPeriodicity", "dcat:temporalResolution",
    "dcat:keyword", "dcat:keyword[sponsored]", "Subject[sector]", "dcat:downloadURL",
    "dcat:accessURL", "foaf:depiction", "dcat:inCatalog", "vcard:fn", "vcard:hasEmail",
    "dcterms:rights", "dcatin:hvdCategory", "dcterms:accrualMethod", "dcterms:creator",
    "dcterms:publisher", "dcat:hadRole", "prov:qualifiedAttribution[1]", "prov:qualifiedAttribution[2]",
    "prov:qualifiedAttribution[3]", "dcatin:note", "dcterms:license", "dcterms:language",
    "dcterms:abstract", "dcterms:alternative", "dcat:endpointURL", "dcterms:hasPart",
    "dcterms:isPartOf", "dcterms:isReferencedBy", "dcterms:isReplacedBy", "dcterms:replaces",
    "dcterms:isVersionOf", "dcterms:hasVersion", "dcat:endpointDescription", "Collection",
    "ogdp_view_count", "ogdp_download_count", "field_show_export", "external_api_reference",
    "is_api_available", "is_visualized", "field_from_api",
]
# --nids / one-row / CSV sheets: the columns, their order and the "old" names of the
# user's own edit of the 6-dataset sheets, by sheet (2026-10-15: the headers of their
# CSVs in ~/Desktop/Old-new comparison sheet CSV; catalog sheets too, read by
# export_catalog_old_new.py). Edit it to change them.
SAMPLE_LAYOUT = Path(edm.REPO) / "data" / "old_new_sample_layout.csv"
# --unmerged-titles: the combined-table column shown as new, by Dublin Core column.
UNMERGED = {"Title": "new_unmerged_dataset_title", "Relation[Catalog Title]": "new_catalog_title"}
BATCH = 2_000
SLICE = 20_000                # rows per lot query (see lot_query)
# A column is written through the shared-string table when its values repeat at
# least this often on average.
REPEATS = 2.0
WIDTH_SAMPLE = 3_000          # rows per lot that set the column widths
# xl/styles.xml cellXfs, by index.
PLAIN, HEAD, OLD_HEAD, NEW_HEAD, FIELD, OLD_FIELD, NEW_FIELD, CHANGED = range(8)
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="5"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    + "".join(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{rgb}"/>'
              '<bgColor indexed="64"/></patternFill></fill>' for rgb in ("D9D9D9", "C6E0B4", "FFF2CC"))
    + '</fills><borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="8">'
    + "".join(
        f'<xf numFmtId="0" fontId="{font}" fillId="{fill}" borderId="0" xfId="0"'
        + (' applyFont="1"' if font else "") + (' applyFill="1"' if fill else "")
        + (' applyAlignment="1"><alignment horizontal="center"/></xf>' if centre else "/>")
        for font, fill, centre in (
            (0, 0, False),                                     # PLAIN
            (1, 0, True), (1, 2, True), (1, 3, True),          # row 1: lot / nid, old, new
            (1, 0, False), (1, 2, False), (1, 3, False),       # row 2
            (0, 4, False)))                                    # CHANGED
    + '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def raw_source(src: str, raw_cols: list[str], aliases: dict) -> tuple[str, str] | None:
    """-> (raw field label, SQL over the raw table's text columns) for one Dublin
    Core column, or None when the raw table has nothing for it."""
    low = {c.lower(): c for c in raw_cols}
    text = lambda c: f"coalesce(r.{q(c)}, '')"
    ogd = mt.FIELD_MAPPING.get(src)
    if ogd:
        col = {v: k for k, v in aliases.items()}.get(ogd, ogd)
        if col in raw_cols:
            return col, f"r.{q(col)}"
    if src == "Identifier[landing_page]" and {"domain", "node_alias"} <= set(raw_cols):
        return "domain+node_alias", f"{text('domain')} || {text('node_alias')}"
    if src == "Temporal Coverage" and {"data_time_period_from", "data_time_period_to"} <= set(raw_cols):
        a, b = text("data_time_period_from"), text("data_time_period_to")
        return ("data_time_period_from, data_time_period_to",
                f"CASE WHEN trim({a}) <> '' OR trim({b}) <> '' THEN 'from: ' || {a} || ', to: ' || {b} END")
    if src == "Spatial Coverage" and "spatial_coverage" in raw_cols:
        return "spatial_coverage", f"r.{q('spatial_coverage')}"
    if src.lower() in low:
        return low[src.lower()], f"r.{q(low[src.lower()])}"
    return None


def nonblank(expr: str) -> str:
    return f"count(*) FILTER (WHERE trim(CAST({expr} AS VARCHAR)) <> '')"


def plan(con, kind, unmerged: bool = False) -> dict:
    """Everything the writer needs: the kept fields, their header labels, and per
    lot the raw table's text SELECT and each field's old expression."""
    table, lots = kind["name"], kind["lots"]
    dcat = kind is eal.DCAT
    columns, _, sources = eal.plan_columns(con, lots, kind["priority"])
    drop = {c.lower() for c in kind.get("drop", [])}        # as export_all_lots.py does
    columns = [c for c in columns if c.lower() not in drop]
    have = [name for name, *_ in con.execute(f"DESCRIBE {q(table)}").fetchall()]
    if have != columns:
        sys.exit(f"{table} does not match the lot tables any more - run export_all_lots.py"
                 f"{' --dcat' if dcat else ''} first.")

    # DCAT column -> Dublin Core column, per lot, from the mapping manifests.
    dublin_tables = [t for _, t, _, _ in eal.DUBLIN["lots"]]
    dcat_source, passthrough = [], set()
    for dublin_table in dublin_tables:
        with open(TRANSFORMATION / MANIFESTS[dublin_table], encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        dcat_source.append({m["dcat_column"]: m["source_column"] for m in rows if m["dcat_column"]})
        passthrough |= {m["dcat_column"] for m in rows if m["action"] == "unchanged"}

    def dublin_column(i: int, field: str) -> str | None:
        """The Dublin Core column behind a sheet column on lot i, if that lot has it."""
        own = sources[lots[i][1]].get(field)
        if own is None:
            return None
        return (dcat_source[i].get(own[0]) or None) if dcat else own[0]

    fields = [c for c in columns[1:] if c.lower() != "nid"]
    if dcat:
        lead = [c for c in REF_ORDER if c in fields]
        always = set(REF_ORDER)
        label = lambda f: f + NO_DCAT if f in passthrough else f
    else:
        # The reference fields under their Dublin Core names, through the manifests.
        lead = []
        for term in REF_ORDER:
            for i in range(len(lots)):
                source = dcat_source[i].get(term)
                for f in fields:
                    if source and f not in lead and dublin_column(i, f) == source:
                        lead.append(f)
        always = {k for k in mt.FIELD_MAPPING if k != "batch"}
        label = lambda f: f
    fields = lead + [c for c in fields if c not in lead]

    filled = dict(zip(fields, con.execute(
        f"SELECT {', '.join(nonblank(q(f)) for f in fields)} FROM {q(table)}").fetchone()))
    distinct = dict(zip(fields, con.execute(
        f"SELECT {', '.join(f'approx_count_distinct({q(f)})' for f in fields)} FROM {q(table)}").fetchone()))

    # A lot whose table lacks a column still has the raw field behind it (lot 1 has
    # no prov:qualifiedAttribution[3], but its raw rows have ministry_department).
    elsewhere = {f: next((s for s in (dublin_column(i, f) for i in range(len(lots))) if s), None)
                 for f in fields}

    per_lot, old_labels, old_filled, old_distinct = [], {}, {}, {}
    for i, (lot, _, raw_table, _) in enumerate(lots):
        described = [(n, t) for n, t, *_ in con.execute(f"DESCRIBE {q(raw_table)}").fetchall()]
        raw_cols = [n for n, _ in described]
        raw_select = (f"SELECT rowid AS rrid, "
                      + ", ".join(f"{raw.text_expr(con, raw_table, n, t)} AS {q(n)}" for n, t in described)
                      + f" FROM {q(raw_table)}")
        aliases = mt.SOURCE_PROFILES[raw_table]["aliases"]
        old, labels = {}, {}
        for f in fields:
            src = dublin_column(i, f) or elsewhere[f]
            found = raw_source(src, raw_cols, aliases) if src else None
            if found:
                old[f] = found[1]
                labels[f] = found[0]
                old_labels.setdefault(f, []).append(found[0])
        if old:
            stats = con.execute(
                "SELECT " + ", ".join(f"{nonblank(e)}, approx_count_distinct({e})" for e in old.values())
                + f" FROM ({raw_select}) r").fetchone()
            for j, f in enumerate(old):
                old_filled[f] = old_filled.get(f, 0) + stats[2 * j]
                old_distinct[f] = old_distinct.get(f, 0) + stats[2 * j + 1]
        per_lot.append({"lot": lot, "raw_table": raw_table, "raw_select": raw_select, "old": old,
                        "labels": labels})

    kept = [f for f in fields if f in always or filled[f] or old_filled.get(f)]
    repeats = lambda n, d: bool(n) and n >= REPEATS * max(d, 1)
    new_from = {f: UNMERGED[elsewhere[f]] for f in kept if unmerged and elsewhere[f] in UNMERGED}
    if unmerged and (len(new_from) != len(UNMERGED) or not set(new_from.values()) <= set(have)):
        sys.exit(f"{table}: cannot show the unmerged titles ({new_from})")
    return {
        "table": table,
        "fields": kept,
        "new_from": new_from,
        "only": "",
        "lead": ["lot", "nid"],
        "dropped": [f for f in fields if f not in kept],
        "head": {f: (" | ".join(dict.fromkeys(old_labels.get(f, []))) or f + NO_OGD, label(f)) for f in kept},
        "quiet_blank": {f for f in kept if f.startswith("prov:qualifiedAttribution")},
        "share_new": {f for f in kept if repeats(filled[f], distinct[f])},
        "share_old": {f for f in kept if repeats(old_filled.get(f, 0), old_distinct.get(f, 0))},
        "lots": per_lot,
        "old_head": {f: old_label(f, per_lot) for f in kept},
    }


def old_label(f: str, lots: list[dict]) -> str:
    """The raw (OGD) field name of field f in these lots, joined with " | " where
    they spell it differently, or "<f> (no OGD field)"."""
    return " | ".join(dict.fromkeys(lot["labels"][f] for lot in lots if f in lot["labels"])) or f + NO_OGD


def lot_query(con, p: dict, lot: dict) -> tuple[list[str], list[tuple]]:
    """-> (SELECTs of one lot's rows, SLICE rows each, in table order,
    [(old position or None, new position)]). Position 0 is the nid; a raw row is
    matched on nid, and among rows that share a nid (or have none) by their order
    in the table. Slicing keeps the join to the raw table inside a small memory
    limit: each slice joins only its own raw rows."""
    table = p["table"]
    select, layout = ["m.nid"], []
    for f in p["fields"]:
        at = None
        if f in lot["old"]:
            at = len(select)
            select.append(lot["old"][f])
        layout.append((at, len(select)))
        select.append(f"m.{q(p['new_from'].get(f, f))}")
    nth = "row_number() OVER (PARTITION BY nid ORDER BY rowid)"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE pair AS
        WITH mk AS (SELECT rowid AS rid, nid, {nth} AS k FROM {q(table)} WHERE lot = '{lot["lot"]}'{p["only"]}),
             rk AS (SELECT rowid AS rrid, CAST(nid AS VARCHAR) AS nid, {nth} AS k FROM {q(lot["raw_table"])})
        SELECT mk.rid, rk.rrid FROM mk LEFT JOIN rk ON rk.nid IS NOT DISTINCT FROM mk.nid AND rk.k = mk.k""")
    rids = [r for r, in con.execute("SELECT rid FROM pair ORDER BY rid").fetchall()]
    sqls = []
    for at in range(0, len(rids), SLICE):
        lo, hi = rids[at], rids[min(at + SLICE, len(rids)) - 1]
        sqls.append(f"""
            WITH pr AS (SELECT rid, rrid FROM pair WHERE rid BETWEEN {lo} AND {hi})
            SELECT {', '.join(select)}
            FROM {q(table)} m JOIN pr ON pr.rid = m.rowid
            LEFT JOIN (SELECT * FROM ({lot["raw_select"]}) WHERE rrid IN (SELECT rrid FROM pr)) r
                   ON r.rrid = pr.rrid
            WHERE m.rowid BETWEEN {lo} AND {hi}
            ORDER BY m.rowid""")
    return sqls, layout


def batches(con, sqls: list[str]):
    """The rows of each query in turn, BATCH at a time."""
    for sql in sqls:
        cur = con.execute(sql)
        while rows := cur.fetchmany(BATCH):
            yield rows


class Strings:
    """xl/sharedStrings.xml, written as it grows. `seen` holds only the strings
    worth finding again; a string shared within one row is added without it."""

    def __init__(self, path: str):
        self.file = open(path, "w", encoding="utf-8")
        self.seen, self.count, self.uses, self.pending = {}, 0, 0, []
        self.add(NA, remember=True)

    def add(self, v: str, remember: bool) -> int:
        k = self.count
        self.count += 1
        if remember:
            self.seen[v] = k
        self.pending.append(f"<si>{eal.text_xml(v)}</si>")
        return k

    def flush(self):
        self.file.write("".join(self.pending))
        self.pending.clear()

    def close(self):
        self.flush()
        self.file.close()


def write_rows(con, p: dict, body: str, strings: Strings) -> tuple[int, list[list[int]], dict]:
    """Write the data rows to `body` -> (rows, sampled cell lengths per sheet column, counts)."""
    fields = p["fields"]
    seen, add = strings.seen, strings.add
    changed_style = f' s="{CHANGED}"'
    lengths = [[] for _ in range(2 + 2 * len(fields))]
    counts = {"changed": 0, "na": 0, "unmatched": 0}
    written = 0

    def cell(v: str, share: bool, style: str) -> str:
        k = seen.get(v)
        if k is None and share:
            k = add(v, True)
        if k is None:
            return f'<c{style} t="inlineStr"><is>{eal.text_xml(v)}</is></c>'
        strings.uses += 1
        return f'<c{style} t="s"><v>{k}</v></c>'

    with open(body, "w", encoding="utf-8") as sheet:
        for lot in p["lots"]:
            sqls, layout = lot_query(con, p, lot)
            spec = [(o, n, f in p["share_old"], f in p["share_new"], f in p["quiet_blank"])
                    for f, (o, n) in zip(fields, layout)]
            lot_cell = f'<c t="s"><v>{seen.get(lot["lot"]) or add(lot["lot"], True)}</v></c>'
            done = 0
            for rows in batches(con, sqls):
                out = []
                for row in rows:
                    sample = done < WIDTH_SAMPLE
                    done += 1
                    nid = row[0]
                    out.append("<row>" + (lot_cell if "lot" in p["lead"] else "")
                               + ("<c/>" if nid is None else cell(nid, False, "")))
                    for i, (o_at, n_at, share_old, share_new, quiet) in enumerate(spec):
                        new = row[n_at]
                        if new is None:
                            new = ""
                        elif new is True or new is False:
                            new = "TRUE" if new else "FALSE"
                        if o_at is None:
                            old, o_cell = "", '<c t="s"><v>0</v></c>'            # NA
                            counts["na"] += 1
                        else:
                            old = row[o_at]
                            if old is None:
                                old = ""
                            elif old is True or old is False:
                                old = "TRUE" if old else "FALSE"
                            o_cell = None
                        if old == new:
                            if not new:
                                out.append((o_cell or "<c/>") + "<c/>")
                            else:
                                # one string, two cells: shared even when the column is not
                                k = seen.get(new)
                                if k is None:
                                    k = add(new, share_old or share_new)
                                ref = f'<c t="s"><v>{k}</v></c>'
                                strings.uses += 2
                                out.append(ref + ref)
                        else:
                            if o_cell is None:
                                o_cell = cell(old, share_old, "") if old else "<c/>"
                            style = ""
                            if old.strip() != new.strip() and not (quiet and not new.strip()):
                                style = changed_style
                                counts["changed"] += 1
                            out.append(o_cell + (cell(new, share_new, style) if new else f"<c{style}/>"))
                        if sample:
                            lengths[2 + 2 * i].append(2 if o_at is None else len(old))
                            lengths[3 + 2 * i].append(len(new))
                    if sample:
                        lengths[1].append(len(nid or ""))
                    out.append("</row>")
                sheet.write("".join(out))
                strings.flush()
            written += lot_done(con, p, lot, done, counts)
    return written, lengths, counts


def lot_done(con, p: dict, lot: dict, done: int, counts: dict) -> int:
    """Check that all of a lot's rows were written and count those with no raw row."""
    expected = con.execute(
        f"SELECT count(*) FROM {q(p['table'])} WHERE lot = '{lot['lot']}'{p['only']}").fetchone()[0]
    if done != expected:
        sys.exit(f"{lot['lot']}: wrote {done} rows, expected {expected}")
    counts["unmatched"] += con.execute(f"""
        SELECT count(*) FROM {q(p['table'])} m WHERE lot = '{lot["lot"]}'{p["only"]} AND NOT EXISTS
          (SELECT 1 FROM {q(lot['raw_table'])} r WHERE CAST(r.nid AS VARCHAR) IS NOT DISTINCT FROM m.nid)
        """).fetchone()[0]
    print(f"  {lot['lot']}: {done} rows, old from {lot['raw_table']}, "
          f"{len(lot['old'])} of {len(p['fields'])} fields have a raw field")
    return done


def plain(v) -> str:
    """A cell's text: '' for NULL, TRUE / FALSE for a boolean."""
    if v is None:
        return ""
    if v is True or v is False:
        return "TRUE" if v else "FALSE"
    return str(v)


def write_csv(con, p: dict, path) -> tuple[int, dict]:
    """--csv: the rows of write_rows, as one header row and plain text -> (rows, counts).
    Changed cells are counted the same way but cannot be coloured."""
    fields = p["fields"]
    quiet = [f in p["quiet_blank"] for f in fields]
    counts = {"changed": 0, "na": 0, "unmatched": 0}
    written = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(p["lead"] + [h for f in fields for h in (f"old {p['old_head'][f]}", f"new {f}")])
        for lot in p["lots"]:
            sqls, layout = lot_query(con, p, lot)
            lead = [lot["lot"]] if "lot" in p["lead"] else []
            done = 0
            for rows in batches(con, sqls):
                for row in rows:
                    line = lead + [plain(row[0])]
                    for i, (o_at, n_at) in enumerate(layout):
                        new = plain(row[n_at])
                        old = "" if o_at is None else plain(row[o_at])
                        counts["na"] += o_at is None
                        if old.strip() != new.strip() and not (quiet[i] and not new.strip()):
                            counts["changed"] += 1
                        line += [NA if o_at is None else old, new]
                    out.writerow(line)
                done += len(rows)
            written += lot_done(con, p, lot, done, counts)
    return written, counts


def header_rows(p: dict, one_row: bool) -> str:
    text = lambda v, s: f'<c s="{s}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
    if one_row:
        return "<row>" + "".join(text(h, HEAD) for h in p["lead"]) + "".join(
            text(f"old {p['old_head'][f]}", OLD_HEAD) + text(f"new {f}", NEW_HEAD)
            for f in p["fields"]) + "</row>"
    one = "".join(text(h, HEAD) for h in p["lead"]) + (text("old", OLD_HEAD) + text("new", NEW_HEAD)) * len(p["fields"])
    two = f'<c s="{FIELD}"/>' * len(p["lead"]) + "".join(
        text(p["head"][f][0], OLD_FIELD) + text(p["head"][f][1], NEW_FIELD) for f in p["fields"])
    return f"<row>{one}</row><row>{two}</row>"


def column_widths(p: dict, lengths: list[list[int]], one_row: bool) -> str:
    """<cols>: wide enough for the header and for nine cells in ten, at most 50."""
    lengths = lengths[2 - len(p["lead"]):]                  # sampled with the lot column
    heads = p["lead"] + [label for f in p["fields"]
                              for label in ((f"old {p['old_head'][f]}", f"new {f}") if one_row else p["head"][f])]
    cols = []
    for i, (head, seen) in enumerate(zip(heads, lengths), 1):
        p90 = sorted(seen)[int(len(seen) * 0.9)] if seen else 0
        width = 12 if i <= len(p["lead"]) else min(max(len(head) + 2, p90 + 2, 10), 50)
        cols.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
    return "<cols>" + "".join(cols) + "</cols>"


def copy_in(zout, part: str, pieces: list):
    """Write one package part from strings and files, as ZIP64 only if it has to be."""
    size = sum(os.path.getsize(x) if isinstance(x, Path) else len(x.encode("utf-8")) for x in pieces)
    with zout.open(part, "w", force_zip64=size >= raw.ZIP64_LIMIT) as dst:
        for x in pieces:
            if isinstance(x, Path):
                with open(x, "rb") as src:
                    shutil.copyfileobj(src, dst, 1 << 22)
            else:
                dst.write(x.encode("utf-8"))
    return size


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=edm.DB_PATH)
    ap.add_argument("--dcat", action="store_true", help="raw vs DCAT, from dcat_all_lots")
    ap.add_argument("--out", help="output path (default: <table name>_old_new.xlsx / .csv in the repo root)")
    ap.add_argument("--memory-limit", default="3GB",
                    help="DuckDB memory for the per-lot join and sort; the rest spills to disk")
    ap.add_argument("--threads", type=int,
                    help="DuckDB threads (fewer need less memory: 2 fits the join in 1 GB)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite even if the file looks open in an office suite")
    ap.add_argument("--nids", nargs="+", metavar="NID", help="only these datasets")
    ap.add_argument("--one-header-row", action="store_true",
                    help='one header row, "old <OGD field>" / "new <column>"')
    ap.add_argument("--unmerged-titles", action="store_true",
                    help="new Title = new_unmerged_dataset_title, new Relation[Catalog Title] = new_catalog_title")
    ap.add_argument("--csv", action="store_true",
                    help="write a CSV (one header row, no yellow) instead of a workbook")
    args = ap.parse_args()
    nids = list(dict.fromkeys(n.strip(",") for n in args.nids or []))
    if not all(n.isdigit() for n in nids):
        sys.exit(f"--nids takes numbers: {nids}")

    kind = eal.DCAT if args.dcat else eal.DUBLIN
    sheet_name = SHEETS[kind["name"]]
    one_row = args.one_header_row or args.csv
    heads = 1 if one_row else 2
    ext = ".csv" if args.csv else ".xlsx"
    default = f"{kind['name']}_old_new_{len(nids)}_nids{ext}" if nids else f"{kind['name']}_old_new{ext}"
    out = Path(args.out) if args.out else eal.REPO / default
    holder = eal.wrapper.file_is_open(out)
    if holder and not args.force:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"! {out.name} is open in {holder} - not overwriting it.")
        out = out.with_name(f"{out.stem}_{ts}{out.suffix}")
        print(f"  Writing {out.name} instead (pass --force to override).")

    tmp = out.with_name(f".{out.stem}.{os.getpid()}.tmp")
    con = duckdb.connect(args.db, read_only=True)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            con.execute(f"SET temp_directory = '{tmpdir}'")
            con.execute(f"SET memory_limit = '{args.memory_limit}'")
            if args.threads:
                con.execute(f"SET threads = {args.threads}")
            p = plan(con, kind, args.unmerged_titles)
            print(f"{kind['name']} -> sheet {sheet_name!r}: {len(p['fields'])} field pairs"
                  f" ({len(p['dropped'])} left out, blank on both sides: {p['dropped']})")
            if p["new_from"]:
                print(f"  new side read from: {p['new_from']}")
            if nids:
                p["only"] = f" AND nid IN ({', '.join(repr(n) for n in nids)})"
                found = {n for n, in con.execute(
                    f"SELECT nid FROM {q(p['table'])} WHERE true{p['only']}").fetchall()}
                if missing := [n for n in nids if n not in found]:
                    sys.exit(f"not in {p['table']}: {missing}")
                present = {lot for lot, in con.execute(
                    f"SELECT DISTINCT lot FROM {q(p['table'])} WHERE true{p['only']}").fetchall()}
                p["old_head"] = {f: old_label(f, [lot for lot in p["lots"] if lot["lot"] in present])
                                 for f in p["fields"]}
            if nids or one_row:
                p["lead"] = ["nid"]
                with open(SAMPLE_LAYOUT, encoding="utf-8") as f:
                    layout = {r["new_column"]: r["old_label"] for r in csv.DictReader(f)
                              if r["sheet"] == p["table"]}
                if layout:
                    if missing := [f for f in layout if f not in p["fields"]]:
                        print(f"! in {SAMPLE_LAYOUT.name}, not in {p['table']}: {missing}")
                    print(f"  left out, as in {SAMPLE_LAYOUT.name}: {[f for f in p['fields'] if f not in layout]}")
                    p["fields"] = [f for f in layout if f in p["fields"]]
                    p["old_head"] = layout
            if args.csv:
                nrows, counts = write_csv(con, p, tmp)
                print(f"CSV: {nrows} rows x {len(p['lead']) + 2 * len(p['fields'])} columns; "
                      f"changed cells: {counts['changed']}; NA cells: {counts['na']}; "
                      f"datasets with no raw row: {counts['unmatched']}")
            else:
                body, sst = Path(tmpdir) / "rows.xml", Path(tmpdir) / "strings.xml"
                strings = Strings(str(sst))
                nrows, lengths, counts = write_rows(con, p, str(body), strings)
                strings.close()

                ncols = len(p["lead"]) + 2 * len(p["fields"])
                last = edm._col_letter(ncols)
                area = f"A{heads}:{last}{nrows + heads}"
                ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zout:
                    zout.writestr("[Content_Types].xml", edm._content_types(1).replace(
                        "</Types>", f'<Override PartName="/xl/sharedStrings.xml" ContentType="{eal.SST_TYPE}"/></Types>'))
                    zout.writestr("_rels/.rels", edm._ROOT_RELS)
                    zout.writestr("xl/workbook.xml", edm._workbook([sheet_name]).replace(
                        "<sheets>", "<bookViews><workbookView/></bookViews><sheets>").replace(
                        "</sheets>", '</sheets><definedNames><definedName name="_xlnm._FilterDatabase" '
                                     f"localSheetId=\"0\" hidden=\"1\">'{sheet_name}'!$A${heads}:${last}${nrows + heads}"
                                     "</definedName></definedNames>"))
                    zout.writestr("xl/_rels/workbook.xml.rels", edm._workbook_rels(1).replace(
                        "</Relationships>", f'<Relationship Id="rId3" Type="{eal.SST_REL}" '
                                            'Target="sharedStrings.xml"/></Relationships>'))
                    zout.writestr("xl/styles.xml", STYLES)
                    copy_in(zout, "xl/sharedStrings.xml", [
                        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst {ns} '
                        f'count="{strings.uses}" uniqueCount="{strings.count}">', sst, "</sst>"])
                    size = copy_in(zout, "xl/worksheets/sheet1.xml", [
                        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}>'
                        f'<dimension ref="A1:{last}{nrows + heads}"/>'
                        f'<sheetViews><sheetView workbookViewId="0"><pane xSplit="{len(p["lead"])}" ySplit="{heads}" '
                        f'topLeftCell="{edm._col_letter(len(p["lead"]) + 1)}{heads + 1}" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>'
                        + column_widths(p, lengths, args.one_header_row) + "<sheetData>"
                        + header_rows(p, args.one_header_row),
                        body, f'</sheetData><autoFilter ref="{area}"/></worksheet>'])
                print(f"Sheet {sheet_name!r}: {nrows} rows x {ncols} columns, "
                      f"{size / 1e9:.2f} GB of XML; {strings.count} shared strings "
                      f"({sst.stat().st_size / 1e9:.2f} GB), {len(strings.seen)} of them kept for reuse")
                print(f"  changed (yellow) cells: {counts['changed']}; NA cells: {counts['na']}; "
                      f"datasets with no raw row: {counts['unmatched']}")
                if size > zipfile.ZIP64_LIMIT:
                    print("! over 2 GiB: this sheet is stored as a ZIP64 entry, which some "
                          "spreadsheet programs cannot open.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    os.replace(tmp, out)
    print(f"Wrote {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
