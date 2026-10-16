"""
Export every curate-flagged dataset with its per-dataset and per-collection row count.

Writes two files side by side:
  curate_collection_row_counts.csv   flat — the collection total repeats on every row
  curate_collection_row_counts.xlsx  same data, but the collection total is written
                                     once per collection and vertically merged across
                                     that collection's rows

The collection total comes from a window function on the same ordered result set that
gets written, so the group boundaries used for merging are the ones the totals were
computed over. Collections with a single member are left unmerged — a one-cell merge
range makes Excel flag the file as corrupt.

Usage:
  python curate_collection_row_count.py
  python curate_collection_row_count.py --merge-method direct
  python curate_collection_row_count.py --out-dir /tmp --basename sample --limit 500
"""

import argparse
import csv
import os
import time

import duckdb
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
TABLE = "dublin_core_metadata"
DEFAULT_OUT_DIR = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation"
DEFAULT_BASENAME = "curate_collection_row_counts"
FETCH_SIZE = 20_000

# Output column order. The merged column must be last so the merge ranges sit in one
# trailing column, matching the reference layout.
HEADERS = [
    "nid",
    "title",
    "new_title",
    "merge_method",
    "Collection",
    "Relation[Catalog Title]",
    "new_catalog_title",
    "merge_add_columns",
    "Year",
    "Month",
    "Financial_Year",
    "Quarter",
    "row_count",
    "collection_total_row_count",
]

COLLECTION_IDX = HEADERS.index("Collection")
TOTAL_IDX = HEADERS.index("collection_total_row_count")
TOTAL_COL = TOTAL_IDX + 1  # 1-based for openpyxl

# Temporal columns are sparse (the DB stores the '<NA>' literal for most of them).
# Write a visible 'NA' rather than an empty cell so a blank always means "not exported"
# instead of "unknown". Real values stay numeric where the column is numeric.
NA_FILL = "NA"
NA_FILL_IDX = [HEADERS.index(c) for c in ("Year", "Month", "Financial_Year", "Quarter")]

COLUMN_WIDTHS = {
    "nid": 10,
    "title": 60,
    "new_title": 50,
    "merge_method": 14,
    "Collection": 60,
    "Relation[Catalog Title]": 50,
    "new_catalog_title": 40,
    "merge_add_columns": 22,
    "Year": 8,
    "Month": 10,
    "Financial_Year": 15,
    "Quarter": 9,
    "row_count": 12,
    "collection_total_row_count": 26,
}


def clean(expr):
    """Blank out the '<NA>' literal left behind by the xlsx round-trip."""
    return f"nullif(nullif(trim({expr}), ''), '<NA>')"


def build_query(merge_method, limit=None):
    sql = f"""
        SELECT
            TRY_CAST(nid AS BIGINT)                        AS nid,
            {clean('"Title"')}                             AS title,
            {clean('new_title')}                           AS new_title,
            merge_method,
            "Collection",
            {clean('"Relation[Catalog Title]"')}           AS "Relation[Catalog Title]",
            {clean('new_catalog_title')}                   AS new_catalog_title,
            {clean('merge_add_columns')}                   AS merge_add_columns,
            TRY_CAST("Year" AS BIGINT)                     AS "Year",
            {clean('"Month"')}                             AS "Month",
            {clean('Financial_Year')}                      AS Financial_Year,
            TRY_CAST("Quarter" AS BIGINT)                  AS "Quarter",
            TRY_CAST(row_count AS BIGINT)                  AS row_count,
            SUM(TRY_CAST(row_count AS BIGINT))
                OVER (PARTITION BY "Collection")           AS collection_total_row_count
        FROM "{TABLE}"
        WHERE merge_method = ?
        ORDER BY "Collection", TRY_CAST(nid AS BIGINT)
    """
    if limit:
        sql += f"\n        LIMIT {int(limit)}"
    return sql


def make_header_row(ws):
    row = []
    for name in HEADERS:
        cell = WriteOnlyCell(ws, value=name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        row.append(cell)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--merge-method", default="curate", help="merge_method to export (default: curate)")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Directory for the output files")
    parser.add_argument("--basename", default=DEFAULT_BASENAME, help="Output filename stem (no extension)")
    parser.add_argument("--limit", type=int, default=None, help="Only export the first N rows (for testing)")
    parser.add_argument("--db", default=DB_PATH, help="Path to metadata.db")
    args = parser.parse_args()

    start = time.time()
    csv_path = os.path.join(args.out_dir, f"{args.basename}.csv")
    xlsx_path = os.path.join(args.out_dir, f"{args.basename}.xlsx")

    conn = duckdb.connect(args.db, read_only=True)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(f"{args.merge_method} datasets")
    ws.freeze_panes = "A2"
    for idx, name in enumerate(HEADERS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = COLUMN_WIDTHS[name]

    merge_align = Alignment(vertical="center", horizontal="center")

    try:
        conn.execute(build_query(args.merge_method, args.limit), [args.merge_method])

        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(csv_file)
        writer.writerow(HEADERS)
        ws.append(make_header_row(ws))

        n_rows = 0
        n_collections = 0
        n_merged = 0
        n_singleton = 0
        excel_row = 1          # header occupies row 1
        current_collection = None
        group_start_row = None

        def close_group(end_row):
            """Merge the total cell across the group that just ended."""
            nonlocal n_merged, n_singleton
            if group_start_row is None:
                return
            if end_row > group_start_row:
                ws.merged_cells.ranges.add(
                    CellRange(
                        min_col=TOTAL_COL, min_row=group_start_row,
                        max_col=TOTAL_COL, max_row=end_row,
                    )
                )
                n_merged += 1
            else:
                # Single-member collection: a 1x1 merge range corrupts the workbook.
                n_singleton += 1

        while True:
            batch = conn.fetchmany(FETCH_SIZE)
            if not batch:
                break
            for row in batch:
                row = list(row)
                for idx in NA_FILL_IDX:
                    if row[idx] is None:
                        row[idx] = NA_FILL
                writer.writerow(row)

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
                    # Blank on continuation rows — the merge shows the anchor's value.
                    row[TOTAL_IDX] = None

                ws.append(row)
                n_rows += 1

        close_group(excel_row)

        csv_file.close()
        wb.save(xlsx_path)

    finally:
        conn.close()

    print(f"merge_method       : {args.merge_method}")
    print(f"Datasets exported  : {n_rows:,}")
    print(f"Collections        : {n_collections:,}")
    print(f"  merged ranges    : {n_merged:,}")
    print(f"  single-member    : {n_singleton:,} (left unmerged)")
    print(f"\nCSV   : {csv_path}")
    print(f"XLSX  : {xlsx_path}")
    print(f"Elapsed            : {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
