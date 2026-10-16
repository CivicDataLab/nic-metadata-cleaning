import duckdb
from pathlib import Path

# Configuration
DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
XLSX_PATH = "/home/aakash/NIC/Newfolder/remaining-datesets/Ministry Data/Ministry Data  With CDO/Ministry Data  With CDO/Ministry_Data_With_CDO_merged.xlsx"
TABLE_NAME = "remaining-raw-datasets"


def import_xlsx_to_db(xlsx_path: str = XLSX_PATH, db_path: str = DB_PATH, table_name: str = TABLE_NAME) -> int:
    """
    Import a single .xlsx file into DuckDB as a table, via the `excel` extension.

    Columns are read as text to keep this a faithful raw landing table.

    Args:
        xlsx_path: Path to the .xlsx file
        db_path: Path to the DuckDB database
        table_name: Name of the table to create

    Returns:
        Number of rows imported
    """
    xlsx_file = Path(xlsx_path)
    if not xlsx_file.is_file():
        raise FileNotFoundError(f"XLSX file not found: {xlsx_file}")

    conn = duckdb.connect(db_path)
    try:
        conn.execute("INSTALL excel")
        conn.execute("LOAD excel")

        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        conn.execute(
            f'CREATE TABLE "{table_name}" AS '
            "SELECT * FROM read_xlsx(?, all_varchar=true, header=true)",
            [str(xlsx_file)],
        )
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        print(f"✓ Imported {row_count} rows from {xlsx_file.name} into '{table_name}' in {db_path}")
        return row_count
    finally:
        conn.close()


def main():
    try:
        import_xlsx_to_db(XLSX_PATH, DB_PATH, TABLE_NAME)
    except Exception as e:
        print(f"Error: {e}", file=__import__("sys").stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
