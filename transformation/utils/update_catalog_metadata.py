"""
Apply human review edits from dublin_core_metadata_cleaned.xlsx into the
dublin_core_metadata table.

Two independent updates from two sheets of the same workbook:

  1. merge_method   <- 'Direct' sheet, matched by nid
       sets merge_method (e.g. 'direct') for the reviewed nids.

  2. new_catalog_title <- 'Catalogs' sheet, matched by catalog title
       Catalogs maps  title -> merged_catalog  (the consolidated catalog name).
       Every dataset whose Relation[Catalog Title] equals a sheet 'title' gets
       new_catalog_title = merged_catalog. Match is on trimmed strings.

'new_catalog_title' is added to the table as a VARCHAR column if missing; rows
whose catalog title has no entry in the Catalogs sheet stay NULL.

Idempotent and re-runnable. Backs up the DB to metadata.db.pre_catalog_*.bak
before writing (repo convention).

Usage:
  python update_catalog_metadata.py --dry-run    # preview counts, no write
  python update_catalog_metadata.py              # apply
"""

import argparse
import shutil
import time
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
XLSX_PATH = str(HERE.parent.parent / "dublin_core_metadata_cleaned.xlsx")
TABLE = "dublin_core_metadata"
NEW_COL = "new_catalog_title"


def load_direct() -> pd.DataFrame:
    """nid -> merge_method, from the 'Direct' sheet."""
    df = pd.read_excel(XLSX_PATH, sheet_name="Direct")
    df.columns = [str(c).strip() for c in df.columns]
    df = df[["nid", "merge_method"]].dropna(subset=["nid"]).copy()
    df["nid"] = df["nid"].astype("int64")
    df["merge_method"] = df["merge_method"].astype("object").where(
        df["merge_method"].notna(), None
    )
    return df.drop_duplicates(subset="nid", keep="last")


def load_catalogs() -> pd.DataFrame:
    """catalog title -> merged (new) catalog name, from the 'Catalogs' sheet."""
    df = pd.read_excel(XLSX_PATH, sheet_name="Catalogs")
    df.columns = [str(c).strip() for c in df.columns]
    if not {"title", "merged_catalog"}.issubset(df.columns):
        raise SystemExit(f"'Catalogs' sheet missing columns. Found: {list(df.columns)}")
    df = df[["title", "merged_catalog"]].dropna(subset=["title"]).copy()
    df["title"] = df["title"].astype(str).str.strip()
    df["merged_catalog"] = df["merged_catalog"].astype(str).str.strip()
    # 6 duplicate titles in the sheet all map to the same merged_catalog; keep last.
    return df.drop_duplicates(subset="title", keep="last")


def main(dry_run: bool) -> None:
    direct = load_direct()
    catalogs = load_catalogs()
    print(f"Direct sheet:   {len(direct)} nids, merge_method="
          f"{direct['merge_method'].value_counts(dropna=False).to_dict()}")
    print(f"Catalogs sheet: {len(catalogs)} unique catalog titles -> merged names")

    con = duckdb.connect(DB_PATH, read_only=dry_run)
    con.register("direct_ds", direct)
    con.register("catalogs_ds", catalogs)

    mm_match = con.execute(
        f"SELECT COUNT(*) FROM {TABLE} d JOIN direct_ds s USING (nid)"
    ).fetchone()[0]
    cat_match = con.execute(
        f'SELECT COUNT(*) FROM {TABLE} d JOIN catalogs_ds c '
        f'ON trim(d."Relation[Catalog Title]") = c.title'
    ).fetchone()[0]
    print(f"\nmatches: merge_method={mm_match}/{len(direct)} rows; "
          f"new_catalog_title={cat_match} rows")

    if dry_run:
        print("\n[dry-run] No changes written.")
        con.close()
        return

    con.close()
    dst = f"{DB_PATH}.pre_catalog_{time.strftime('%Y%m%d_%H%M%S')}.bak"
    shutil.copy2(DB_PATH, dst)
    print(f"Backed up DB -> {dst}")

    con = duckdb.connect(DB_PATH)
    try:
        existing = {
            r[0] for r in con.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{TABLE}'"
            ).fetchall()
        }
        if NEW_COL not in existing:
            con.execute(f'ALTER TABLE {TABLE} ADD COLUMN "{NEW_COL}" VARCHAR')
            print(f"Added column: {NEW_COL}")

        con.register("direct_ds", direct)
        con.register("catalogs_ds", catalogs)

        # 1. merge_method by nid
        con.execute(
            f"UPDATE {TABLE} AS d SET merge_method = s.merge_method "
            f"FROM direct_ds s WHERE d.nid = s.nid"
        )
        # 2. new_catalog_title by catalog title
        con.execute(
            f'UPDATE {TABLE} AS d SET "{NEW_COL}" = c.merged_catalog '
            f'FROM catalogs_ds c WHERE trim(d."Relation[Catalog Title]") = c.title'
        )

        filled = con.execute(
            f'SELECT COUNT(*) FROM {TABLE} WHERE "{NEW_COL}" IS NOT NULL'
        ).fetchone()[0]
        mm = con.execute(
            f"SELECT COUNT(*) FROM {TABLE} d JOIN direct_ds s USING (nid) "
            f"WHERE d.merge_method = s.merge_method"
        ).fetchone()[0]
        print(f"Updated merge_method for {mm} matched rows.")
        print(f"{NEW_COL} now populated on {filled} rows.")
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update merge_method (Direct sheet) and new_catalog_title (Catalogs sheet)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    main(parser.parse_args().dry_run)
