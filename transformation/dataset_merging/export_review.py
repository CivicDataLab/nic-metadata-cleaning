"""
Dump the detection results to CSVs for human review.

Three views of the same table, written to reports/ next to this script:

  collections_curate.csv - one row per curate Collection: size, the axis that
      must be added to merge it, needs_review, how many distinct header
      signatures it spans, and three sample titles. This is the sheet to read
      first, and the one the curation round-trip edits.
  exact_groups.csv       - one row per exact merge group (identical headers,
      merge directly): size, catalog, and the shared header signature.
  rows.csv               - every row with its derived columns, for tracing an
      individual nid.

Read-only: opens DuckDB read_only=True and never writes to the database.

Usage:
  python export_review.py
  python export_review.py --table dublin_core_remaining --out-dir /tmp/review
"""

import argparse
import csv
import re
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
SAMPLES = 3


def _write(path: Path, header: list[str], rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        n = 0
        for row in rows:
            w.writerow(row)
            n += 1
    print(f"  {path.name:26s} {n:>7} rows")


def export(con, table: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing to {out_dir}")

    curate = con.execute(f"""
        SELECT "Collection",
               any_value("Publisher[ministry_department]")  AS ministry,
               COUNT(*)                                     AS n_rows,
               any_value(merge_add_columns)                 AS merge_add_columns,
               any_value(needs_review)                      AS needs_review,
               COUNT(DISTINCT "Conforms To")                AS n_header_sigs,
               COUNT(*) FILTER (WHERE "Conforms To" IS NULL) AS n_missing_header,
               list("Title")[1:{SAMPLES}]                   AS samples
        FROM "{table}"
        WHERE merge_method = 'curate'
        GROUP BY 1
        ORDER BY n_rows DESC
    """).fetchall()
    _write(
        out_dir / "collections_curate.csv",
        ["Collection", "ministry", "n_rows", "merge_add_columns", "needs_review",
         "n_header_sigs", "n_missing_header", "sample_titles"],
        ([c, m, n, a, r, s, mh, " | ".join(x or "" for x in samp)]
         for c, m, n, a, r, s, mh, samp in curate),
    )

    exact = con.execute(f"""
        SELECT exact_merge_group_id,
               any_value(exact_merge_group_name)            AS name,
               any_value("Publisher[ministry_department]")  AS ministry,
               any_value("Relation[Catalog Title]")         AS catalog,
               COUNT(*)                                     AS n_rows,
               any_value("Conforms To")                     AS header_signature,
               list("Title")[1:{SAMPLES}]                   AS samples
        FROM "{table}"
        WHERE exact_merge_group_id IS NOT NULL
        GROUP BY 1
        ORDER BY n_rows DESC
    """).fetchall()
    _write(
        out_dir / "exact_groups.csv",
        ["exact_merge_group_id", "exact_merge_group_name", "ministry", "catalog",
         "n_rows", "header_signature", "sample_titles"],
        ([g, nm, m, cat, n, (h or "")[:500], " | ".join(x or "" for x in samp)]
         for g, nm, m, cat, n, h, samp in exact),
    )

    rows = con.execute(f"""
        SELECT nid, "Title", "Publisher[ministry_department]",
               "Relation[Catalog Title]", merge_method, "Collection",
               exact_merge_group_id, exact_merge_group_name,
               merge_add_columns, needs_review,
               data_time_period_from, data_time_period_to,
               CASE WHEN "Conforms To" IS NULL THEN 0 ELSE 1 END AS has_header
        FROM "{table}"
        ORDER BY merge_method NULLS LAST, "Collection", nid
    """).fetchall()
    _write(
        out_dir / "rows.csv",
        ["nid", "Title", "ministry", "catalog", "merge_method", "Collection",
         "exact_merge_group_id", "exact_merge_group_name", "merge_add_columns",
         "needs_review", "period_from", "period_to", "has_header"],
        rows,
    )


def export_curation_xlsx(con, table: str, out_dir: Path) -> None:
    """
    The curation round-trip workbook: curate collections, one sheet per
    merge_add_columns value, as batch 1 did with curate_datasets.xlsx.

    The reviewer edits `curated_merge_add_columns` and `curator_note` — batch 1
    entered values like "group based on state" and "non-mergeable" by hand,
    which is also how the axes this pipeline cannot name (entity dimensions such
    as airline) get recorded.
    """
    import pandas as pd   # local: only this path needs pandas/openpyxl

    df = con.execute(f"""
        SELECT "Collection", any_value("Publisher[ministry_department]") AS ministry,
               COUNT(*) AS n_rows,
               any_value(merge_add_columns) AS merge_add_columns,
               any_value(needs_review) AS needs_review,
               COUNT(DISTINCT "Conforms To") AS n_header_sigs,
               list("Title")[1:3] AS samples
        FROM "{table}" WHERE merge_method = 'curate'
        GROUP BY 1 ORDER BY n_rows DESC
    """).fetchdf()
    df["samples"] = df["samples"].apply(lambda v: " | ".join(x or "" for x in v))
    df["curated_merge_add_columns"] = ""   # reviewer fills in
    df["curator_note"] = ""

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "curate_datasets.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for axis, chunk in df.groupby(df["merge_add_columns"].fillna("needs review")):
            # Excel sheet names: 31 chars max, and []:*?/\ are illegal.
            sheet = re.sub(r"[\[\]:*?/\\]", "-", str(axis))[:31] or "none"
            chunk.drop(columns=["merge_add_columns"]).to_excel(
                xw, sheet_name=sheet, index=False)
    print(f"  {path.name:26s} {len(df):>7} collections "
          f"across {df['merge_add_columns'].fillna('needs review').nunique()} sheets")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export detection results for review.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--out-dir", default=str(HERE / "reports"))
    ap.add_argument("--xlsx", action="store_true",
                    help="Also write the curation round-trip workbook.")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    try:
        export(con, args.table, Path(args.out_dir))
        if args.xlsx:
            export_curation_xlsx(con, args.table, Path(args.out_dir))
    finally:
        con.close()


if __name__ == "__main__":
    main()
