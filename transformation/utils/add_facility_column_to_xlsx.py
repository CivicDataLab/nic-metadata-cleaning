"""
Append a `facility` column to curate_collection_row_counts.xlsx in place.

Why not regenerate the workbook
    The file on disk is NOT what curate_collection_row_count.py emits today: it
    has been opened and edited in WPS Office. Its headers were renamed by hand
    ("Old Dataset Title", "New Catalog Title", ...) and the merge_method and
    Collection columns were deleted, leaving 12 columns. Rebuilding it from the
    CSV would silently undo all of that, so instead we surgically add one column.

How
    The sheet XML is rewritten by streaming: for every <row>, a single new cell
    is appended at the far right (column M) carrying the facility label as an
    inline string. Nothing existing is touched — no cell reference shifts, and
    the 5,124 vertical merge ranges on column L are left exactly where they are.
    Inline strings (t="inlineStr") are used so sharedStrings.xml needs no edit.
    Every other zip entry is copied through byte-for-byte.

    The label for each row is looked up by the nid in column A, using the same
    classifier that produced facility_topic_update.csv.

Usage:
    python add_facility_column_to_xlsx.py --dry-run
    python add_facility_column_to_xlsx.py            # backs up, then rewrites
"""

import argparse
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract_facility_topic import classify  # noqa: E402

TRANSFORM_DIR = HERE.parent
XLSX = TRANSFORM_DIR / "curate_collection_row_counts.xlsx"
SRC_CSV = TRANSFORM_DIR / "curate_collection_row_counts.csv"
SHEET = "xl/worksheets/sheet1.xml"

NEW_HEADER = "facility"
NEW_LETTER = "M"          # first free column after collection_total_row_count (L)
HEADER_STYLE = 's="1"'    # the bold style the other header cells use

ROW_RE = re.compile(rb'<row [^>]*r="(\d+)"[^>]*>.*?</row>', re.S)
NID_RE = re.compile(rb'<c r="A\d+"[^>]*>\s*<v>([^<]+)</v>')


def build_nid_map():
    """nid (as text) -> facility label, for the Performance-of-Public-Facilities rows."""
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")
    rows = con.execute(
        """SELECT nid, title FROM read_csv_auto(?, header=true, all_varchar=true)
           WHERE title ILIKE '%Performance of Public Facilities%'""",
        [str(SRC_CSV)],
    ).fetchall()
    con.close()
    out = {}
    for nid, title in rows:
        label, _raw = classify(title)
        if label:
            out[str(nid).strip()] = label
    return out


def cell_xml(row_num, value):
    return (
        f'<c r="{NEW_LETTER}{row_num}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    ).encode("utf-8")


def header_cell_xml():
    return (
        f'<c r="{NEW_LETTER}1" {HEADER_STYLE} t="inlineStr">'
        f"<is><t>{NEW_HEADER}</t></is></c>"
    ).encode("utf-8")


def transform_sheet(data, nid_map, stats):
    def fix_row(m):
        row_xml = m.group(0)
        row_num = int(m.group(1))
        stats["rows"] += 1
        if row_num == 1:
            stats["header"] = True
            new_cell = header_cell_xml()
        else:
            nid_m = NID_RE.search(row_xml)
            if not nid_m:
                stats["no_nid"] += 1
                return row_xml
            nid = nid_m.group(1).decode().strip()
            label = nid_map.get(nid)
            if not label:
                return row_xml           # leave the cell absent = blank
            stats["filled"] += 1
            new_cell = cell_xml(row_num, label)
        # widen the spans hint if present, then splice the cell before </row>
        row_xml = re.sub(rb'spans="1:12"', b'spans="1:13"', row_xml, count=1)
        return row_xml[: -len(b"</row>")] + new_cell + b"</row>"

    data = ROW_RE.sub(fix_row, data)
    data = data.replace(b'<dimension ref="A1:L172330"/>',
                        b'<dimension ref="A1:M172330"/>')
    # add a width for the new column, mirroring the other <col> entries
    data = data.replace(
        b'<col min="12" max="12" width="26" customWidth="1"/>',
        b'<col min="12" max="12" width="26" customWidth="1"/>'
        b'<col min="13" max="13" width="34" customWidth="1"/>',
    )
    return data


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--xlsx", default=str(XLSX))
    args = ap.parse_args()

    path = Path(args.xlsx)
    start = time.time()

    nid_map = build_nid_map()
    print(f"facility labels to place: {len(nid_map):,}")
    if args.dry_run:
        from collections import Counter
        for label, n in Counter(nid_map.values()).most_common():
            print(f"    {n:7,d}  {label}")
        print("\ndry run — nothing written")
        return

    zin = zipfile.ZipFile(path)
    names = zin.namelist()
    if SHEET not in names:
        raise SystemExit(f"{SHEET} not found in workbook")
    sheet_data = zin.read(SHEET)

    stats = {"rows": 0, "filled": 0, "no_nid": 0, "header": False}
    new_sheet = transform_sheet(sheet_data, nid_map, stats)
    if not stats["header"]:
        raise SystemExit("header row not found — aborting without writing")
    if stats["filled"] != len(nid_map):
        print(f"WARNING: placed {stats['filled']:,} of {len(nid_map):,} labels")

    bak = path.with_suffix(f".pre_facility_{time.strftime('%Y%m%d_%H%M%S')}.bak.xlsx")
    shutil.copy2(path, bak)
    print(f"backup: {bak.name}")

    tmp = path.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            payload = new_sheet if item.filename == SHEET else zin.read(item.filename)
            zout.writestr(item, payload)
    zin.close()
    tmp.replace(path)

    print(f"rows scanned : {stats['rows']:,}")
    print(f"facility set : {stats['filled']:,}")
    print(f"rows w/o nid : {stats['no_nid']:,}")
    print(f"\nXLSX : {path}")
    print(f"took {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
