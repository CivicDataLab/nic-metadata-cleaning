

import duckdb


enhancement_fields = [
    "title",
    "uuid",
    "catalog_title",
    "note",
    "frequency",
    "govt_type",
    "granularity",
    "ministry_department",
    "sector",
    "sector_resource"
]


def create_metadata_enhancement_table(
    db_path: str = "metadata.db",
    source_table: str = "raw_metadata",
    target_table: str = "metadata_enhancement",
    fields: list[str] | None = None
) -> None:

    if fields is None:
        fields = enhancement_fields

    con = duckdb.connect(db_path)

    try:
        # Verify source table exists
        source_check = con.execute(
            f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{source_table}'"
        ).fetchone()[0]

        if source_check == 0:
            print(f"✗ Error: Source table '{source_table}' not found in {db_path}")
            return

        # Get all columns from source table for validation
        available_columns = con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{source_table}'"
        ).fetchall()
        available_columns = [col[0] for col in available_columns]

        # Validate that requested fields exist in source table
        missing_fields = [f for f in fields if f not in available_columns]
        if missing_fields:
            print(f"✗ Warning: The following fields are not in '{source_table}': {missing_fields}")
            print(f"  Available fields: {available_columns}")
            fields = [f for f in fields if f in available_columns]
            if not fields:
                print("✗ Error: No valid fields to select. Aborting.")
                return

        # Build the SELECT statement
        fields_str = ", ".join([f'"{f}"' for f in fields])
        select_query = f"SELECT {fields_str} FROM {source_table}"

        # Create the new table
        con.execute(f"CREATE TABLE {target_table} AS {select_query}")
        print(f"[2/3] Created table {target_table} with {len(fields)} fields")

        # Verify the creation
        row_count = con.execute(f"SELECT COUNT(*) FROM {target_table}").fetchone()[0]
        col_count = len(fields)
        print(f"[3/3] Loaded {row_count} rows × {col_count} columns into {target_table}")

        # Display table info
        print(f"\n✓ Successfully created {target_table}")
        print(f"  Location: {db_path}::{target_table}")
        print(f"  Rows: {row_count}")
        print(f"  Columns: {col_count}")
        print(f"\n  Fields included:")
        for field in fields:
            print(f"    - {field}")

    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        con.close()


if __name__ == "__main__":
    DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"


    print(f"Fields to extract: {len(enhancement_fields)}")
    print()

    create_metadata_enhancement_table(db_path=DB_PATH)

    # Quick preview
    try:
        con = duckdb.connect(DB_PATH)
        print("\n── Sample output (first 3 rows) ──")
        preview = con.execute(f"""
            SELECT * FROM metadata_enhancement LIMIT 3
        """).fetchdf()
        print(preview.to_string(index=False))
        con.close()
    except Exception as e:
        print(f"Error displaying preview: {e}")