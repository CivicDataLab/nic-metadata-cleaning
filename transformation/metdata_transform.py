import duckdb
import pandas as pd

from datetime import datetime


FIELD_MAPPING: dict[str, str | None] = {
    #Exact Matches
    "Title":                        "title",
    "Subject[sector_resource]":     "sector_resource",
    "Date Created":                 "created",
    "Date Issued":                  "published",
    "Date Modified":                "changed",
    "Type":                         "resource_category",
    "Extent":                       "file_size",
    "Format":                       "file_format",
    "Relation":                     "Reference Url",
    "Identifier[UUID]":             "uuid",
    # Identifier[landing_page] is a *composite*: domain + node_alias
    # handled separately in transform_metadata()
    "Jurisdiction":                 "govt_type",
    "Access Rights":                "Access Type",
    "Accrual Periodicity":          "frequency",
    "Coverage":                     "granularity",
    "Subject[sector]":              "sector",
    "Relation[download_url]":       "datafile",
    "Relation[endpointURL]":        "datafile_url",
    "Relation[Catalog Title]":      "catalog_title",


    #Ambiguous 
    "Rights":                       None,   
    "High Value Dataset Category":  "field_high_value_dataset",
    "Accrual Method":               "field_resource_type",
    "Creator":                      "cdos_state_ministry",
    "Publisher[state_department]":   "state_department",
    "Publisher[ministry_department]":"ministry_department",
    "Note":                         "note",
    #Gap fields 
    "Description":                  None,
    "License":                      None,
    "Language":                     None,
    "Abstract":                     None,
    "Alternative Title":            None,
    "Source":                       None,   # "Sourced Webservices/API" — not in OGD export
    "Spatial Coverage":             None,   # "field_asset_jurisdiction" — catalog-level, not in resource export
    "Temporal Coverage":            None,   # "Duration of Date" — not in OGD export
    "Rights Statement":             None,   # "Released Under" — not in OGD export
    "Subject[keyword]":             None,   # "keyword" — not in OGD export
    "Conforms To":                  None,   # "Fields" — not in OGD export
    "Depiction":                    None,   # "Thumbnail" — not in OGD export
    "Relation[Access URL]":         None,
    "Relation[Has Part]":           None,
    "Relation[Is Referenced By]":   None,
    "Relation[Is Replaced By]":     None,
    "Relation[Replaces]":           None,
    "Relation[Is Version Of]":      None,
    "Relation[Has Version]":        None,
    "Description[endpointDescription]": None,
    "Collection":                   None,
    "Relation[Is Part Of]":         None,
    "batch": "batch",
}

#Date columns that need format conversion (ISO 8601)
DATE_COLUMNS_OGD = ["created", "published_date", "changed"]


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:

    # Build the reverse lookup: ogd_name → dublin_core_name
    ogd_to_dc: dict[str, str] = {
        ogd_col: dc_name
        for dc_name, ogd_col in FIELD_MAPPING.items()
        if ogd_col is not None
    }

    rename_map = {
        col: ogd_to_dc[col]
        for col in df.columns
        if col in ogd_to_dc
    }

    return df.rename(columns=rename_map)


def convert_date_columns(df: pd.DataFrame,
                         date_columns: list[str] | None = None) -> pd.DataFrame:

    if date_columns is None:
        date_columns = DATE_COLUMNS_OGD

    df = df.copy()
    for col in date_columns:
        if col not in df.columns:
            continue
        # pd.to_datetime with dayfirst=False handles M/D/YYYY
        df[col] = (
            pd.to_datetime(df[col], format="mixed", dayfirst=False, errors="coerce")
            .dt.strftime("%Y-%m-%d")
        )
    return df


def transform_metadata(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Step 1 — Convert date columns (while OGD names still exist)
    df = convert_date_columns(df)
    print(f"[1/4] Converted date columns to ISO 8601: {DATE_COLUMNS_OGD}")

    # Step 2 — Build composite Identifier[landing_page]
    if "domain" in df.columns and "node_alias" in df.columns:
        df["Identifier[landing_page]"] = (
            "https://" + df["domain"].fillna("") + df["node_alias"].fillna("")
        )
        df = df.drop(columns=["domain", "node_alias"])
        print("[2/4] Built composite Identifier[landing_page] from domain + node_alias")
    else:
        print("[2/4] Skipped composite Identifier[landing_page] — columns not found")

    # Step 3 — Rename OGD columns → Dublin Core names
    df = rename_columns(df)
    print(f"[3/4] Renamed {sum(1 for c in df.columns if c in FIELD_MAPPING)} columns to Dublin Core names")

    # Step 4 — Add gap Dublin Core columns as empty
    gap_fields = [
        dc_name for dc_name, ogd_col in FIELD_MAPPING.items()
        if ogd_col is None and dc_name not in df.columns
    ]
    for field in gap_fields:
        df[field] = pd.array([None] * len(df), dtype=pd.StringDtype())

    #Populate "Rights" column with NDSAP policy
    if "Rights" in df.columns:
        df["Rights"] = "National Data Sharing and Accessibility Policy (NDSAP) (2012)"

    print(f"[4/4] Added {len(gap_fields)} gap Dublin Core columns: {gap_fields}")

    return df


def load_to_duckdb(df: pd.DataFrame,
                   db_path: str = "metadata.duckdb",
                   table_name: str = "dublin_core_metadata") -> None:
    """
    Write the transformed dataframe into a DuckDB table.
    Replaces the table if it already exists.
    """
    con = duckdb.connect(db_path)
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")
    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    col_count = con.execute(
        f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'"
    ).fetchone()[0]
    print(f"\n✓ Loaded {row_count} rows × {col_count} columns into {db_path}::{table_name}")
    con.close()


if __name__ == "__main__":
    DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
    SOURCE_TABLE = "raw_metadata"
    TARGET_TABLE = "dublin_core_metadata"

    # --- Read source table from existing DuckDB ---
    con = duckdb.connect(DB_PATH)
    source_count = con.execute(f"SELECT COUNT(*) FROM {SOURCE_TABLE}").fetchone()[0]
    print(f"Source: {source_count} rows in {DB_PATH}::{SOURCE_TABLE}\n")
    df_ogd = con.execute(f"SELECT * FROM {SOURCE_TABLE}").fetchdf()
    con.close()

    print("=" * 60)
    print("FIELD MAPPING TABLE (Dublin Core to OGD)")
    print("=" * 60)
    print(f"{'Dublin Core Field':<40} {'OGD Field':<30} {'Action'}")
    print("-" * 90)
    for dc_name, ogd_col in FIELD_MAPPING.items():
        action = "RENAME" if ogd_col else "ADD (empty)"
        ogd_display = ogd_col if ogd_col else "—"
        print(f"{dc_name:<40} {ogd_display:<30} {action}")
    print("-" * 90)
    print("=" * 60)


    print("\nTransforming…")
    df_dc = transform_metadata(df_ogd)


    load_to_duckdb(df_dc, db_path=DB_PATH, table_name=TARGET_TABLE)

    # --- Quick verification ---
    con = duckdb.connect(DB_PATH)
    print("\n── Sample output (first 2 rows, key columns) ──")
    preview = con.execute(f"""
        SELECT
            "Title",
            "Identifier[UUID]",
            "Date Created",
            "Date Issued",
            "Date Modified",
            "Type",
            "Jurisdiction",
            "Creator",
            "Identifier[landing_page]"
        FROM {TARGET_TABLE}
        LIMIT 2
    """).fetchdf()
    print(preview.to_string(index=False))

    print(f"\nAll columns in {TARGET_TABLE}")
    cols = con.execute(f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = '{TARGET_TABLE}'
        ORDER BY ordinal_position
    """).fetchdf()
    print(cols.to_string(index=False))
    con.close()