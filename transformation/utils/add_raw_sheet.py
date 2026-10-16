#!/usr/bin/env python3
"""
Add a lot's raw source table to its exported workbook as an extra sheet "raw".

  dublin_core_metadata.xlsx   <- raw_metadata
  dublin_core_remaining.xlsx  <- remaining-raw-datasets
  dublin_core_lot3.xlsx       <- lot3_raw

The workbook's existing parts are copied across unchanged -- Sheet1 is not
re-exported, so whatever the file holds stays as it is -- and the raw table is
appended as one more worksheet: a header row, every column in table order, rows
in table order. Running it on a workbook that already has the sheet replaces
that sheet.

Cells are text, like the rest of the export; nid in particular, so it matches
Sheet1's nid in a lookup. Booleans stay booleans. A DOUBLE column holding only
whole numbers is written without the ".0", and a TIMESTAMP column holding only
midnights as a date.

A plain re-export (export_dublin_metadata.py, export_dublin_core_remaining.py)
writes a one-sheet workbook again; re-run this afterwards to put the sheet back.

Like the export wrapper, it does not overwrite a workbook that is open in
WPS/LibreOffice/Excel: it writes a timestamped copy beside it and says so.

Usage:
  python3 add_raw_sheet.py                          # all three lots
  python3 add_raw_sheet.py dublin_core_lot3         # one lot
  python3 add_raw_sheet.py --workbook X.xlsx --table lot3_raw
"""

import argparse
import datetime as dt
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb

import export_dublin_core_remaining as wrapper
import export_dublin_metadata as edm

REPO = Path(edm.REPO)
LOTS = {
    "dublin_core_metadata": "raw_metadata",
    "dublin_core_remaining": "remaining-raw-datasets",
    "dublin_core_lot3": "lot3_raw",
}
SHEET = "raw"
EXCEL_MAX_ROWS = 1_048_576
WORKBOOK, RELS, TYPES = "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
WORKSHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
ZIP64_LIMIT = 1 << 31


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else None


def text_expr(con, table: str, name: str, typ: str) -> str:
    """SQL expression rendering one column as the text the sheet should show."""
    t, c = q(table), q(name)
    none = lambda cond: con.execute(
        f"SELECT count(*) FROM {t} WHERE {c} IS NOT NULL AND ({cond})").fetchone()[0] == 0
    if typ == "BOOLEAN":
        return c
    if typ in ("DOUBLE", "FLOAT") and none(
            f"isnan({c}) OR isinf({c}) OR {c} <> floor({c}) OR abs({c}) >= 9e15"):
        return f"CAST(CAST({c} AS BIGINT) AS VARCHAR)"
    if typ.startswith("TIMESTAMP") and none(f"CAST({c} AS VARCHAR) NOT LIKE '% 00:00:00'"):
        return f"CAST(CAST({c} AS DATE) AS VARCHAR)"
    return f"CAST({c} AS VARCHAR)"


def select_sql(con, table: str) -> tuple[str, list[str]]:
    """SELECT that renders every column as the text the sheet should show."""
    cols = [(name, typ) for name, typ, *_ in con.execute(f"DESCRIBE {q(table)}").fetchall()]
    exprs = [f"{text_expr(con, table, name, typ)} AS {q(name)}" for name, typ in cols]
    return f"SELECT {', '.join(exprs)} FROM {q(table)}", [name for name, _ in cols]


def write_sheet(zout, part: str, con, table: str) -> tuple[int, int]:
    nrows = con.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
    if nrows + 1 > EXCEL_MAX_ROWS:
        sys.exit(f"{table}: {nrows} rows do not fit one worksheet ({EXCEL_MAX_ROWS} max)")
    sql, names = select_sql(con, table)
    cell = edm._cell_xml
    written = 0
    with zout.open(part, "w") as sheet:
        sheet.write(
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
        sheet.write(f'<dimension ref="A1:{edm._col_letter(len(names))}{nrows + 1}"/><sheetData>'.encode())
        sheet.write(("<row>" + "".join(cell(n) for n in names) + "</row>").encode("utf-8"))
        cur = con.execute(sql)
        while rows := cur.fetchmany(20_000):
            sheet.write("".join(
                "<row>" + "".join(cell(v) for v in row) + "</row>" for row in rows).encode("utf-8"))
            written += len(rows)
        sheet.write(b"</sheetData></worksheet>")
    if written != nrows:
        sys.exit(f"{table}: wrote {written} rows, expected {nrows}")
    return nrows, len(names)


def plan_parts(zin, sheet_name: str) -> tuple[str, dict, bool]:
    """-> (worksheet part to write, {package part: new xml}, sheet already there)."""
    wb = zin.read(WORKBOOK).decode("utf-8")
    rels = zin.read(RELS).decode("utf-8")
    types = zin.read(TYPES).decode("utf-8")
    block = re.search(r"<sheets>(.*?)</sheets>", wb, re.S)
    if not block:
        sys.exit("workbook.xml has no <sheets> block")
    sheets = re.findall(r"<sheet\b[^>]*/>", block.group(1))
    rel_tags = re.findall(r"<Relationship\b[^>]*/>", rels)
    targets = {attr(r, "Id"): attr(r, "Target") for r in rel_tags}
    part_of = lambda target: target.lstrip("/") if target.startswith("/") else "xl/" + target

    for tag in sheets:
        if (attr(tag, "name") or "").lower() == sheet_name.lower():
            return part_of(targets[attr(tag, "r:id")]), {}, True

    used = set(zin.namelist())
    k = next(i for i in range(1, 10_000) if f"xl/worksheets/sheet{i}.xml" not in used)
    rid_n = max([int(m.group(1)) for r in targets if r and (m := re.fullmatch(r"rId(\d+)", r))] + [0]) + 1
    sheet_id = max([int(attr(s, "sheetId") or 0) for s in sheets] + [0]) + 1
    wb = wb.replace("</sheets>",
                    f'<sheet name="{escape(sheet_name)}" sheetId="{sheet_id}" r:id="rId{rid_n}"/></sheets>', 1)
    rels = rels.replace("</Relationships>",
                        f'<Relationship Id="rId{rid_n}" Type="{WORKSHEET_REL}" '
                        f'Target="worksheets/sheet{k}.xml"/></Relationships>', 1)
    types = types.replace("</Types>",
                          f'<Override PartName="/xl/worksheets/sheet{k}.xml" '
                          f'ContentType="{WORKSHEET_TYPE}"/></Types>', 1)
    return f"xl/worksheets/sheet{k}.xml", {WORKBOOK: wb, RELS: rels, TYPES: types}, False


def add_raw_sheet(workbook: Path, table: str, db: str, sheet_name: str, force: bool) -> Path:
    if not workbook.exists():
        sys.exit(f"{workbook} not found - export it first")
    out = workbook
    holder = wrapper.file_is_open(workbook)
    if holder and not force:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = workbook.with_name(f"{workbook.stem}_{ts}{workbook.suffix}")
        print(f"! {workbook.name} is open in {holder} - not overwriting it.")
        print(f"  Writing {out.name} instead (pass --force to override).")

    tmp = workbook.with_name(f".{workbook.stem}.raw-sheet-{os.getpid()}.tmp")
    con = duckdb.connect(db, read_only=True)
    try:
        with zipfile.ZipFile(workbook) as zin, \
                zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zout:
            part, edited, replacing = plan_parts(zin, sheet_name)
            for info in zin.infolist():
                if info.filename == part:
                    continue                      # the old raw sheet, rewritten below
                if info.filename in edited:
                    zout.writestr(info.filename, edited[info.filename])
                    continue
                with zin.open(info) as src, zout.open(
                        info.filename, "w", force_zip64=info.file_size >= ZIP64_LIMIT) as dst:
                    shutil.copyfileobj(src, dst, 1 << 22)
            nrows, ncols = write_sheet(zout, part, con, table)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    os.replace(tmp, out)
    verb = "replaced" if replacing else "added"
    print(f"{out.name}: sheet {sheet_name!r} {verb} from {table} - {nrows} rows x {ncols} columns "
          f"({out.stat().st_size / 1024 / 1024:.1f} MB)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lots", nargs="*", metavar="lot",
                    help=f"which workbook(s); default all of {', '.join(LOTS)}")
    ap.add_argument("--workbook", help="another workbook (needs --table)")
    ap.add_argument("--table", help="raw table for --workbook")
    ap.add_argument("--sheet", default=SHEET, help=f"sheet name (default {SHEET!r})")
    ap.add_argument("--db", default=edm.DB_PATH)
    ap.add_argument("--force", action="store_true",
                    help="overwrite even if the workbook looks open in an office suite")
    args = ap.parse_args()

    if bool(args.workbook) != bool(args.table):
        sys.exit("--workbook and --table go together")
    unknown = [lot for lot in args.lots if lot not in LOTS]
    if unknown:
        sys.exit(f"unknown lot(s) {unknown}; choose from {', '.join(LOTS)}")
    jobs = ([(Path(args.workbook), args.table)] if args.workbook else
            [(REPO / f"{lot}.xlsx", LOTS[lot]) for lot in (args.lots or LOTS)])
    for workbook, table in jobs:
        add_raw_sheet(workbook, table, args.db, args.sheet, args.force)


if __name__ == "__main__":
    main()
