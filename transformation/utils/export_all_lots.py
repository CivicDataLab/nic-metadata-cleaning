#!/usr/bin/env python3
"""
Export the three Dublin Core lots as one workbook, dublin_core_all_lots.xlsx,
and as one table, dublin_core_all_lots.

  sheet "all_lots"  dublin_core_metadata, dublin_core_remaining and
                    dublin_core_lot3 stacked: lot 1 rows, then lot 2, then lot 3
  sheet "raw_lot1"  raw_metadata
  sheet "raw_lot2"  remaining-raw-datasets
  sheet "raw_lot3"  lot3_raw

The stacked sheet opens with a "lot" column and then follows each lot's own
export (export_dublin_metadata.py): the same columns are left out per lot, the
yellow PRIORITY_COLUMNS lead, dublin_core_metadata's columns follow in its
order, and the columns only lot 2 / lot 3 have come last in LOT_EXTRA_ORDER. A
lot 2 / lot 3 column that is a dublin_core_metadata column under another name
(Remark, year, month, ...) goes into that column. A column a lot does not have
is blank on its rows. ALL_LOTS_DROP lists the columns left out of the
stacked sheet and table altogether (the ones the user deleted 2026-10-14),
for the DCAT one too.

Every cell is text, so a column reads the same on all three lots: a lot 2 /
lot 3 BOOLEAN in a dublin_core_metadata column (headers_cleaned) is written as
that table holds it, '1' / '0'; one only those lots have (file_present) stays a
boolean. The raw sheets are written by add_raw_sheet.py's writer.

The table dublin_core_all_lots (metadata.db) is the stacked sheet as a table:
the same columns in the same order, the same text, the same row order. It is
rebuilt from the three lot tables on every run -- a copy, like the workbook, so
edit the lot tables and re-run rather than editing it. --no-table leaves it
alone and writes the workbook only, which needs no write lock on the database.

--dcat stacks the same lots under their DCAT names instead -- dcat_metadata,
dcat_remaining and dcat_lot3 (build_dcat_mapping.py) -- into dcat_all_lots.xlsx
and the table dcat_all_lots, arranged the same way: DCAT_PRIORITY_COLUMNS lead,
dcat_metadata's columns follow. dcat_lot3 is a table, so rebuild it first
(build_dcat_mapping.py --profile lot3 --materialize) if dublin_core_lot3 changed.

The stacked sheet is large (over 2 GB of XML with every cell an inline string),
and a part over 2 GiB has to be stored as a ZIP64 entry, which some spreadsheet
programs cannot open. Two things keep it well under that: text a column repeats
(lot, publisher, sector, licence, ...) is written once in xl/sharedStrings.xml
and referenced by index, up to SHARED_CAP distinct values per column, and
xml:space="preserve" is written only on a value with leading or trailing
whitespace -- what Excel itself does. The script says so if the part still
crosses the line.

Like the export wrapper, it does not overwrite a workbook that is open in
WPS/LibreOffice/Excel: it writes a timestamped copy beside it and says so.

Usage:
  python3 export_all_lots.py                  # table + workbook
  python3 export_all_lots.py --no-table       # workbook only
  python3 export_all_lots.py --no-workbook    # table only
  python3 export_all_lots.py --dcat           # the DCAT table + workbook
  python3 export_all_lots.py --out /path/to/file.xlsx
  python3 export_all_lots.py [--dcat] --per-lot ../../data/per_lot_sheets   # one workbook per lot

--per-lot DIR writes one workbook per lot instead (dublin_core_lot1.xlsx ...,
dcat_lot1.xlsx ...): the stacked sheet's rows of that lot, under the same
columns minus "lot" (a column the lot does not have is blank), no raw sheets.
It opens the database read-only and leaves the combined table alone.
"""

import argparse
import datetime as dt
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb

import add_raw_sheet as raw
import export_dublin_core_remaining as wrapper
import export_dublin_metadata as edm

REPO = Path(edm.REPO)
# What gets stacked. "name" is both the table and the workbook; "lots" are
# (label in the "lot" column, lot table, raw table, raw sheet name), the first
# being the lot whose arrangement the sheet follows.
# Deleted from the stacked Dublin sheet by the user, 2026-10-14, and left out of
# the DCAT one too. They stay in the lot tables; only the combined sheets and
# tables leave them out. The DCAT names are the same but for the full forms.
ALL_LOTS_DROP = [
    "batch", "archive_reason", "Remark for change in header",
    "Subject[keyword_fullform]", "state", "till_date", "temporal_source",
    "temporal_check", "spatial_states", "spatial_districts",
    "spatial_subdistricts", "spatial_level", "spatial_source", "file_present",
    "sponsored_keyword_search", "title_search", "sponsored_keyword_needed",
    "collection_sponsored_keyword_needed",
]
DCAT_NAMES = {"Subject[keyword_fullform]": "dcat:keyword[fullform]"}

DUBLIN = {
    "name": "dublin_core_all_lots",
    "priority": edm.PRIORITY_COLUMNS,
    "drop": ALL_LOTS_DROP,
    "lots": [
        ("Lot 1", edm.TABLE, "raw_metadata", "raw_lot1"),
        ("Lot 2", edm.REMAINING_TABLE, "remaining-raw-datasets", "raw_lot2"),
        ("Lot 3", edm.LOT3_TABLE, "lot3_raw", "raw_lot3"),
    ],
}
DCAT = {
    "name": "dcat_all_lots",
    "priority": edm.DCAT_PRIORITY_COLUMNS,
    "drop": [DCAT_NAMES.get(c, c) for c in ALL_LOTS_DROP],
    "lots": [
        ("Lot 1", edm.DCAT_TABLE, "raw_metadata", "raw_lot1"),
        ("Lot 2", "dcat_remaining", "remaining-raw-datasets", "raw_lot2"),
        ("Lot 3", "dcat_lot3", "lot3_raw", "raw_lot3"),
    ],
}
SHEET = "all_lots"
LOT_COLUMN = "lot"
BATCH = 5_000
# Distinct values one column may add to the shared-string table. A column of
# few values (lot, publisher, licence) fits whole; one of unique values (nid,
# Title) stops adding after this many and writes the rest inline.
SHARED_CAP = 2_000
SST_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
SST_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
q = raw.q


def table_columns(con, table: str) -> list[tuple[str, str]]:
    """(name, type) of the columns the lot's own export keeps, in table order."""
    exclude = {c.lower() for c in edm.LOT_EXCLUDE_COLUMNS.get(table, edm.EXCLUDE_COLUMNS)}
    return [(name, typ) for name, typ, *_ in con.execute(f"DESCRIBE {q(table)}").fetchall()
            if name.lower() not in exclude]


def column_expr(con, table: str, name: str, typ: str, shared: bool) -> str:
    """Text of one source column. A BOOLEAN that lands in a dublin_core_metadata
    column is written the way that table holds it, '1' / '0' (headers_cleaned)."""
    if shared and typ == "BOOLEAN":
        return f"CAST(CAST({q(name)} AS INTEGER) AS VARCHAR)"
    return raw.text_expr(con, table, name, typ)


def plan_columns(con, lots, priority) -> tuple[list[str], list[str], dict]:
    """-> (sheet columns, yellow columns, {table: {sheet column: (source name, type)}})."""
    ref = [name for name, _ in table_columns(con, lots[0][1])]
    by_lower = {c.lower(): c for c in ref}
    front = [by_lower[c.lower()] for c in priority if c.lower() in by_lower]
    order = front + [c for c in ref if c not in front]

    sources, extras = {}, []
    for _, table, _, _ in lots:
        mapped = {}
        for name, typ in table_columns(con, table):
            target = by_lower.get(edm.LOT_COLUMN_ALIASES.get(name, name).lower(), name)
            if target in mapped:
                sys.exit(f"{table}: {mapped[target][0]!r} and {name!r} both map to {target!r}")
            mapped[target] = (name, typ)
            if target not in by_lower.values() and target not in extras:
                extras.append(target)
        sources[table] = mapped
    extra_pos = {c.lower(): i for i, c in enumerate(edm.LOT_EXTRA_ORDER)}
    extras = [c for _, c in sorted(
        enumerate(extras), key=lambda ic: (0, extra_pos[ic[1].lower()]) if ic[1].lower() in extra_pos
        else (1, ic[0]))]
    columns = order + extras
    # A numbered column only some lots reach (prov:qualifiedAttribution[3]) sits
    # after the one before it, not at the end of the sheet.
    for c in extras:
        m = re.fullmatch(r"(.*)\[(\d+)\]", c)
        before = f"{m.group(1)}[{int(m.group(2)) - 1}]" if m else None
        if before in columns:
            columns.remove(c)
            columns.insert(columns.index(before) + 1, c)
    return [LOT_COLUMN] + columns, front, sources


def lot_selects(con, lots, columns, sources) -> list[tuple[str, str, str]]:
    """(label, table, SELECT of the sheet's columns as text) for each lot."""
    reference = set(sources[lots[0][1]])
    selects = []
    for label, table, _, _ in lots:
        mapped = sources[table]
        exprs = [f"'{label}'"] + [
            column_expr(con, table, *mapped[c], shared=c in reference) if c in mapped else "NULL"
            for c in columns[1:]]
        aliased = ", ".join(f"{e} AS {q(c)}" for e, c in zip(exprs, columns))
        selects.append((label, table, f"SELECT {aliased} FROM {q(table)}"))
    return selects


def build_table(con, name: str, selects) -> tuple[int, int]:
    """(Re)build the combined table: the lots' SELECTs stacked in lot order."""
    con.execute(f"CREATE OR REPLACE TABLE {q(name)} AS "
                + " UNION ALL ".join(sql for _, _, sql in selects))
    con.execute("CHECKPOINT")
    nrows = con.execute(f"SELECT count(*) FROM {q(name)}").fetchone()[0]
    return nrows, len(con.execute(f"DESCRIBE {q(name)}").fetchall())


def text_xml(v: str) -> str:
    """<t> element for one cell's text: edm._cell_xml's cleaning, minus the
    xml:space attribute where the value has no outer whitespace to keep."""
    v = edm._ILLEGAL_XML.sub("", v)
    if len(v) > edm.CELL_LIMIT:
        v = v[:edm.CELL_LIMIT - 3] + "..."
    keep = ' xml:space="preserve"' if v[:1].isspace() or v[-1:].isspace() else ""
    return f"<t{keep}>{escape(v)}</t>"


def shared_strings_xml(shared: dict, uses: int) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{uses}" uniqueCount="{len(shared)}">'
            + "".join(f"<si>{text_xml(v)}</si>" for v in shared) + "</sst>")


def write_stacked(path: str, con, columns, front, selects) -> tuple[int, dict, int]:
    """Write the stacked worksheet part -> (rows, shared strings, cells using them)."""
    counts = {label: con.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
              for label, table, _ in selects}
    total = sum(counts.values())
    if total + 1 > raw.EXCEL_MAX_ROWS:
        sys.exit(f"{total} rows do not fit one worksheet ({raw.EXCEL_MAX_ROWS} max)")
    header = "".join(
        f'<c{" s=\"1\"" if c in front else ""} t="inlineStr"><is><t>{escape(c)}</t></is></c>'
        for c in columns)
    shared, uses = {}, 0                 # text -> index in xl/sharedStrings.xml
    room = [SHARED_CAP] * len(columns)   # values each column may still add
    written = 0
    with open(path, "wb") as sheet:
        sheet.write(
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
        sheet.write(f'<dimension ref="A1:{edm._col_letter(len(columns))}{total + 1}"/><sheetData>'.encode())
        sheet.write(f"<row>{header}</row>".encode("utf-8"))
        for label, table, sql in selects:
            cur = con.execute(sql)
            n = 0
            while rows := cur.fetchmany(BATCH):
                out = []
                for row in rows:
                    out.append("<row>")
                    for i, v in enumerate(row):
                        if v is None:
                            out.append("<c/>")
                            continue
                        if isinstance(v, bool):
                            out.append(f'<c t="b"><v>{1 if v else 0}</v></c>')
                            continue
                        v = str(v)
                        k = shared.get(v)
                        if k is None and room[i]:
                            room[i] -= 1
                            k = shared[v] = len(shared)
                        if k is None:
                            out.append(f'<c t="inlineStr"><is>{text_xml(v)}</is></c>')
                        else:
                            uses += 1
                            out.append(f'<c t="s"><v>{k}</v></c>')
                    out.append("</row>")
                sheet.write("".join(out).encode("utf-8"))
                n += len(rows)
            if n != counts[label]:
                sys.exit(f"{table}: wrote {n} rows, expected {counts[label]}")
            written += n
            print(f"  {label}: {n} rows")
        sheet.write(b"</sheetData></worksheet>")
    return written, shared, uses


def free_path(out: Path, force: bool) -> Path:
    """`out`, or a timestamped name beside it while `out` is open in an office suite."""
    holder = wrapper.file_is_open(out)
    if not holder or force:
        return out
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"! {out.name} is open in {holder} - not overwriting it.")
    out = out.with_name(f"{out.stem}_{ts}{out.suffix}")
    print(f"  Writing {out.name} instead (pass --force to override).")
    return out


def write_workbook(out: Path, con, columns, front, selects, sheet: str, raw_sheets) -> None:
    """The workbook `out`: `selects` stacked on worksheet `sheet`, then one sheet
    per (raw table, sheet name) in raw_sheets, written beside it and renamed."""
    names = [sheet] + [name for _, name in raw_sheets]
    tmp = out.with_name(f".{out.stem}.{os.getpid()}.tmp")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            stacked = os.path.join(tmpdir, "sheet1.xml")
            print(f"Stacking {', '.join(table for _, table, _ in selects)} ...")
            nrows, shared, uses = write_stacked(stacked, con, columns, front, selects)
            size = os.path.getsize(stacked)
            print(f"Sheet {sheet!r}: {nrows} rows x {len(columns)} columns, {size / 1e9:.2f} GB of XML; "
                  f"{uses} cells share {len(shared)} strings")
            if size > zipfile.ZIP64_LIMIT:
                print("! over 2 GiB: this sheet is stored as a ZIP64 entry, which some "
                      "spreadsheet programs cannot open.")
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zout:
                zout.writestr("[Content_Types].xml", edm._content_types(len(names)).replace(
                    "</Types>", f'<Override PartName="/xl/sharedStrings.xml" ContentType="{SST_TYPE}"/></Types>'))
                zout.writestr("_rels/.rels", edm._ROOT_RELS)
                zout.writestr("xl/workbook.xml", edm._workbook(names))
                zout.writestr("xl/_rels/workbook.xml.rels", edm._workbook_rels(len(names)).replace(
                    "</Relationships>", f'<Relationship Id="rId{len(names) + 2}" Type="{SST_REL}" '
                                        'Target="sharedStrings.xml"/></Relationships>'))
                zout.writestr("xl/styles.xml", edm._STYLES)
                zout.writestr("xl/sharedStrings.xml", shared_strings_xml(shared, uses))
                zout.write(stacked, "xl/worksheets/sheet1.xml")
                for i, (table, name) in enumerate(raw_sheets, 2):
                    r, c = raw.write_sheet(zout, f"xl/worksheets/sheet{i}.xml", con, table)
                    print(f"Sheet {name!r}: {r} rows x {c} columns from {table}")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)
    print(f"Wrote {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=edm.DB_PATH)
    ap.add_argument("--dcat", action="store_true",
                    help=f"stack the DCAT lot tables: {DCAT['name']}.xlsx and table {DCAT['name']}")
    ap.add_argument("--out", help="workbook path (default: <table name>.xlsx in the repo root)")
    ap.add_argument("--no-table", action="store_true",
                    help="write the workbook only and leave the combined table as it is "
                         "(opens the database read-only)")
    ap.add_argument("--no-workbook", action="store_true",
                    help="rebuild the combined table only and leave the workbook as it is")
    ap.add_argument("--per-lot", metavar="DIR",
                    help="instead: one workbook per lot in DIR, the stacked sheet's columns "
                         "without 'lot' (read-only; no table, no raw sheets)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite even if the file looks open in an office suite")
    args = ap.parse_args()
    if args.no_table and args.no_workbook:
        sys.exit("--no-table and --no-workbook together leave nothing to do")

    kind = DCAT if args.dcat else DUBLIN
    name, lots = kind["name"], kind["lots"]
    read_only = args.no_table or bool(args.per_lot)
    out = None
    if not args.no_workbook and not args.per_lot:
        out = free_path(Path(args.out) if args.out else REPO / f"{name}.xlsx", args.force)
    try:
        con = duckdb.connect(args.db, read_only=read_only)
    except duckdb.IOException as e:
        sys.exit(f"Cannot open {args.db}: {e}\n"
                 f"Rebuilding {name} needs the write lock - close whatever holds the "
                 "database (DBeaver?), or pass --no-table for the workbook alone.")
    try:
        columns, front, sources = plan_columns(con, lots, kind["priority"])
        drop = {c.lower() for c in kind.get("drop", [])}
        columns = [c for c in columns if c.lower() not in drop]
        front = [c for c in front if c.lower() not in drop]
        selects = lot_selects(con, lots, columns, sources)
        for _, table, _, _ in lots:
            filled = sum(c in sources[table] for c in columns[1:])
            print(f"  {table}: {filled} of {len(columns) - 1} columns filled")
        if args.per_lot:
            folder = Path(args.per_lot)
            folder.mkdir(parents=True, exist_ok=True)
            for label, table, sql in selects:
                stem = name.replace("all_lots", "lot" + label.split()[-1])
                lot_out = free_path(folder / f"{stem}.xlsx", args.force)
                write_workbook(lot_out, con, columns[1:], front,
                               [(label, table, f"SELECT * EXCLUDE ({q(LOT_COLUMN)}) FROM ({sql})")],
                               stem, [])
            return
        if not args.no_table:
            print(f"Building table {name} ...")
            r, c = build_table(con, name, selects)
            print(f"Table {name}: {r} rows x {c} columns")
        if args.no_workbook:
            return
        write_workbook(out, con, columns, front, selects, SHEET,
                       [(table, sheet) for _, _, table, sheet in lots])
    finally:
        con.close()


if __name__ == "__main__":
    main()
