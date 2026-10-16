import argparse
import duckdb
import pandas as pd

from datetime import datetime
from pathlib import Path


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
# NOTE: "published_date" matches no column in any known source — the real column
# is "published". Kept only because raw_metadata stores dates as TIMESTAMP_NS and
# so needs no conversion; new sources should declare formats in SOURCE_PROFILES.
DATE_COLUMNS_OGD = ["created", "published_date", "changed"]

# Per-source quirks. `raw_metadata` keeps the original behaviour untouched;
# `remaining-raw-datasets` arrives from a different export with its own column
# spellings, day-first dates, and already-populated spatial/temporal fields.
SOURCE_PROFILES: dict[str, dict] = {
    "raw_metadata": {
        "aliases": {},
        "date_formats": {},
        "spatial_temporal": False,
    },
    "remaining-raw-datasets": {
        # Normalised to the OGD spellings FIELD_MAPPING expects, before renaming.
        "aliases": {
            "Reference_url":                  "Reference Url",
            "Access_Type":                    "Access Type",
            "field_high_value_dataset_value": "field_high_value_dataset",
        },
        # Uniform single formats, verified against the table (no mixed parsing).
        # created/changed are DD-MM-YYYY: dayfirst is load-bearing here, since
        # "07-04-2014" would otherwise silently become 4 July.
        "date_formats": {
            "created":   "%d-%m-%Y",
            "changed":   "%d-%m-%Y",
            "published": "%Y-%m-%d - %H:%M",
        },
        "spatial_temporal": True,
    },
    # AIKosh resource export. Carries content columns the OGD exports lack
    # (short_description / description / alternate_title / keywords), so those
    # Dublin gaps are filled here rather than left empty. cdo_username and
    # cdo_email pass through unmapped: Dublin Core has no contact term in the
    # mapping sheet, and the vCard treatment happens in the DCAT layer only.
    "aikosh_raw": {
        "aliases": {
            "Reference_url":                  "Reference Url",
            "Access_Type":                    "Access Type",
            "field_high_value_dataset_value": "field_high_value_dataset",
        },
        "field_mapping": {
            "Description":       "description",
            "Abstract":          "short_description",
            "Alternative Title": "alternate_title",
            "Subject[keyword]":  "keywords",
        },
        # created/changed are DD-MM-YYYY; dayfirst is load-bearing, as
        # "07-04-2014" would otherwise silently become 4 July.
        "date_formats": {
            "created":   "%d-%m-%Y",
            "changed":   "%d-%m-%Y",
            "published": "%Y-%m-%d - %H:%M",
            "till_date": "%d-%m-%Y",
        },
        "spatial_temporal": True,
    },
    # Lot 3 resource export. Same column spellings as remaining-raw-datasets,
    # but no spatial_coverage column and a till_date that carries a time part
    # ("31-07-2016 00:00"), so it needs its own format rather than aikosh's
    # bare %d-%m-%Y (which would coerce every value to NaT).
    "lot3_raw": {
        "aliases": {
            "Reference_url":                  "Reference Url",
            "Access_Type":                    "Access Type",
            "field_high_value_dataset_value": "field_high_value_dataset",
        },
        # Verified against the table: created/changed are uniformly DD-MM-YYYY
        # (first component reaches 31, second stops at 12), so dayfirst is
        # load-bearing here.
        "date_formats": {
            "created":   "%d-%m-%Y",
            "changed":   "%d-%m-%Y",
            "published": "%Y-%m-%d - %H:%M",
            # Both shapes occur; see convert_date_columns for the ordering rule.
            "till_date": ["%d-%m-%Y %H:%M", "%d-%m-%Y"],
        },
        # Temporal only: data_time_period_from/_to are present, spatial_coverage
        # is not.
        "spatial_temporal": True,
    },
}


def effective_mapping(profile: dict | None = None) -> dict[str, str | None]:
    """FIELD_MAPPING with the profile's per-source overrides applied.

    A field that is a gap for one source (Description, Abstract, keywords...)
    may be present in another export, so profiles can fill it in rather than
    forcing every source to share the lowest common denominator.
    """
    mapping = dict(FIELD_MAPPING)
    mapping.update((profile or {}).get("field_mapping", {}))
    return mapping


def rename_columns(df: pd.DataFrame, mapping: dict | None = None) -> pd.DataFrame:

    mapping = mapping or FIELD_MAPPING
    # Build the reverse lookup: ogd_name → dublin_core_name
    ogd_to_dc: dict[str, str] = {
        ogd_col: dc_name
        for dc_name, ogd_col in mapping.items()
        if ogd_col is not None
    }

    rename_map = {
        col: ogd_to_dc[col]
        for col in df.columns
        if col in ogd_to_dc
    }

    return df.rename(columns=rename_map)


def convert_date_columns(df: pd.DataFrame,
                         date_columns: list[str] | None = None,
                         date_formats: dict[str, str] | None = None) -> pd.DataFrame:

    if date_columns is None:
        date_columns = DATE_COLUMNS_OGD
    date_formats = date_formats or {}

    # An explicit per-column format takes precedence over the mixed-parse default.
    columns = list(dict.fromkeys(list(date_columns) + list(date_formats)))

    df = df.copy()
    for col in columns:
        if col not in df.columns:
            continue
        fmt = date_formats.get(col)
        if fmt:
            # A column may declare several formats: lot3's till_date carries both
            # "31-07-2016 00:00" and a bare "01-02-2025". They are tried in order
            # and each fills only what the previous ones left unparsed, so a
            # single strict format never silently nulls the other shape.
            formats = [fmt] if isinstance(fmt, str) else list(fmt)
            parsed = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
            for f in formats:
                todo = parsed.isna()
                if not todo.any():
                    break
                parsed[todo] = pd.to_datetime(
                    df.loc[todo, col], format=f, errors="coerce")
        else:
            # pd.to_datetime with dayfirst=False handles M/D/YYYY
            parsed = pd.to_datetime(df[col], format="mixed", dayfirst=False, errors="coerce")
        df[col] = parsed.dt.strftime("%Y-%m-%d")
    return df


def build_temporal_coverage(df: pd.DataFrame) -> pd.Series:
    """
    Collapse data_time_period_from/_to into a single DCMI-style ISO interval
    ("2013-07-24/2013-07-24"). The source keeps both endpoints; the Dublin Core
    table has only one Temporal Coverage column, so the range is encoded rather
    than one endpoint being dropped.
    """
    def date_part(col: str) -> pd.Series:
        s = df[col] if col in df.columns else pd.Series([None] * len(df), index=df.index)
        # Some exports carry the literal string "NULL" rather than an empty cell.
        s = s.replace(r"^\s*(NULL|null|NaN|nan|None)\s*$", None, regex=True)
        # These endpoints arrive in three shapes: "2015-06-01T00:00:00",
        # "2019-04-01 0:00:00" and "01-04-2022 0:00". A bare to_datetime()
        # infers one format from the first row and silently coerces the rest
        # to NaT, so parse with format="mixed" -- and split the year-first
        # from the day-first shapes, because dayfirst is load-bearing for the
        # latter ("01-04-2022" is 1 April, not 4 January) and wrong for the
        # former.
        iso = s.str.match(r"^\s*\d{4}-", na=False)
        parsed = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
        if iso.any():
            parsed[iso] = pd.to_datetime(
                s[iso], format="mixed", dayfirst=False, errors="coerce")
        if (~iso).any():
            parsed[~iso] = pd.to_datetime(
                s[~iso], format="mixed", dayfirst=True, errors="coerce")
        return parsed.dt.strftime("%Y-%m-%d").fillna("")

    start, end = date_part("data_time_period_from"), date_part("data_time_period_to")
    combined = start.str.cat(end, sep="/")
    # Blank out rows where neither endpoint parsed, rather than emitting a bare "/".
    return combined.where(combined != "/", None)


def transform_metadata(df: pd.DataFrame, profile: dict | None = None) -> pd.DataFrame:
    df = df.copy()
    profile = profile or SOURCE_PROFILES["raw_metadata"]

    # Step 0 — Normalise source-specific column spellings to the OGD names
    aliases = {k: v for k, v in profile.get("aliases", {}).items() if k in df.columns}
    if aliases:
        df = df.rename(columns=aliases)
        print(f"[0/4] Normalised {len(aliases)} source column names: {aliases}")

    # Step 1 — Convert date columns (while OGD names still exist)
    df = convert_date_columns(df, date_formats=profile.get("date_formats"))
    converted = sorted(set(DATE_COLUMNS_OGD) | set(profile.get("date_formats", {})))
    print(f"[1/4] Converted date columns to ISO 8601: {converted}")

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
    mapping = effective_mapping(profile)
    df = rename_columns(df, mapping)
    print(f"[3/4] Renamed {sum(1 for c in df.columns if c in mapping)} columns to Dublin Core names")

    # Step 3b — Populate Spatial/Temporal Coverage where the source already has
    # them, so the gap-fill below does not blank real values.
    if profile.get("spatial_temporal"):
        if "spatial_coverage" in df.columns:
            df["Spatial Coverage"] = df["spatial_coverage"]
            spatial_note = f"Spatial Coverage ({df['Spatial Coverage'].notna().sum()} rows)"
        else:
            # Not every temporal source carries spatial_coverage; Step 4 adds the
            # column as an empty gap field instead.
            spatial_note = "Spatial Coverage (no source column)"
        df["Temporal Coverage"] = build_temporal_coverage(df)
        print(f"[3b/4] Populated {spatial_note} and Temporal Coverage "
              f"({df['Temporal Coverage'].notna().sum()} rows) from source columns")

    # Step 4 — Add gap Dublin Core columns as empty. This covers both the
    # unmapped fields and any RENAME field whose source column was absent
    # (e.g. Creator/cdos_state_ministry, which remaining-raw-datasets lacks),
    # so every source yields the same Dublin Core column set.
    gap_fields = [
        dc_name for dc_name in mapping
        if dc_name not in df.columns
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
    con.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM df')
    row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    col_count = con.execute(
        f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'"
    ).fetchone()[0]
    print(f"\n✓ Loaded {row_count} rows × {col_count} columns into {db_path}::{table_name}")
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transform raw_metadata to Dublin Core format.")
    parser.add_argument("--batch", type=int, default=None,
                        help="Process only this batch number (appends to existing table)")
    parser.add_argument("--source-table", default="raw_metadata",
                        help="Source table to transform (default: raw_metadata)")
    parser.add_argument("--target-table", default=None,
                        help="Destination table (default: dublin_core_metadata)")
    parser.add_argument("--db", default=str(Path(__file__).parent / "metadata.db"),
                        help="Path to metadata.db (default: alongside this script)")
    parser.add_argument("--ministry", default=None,
                        help="Transform only rows whose ministry_department contains this text "
                             "(case-insensitive). Implies APPEND: the slice is inserted into the "
                             "existing target instead of dropping and rebuilding it.")
    args = parser.parse_args()

    # --ministry and --batch both mean 'append a slice'; the no-batch path drops
    # the target, so appending is the only safe write mode for them.
    append_mode = args.batch is not None or args.ministry is not None

    DB_PATH = args.db
    SOURCE_TABLE = args.source_table
    TARGET_TABLE = args.target_table or "dublin_core_metadata"
    PROFILE = SOURCE_PROFILES.get(SOURCE_TABLE, SOURCE_PROFILES["raw_metadata"])

    # The no-batch path drops the target. dublin_core_metadata carries ~33 columns
    # of downstream enrichment, so rebuilding it must be a deliberate act.
    if TARGET_TABLE == "dublin_core_metadata" and SOURCE_TABLE != "raw_metadata":
        parser.error(
            f"refusing to overwrite dublin_core_metadata from '{SOURCE_TABLE}'. "
            f"Pass --target-table to write elsewhere."
        )

    # --- Read source table from existing DuckDB ---
    con = duckdb.connect(DB_PATH)
    if args.ministry is not None:
        # Substring, not equality: a ministry also appears inside joint attributions
        # ("NITI Aayog, Unique Identification Authority of India (UIDAI)").
        pattern = args.ministry.replace("'", "''")
        matched = con.execute(
            f'SELECT ministry_department, count(*) FROM "{SOURCE_TABLE}" '
            f"WHERE ministry_department ILIKE '%{pattern}%' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        for value, count in matched:
            print(f"  ministry match: {value!r} -> {count} row(s)")
        df_ogd = con.execute(
            f'SELECT * FROM "{SOURCE_TABLE}" '
            f"WHERE ministry_department ILIKE '%{pattern}%'"
        ).fetchdf()
        print(f"Source: {len(df_ogd)} rows from {SOURCE_TABLE} (ministry ~ {args.ministry!r})\n")
    elif args.batch is not None:
        query = f'SELECT * FROM "{SOURCE_TABLE}" WHERE batch = {args.batch}'
        df_ogd = con.execute(query).fetchdf()
        print(f"Source: {len(df_ogd)} rows from {SOURCE_TABLE} (batch {args.batch})\n")
    else:
        source_count = con.execute(f'SELECT COUNT(*) FROM "{SOURCE_TABLE}"').fetchone()[0]
        print(f"Source: {source_count} rows in {DB_PATH}::{SOURCE_TABLE}\n")
        df_ogd = con.execute(f'SELECT * FROM "{SOURCE_TABLE}"').fetchdf()
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
    df_dc = transform_metadata(df_ogd, PROFILE)

    if append_mode:
        # Append mode: insert into existing table (or create if it is the first slice)
        slice_label = f"batch {args.batch}" if args.batch is not None else f"ministry {args.ministry!r}"
        con = duckdb.connect(DB_PATH)
        table_exists = con.execute(
            f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{TARGET_TABLE}'"
        ).fetchone()[0]
        if table_exists:
            con.execute(f'INSERT INTO "{TARGET_TABLE}" BY NAME SELECT * FROM df_dc')
            row_count = con.execute(f'SELECT COUNT(*) FROM "{TARGET_TABLE}"').fetchone()[0]
            print(f"\n✓ Appended {len(df_dc)} rows ({slice_label}). Total: {row_count}")
        else:
            con.execute(f'CREATE TABLE "{TARGET_TABLE}" AS SELECT * FROM df_dc')
            print(f"\n✓ Created {TARGET_TABLE} with {len(df_dc)} rows ({slice_label})")
        con.close()
    else:
        load_to_duckdb(df_dc, db_path=DB_PATH, table_name=TARGET_TABLE)

    # --- Quick verification ---
    con = duckdb.connect(DB_PATH)
    print("\n── Sample output (first 2 rows, key columns) ──")
    preview_cols = [
        "Title", "Identifier[UUID]", "Date Created", "Date Issued",
        "Date Modified", "Type", "Jurisdiction", "Creator",
        "Identifier[landing_page]",
    ]
    present = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [TARGET_TABLE],
    ).fetchall()}
    select_list = ", ".join(f'"{c}"' for c in preview_cols if c in present)
    preview = con.execute(f'SELECT {select_list} FROM "{TARGET_TABLE}" LIMIT 2').fetchdf()
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