"""
Rebuild curate_collection_row_counts.xlsx with a `facility` column added.

The original workbook is produced by curate_collection_row_count.py straight from
metadata.db. That DB is usually locked by another process, and `facility` isn't a
DB column yet, so this script rebuilds the workbook from the CSV the same script
wrote alongside it — identical rows in identical order — and classifies `facility`
in-process via extract_facility_topic.classify(), so the workbook and
facility_topic_update.csv can never disagree.

Layout is reproduced exactly: column widths, frozen header, the 'NA' fill for the
sparse temporal columns, and the vertical merge of collection_total_row_count
across each collection block. `facility` is inserted after merge_add_columns —
it groups with the other dimension columns (Year/Month/...) and, critically,
keeps collection_total_row_count as the trailing column, which is what lets the
merge ranges live in a single column.

Rows that aren't "Performance of Public Facilities" datasets get an empty
facility cell; only those titles carry a measure to extract.

Usage:
    python add_facility_to_curate_xlsx.py                 # writes ...facility.xlsx
    python add_facility_to_curate_xlsx.py --in-place      # overwrite the original
"""

import argparse
import csv
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract_facility_topic import classify  # noqa: E402

TRANSFORM_DIR = HERE.parent
SRC_CSV = TRANSFORM_DIR / "curate_collection_row_counts.csv"
SRC_XLSX = TRANSFORM_DIR / "curate_collection_row_counts.xlsx"
SHEET_NAME = "curate datasets"

NEW_COL = "facility"
INSERT_AFTER = "merge_add_columns"

# Mirrors curate_collection_row_count.py, with NEW_COL spliced in.
BASE_HEADERS = [
    "nid", "title", "new_title", "merge_method", "Collection",
    "Relation[Catalog Title]", "new_catalog_title", "merge_add_columns",
    "Year", "Month", "Financial_Year", "Quarter",
    "row_count", "collection_total_row_count",
]
HEADERS = BASE_HEADERS[: BASE_HEADERS.index(INSERT_AFTER) + 1] + [NEW_COL] \
    + BASE_HEADERS[BASE_HEADERS.index(INSERT_AFTER) + 1:]

COLUMN_WIDTHS = {
    "nid": 10, "title": 60, "new_title": 50, "merge_method": 14,
    "Collection": 60, "Relation[Catalog Title]": 50, "new_catalog_title": 40,
    "merge_add_columns": 22, NEW_COL: 34,
    "Year": 8, "Month": 10, "Financial_Year": 15, "Quarter": 9,
    "row_count": 12, "collection_total_row_count": 26,
}

COLLECTION_IDX = HEADERS.index("Collection")
TOTAL_IDX = HEADERS.index("collection_total_row_count")
TOTAL_COL = TOTAL_IDX + 1
TITLE_IDX = HEADERS.index("title")
FACILITY_IDX = HEADERS.index(NEW_COL)

NA_FILL = "NA"
NA_FILL_IDX = [HEADERS.index(c) for c in ("Year", "Month", "Financial_Year", "Quarter")]
# Written as numbers in the original workbook, so cast back from CSV text.
INT_COLS = {"nid", "Year", "Quarter", "row_count", "collection_total_row_count"}
INT_IDX = [HEADERS.index(c) for c in INT_COLS]


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def make_header_row(ws):
    row = []
    for name in HEADERS:
        cell = WriteOnlyCell(ws, value=name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        row.append(cell)
    return row


def read_source_rows():
    """CSV rows in file order (already ordered by Collection, nid)."""
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")
    cols = ", ".join(f'"{c}"' for c in BASE_HEADERS)
    rows = con.execute(
        f"SELECT {cols} FROM read_csv_auto(?, header=true, all_varchar=true)",
        [str(SRC_CSV)],
    ).fetchall()
    con.close()
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--in-place", action="store_true",
                    help="overwrite the original xlsx (a .bak is kept)")
    ap.add_argument("--out", default=None, help="explicit output path")
    args = ap.parse_args()

    if args.out:
        out_path = Path(args.out)
    elif args.in_place:
        out_path = SRC_XLSX
    else:
        out_path = SRC_XLSX.with_name(SRC_XLSX.stem + "_facility.xlsx")

    start = time.time()
    src = read_source_rows()
    print(f"source rows: {len(src):,}")

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(SHEET_NAME)
    ws.freeze_panes = "A2"
    for idx, name in enumerate(HEADERS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = COLUMN_WIDTHS[name]
    ws.append(make_header_row(ws))

    merge_align = Alignment(vertical="center", horizontal="center")

    labels = Counter()
    n_rows = n_collections = n_merged = n_singleton = 0
    excel_row = 1
    current_collection = None
    group_start_row = None

    def close_group(end_row):
        nonlocal n_merged, n_singleton
        if group_start_row is None:
            return
        if end_row > group_start_row:
            ws.merged_cells.ranges.add(CellRange(
                min_col=TOTAL_COL, min_row=group_start_row,
                max_col=TOTAL_COL, max_row=end_row,
            ))
            n_merged += 1
        else:
            # A 1x1 merge range corrupts the workbook.
            n_singleton += 1

    ins = BASE_HEADERS.index(INSERT_AFTER) + 1
    for base in src:
        title = base[BASE_HEADERS.index("title")]
        facility = None
        if title and "performance of public facilities" in title.lower():
            facility, _raw = classify(title)
            if facility:
                labels[facility] += 1

        row = list(base[:ins]) + [facility] + list(base[ins:])
        for idx in INT_IDX:
            row[idx] = as_int(row[idx])
        for idx in NA_FILL_IDX:
            if row[idx] is None or row[idx] == "":
                row[idx] = NA_FILL

        excel_row += 1
        collection = row[COLLECTION_IDX]
        if collection != current_collection:
            close_group(excel_row - 1)
            current_collection = collection
            group_start_row = excel_row
            n_collections += 1
            total_cell = WriteOnlyCell(ws, value=row[TOTAL_IDX])
            total_cell.alignment = merge_align
            row[TOTAL_IDX] = total_cell
        else:
            row[TOTAL_IDX] = None

        ws.append(row)
        n_rows += 1

    close_group(excel_row)

    if args.in_place and SRC_XLSX.exists():
        bak = SRC_XLSX.with_suffix(f".pre_facility_{time.strftime('%Y%m%d_%H%M%S')}.bak.xlsx")
        shutil.copy2(SRC_XLSX, bak)
        print(f"backup: {bak.name}")

    wb.save(out_path)

    print(f"rows written     : {n_rows:,}")
    print(f"collections      : {n_collections:,}  "
          f"(merged {n_merged:,}, single-member {n_singleton:,})")
    print(f"facility filled  : {sum(labels.values()):,}")
    for label, n in labels.most_common():
        print(f"    {n:7,d}  {label}")
    print(f"\nXLSX : {out_path}")
    print(f"took {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
