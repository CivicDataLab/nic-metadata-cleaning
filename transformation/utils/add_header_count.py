"""
Add a `header_count` column to dublin_core_metadata, populated from the
comma-separated header list in `Conforms To`.

Usage:
  python add_header_count.py
  python add_header_count.py --dry-run
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"


def main(dry_run: bool = False) -> None:
    con = duckdb.connect(DB_PATH)
    try:
        existing_cols = {row[0] for row in con.execute("DESCRIBE dublin_core_metadata").fetchall()}
        if "header_count" not in existing_cols:
            if dry_run:
                print("[dry-run] Would add column: header_count INTEGER")
            else:
                con.execute('ALTER TABLE dublin_core_metadata ADD COLUMN header_count INTEGER')
                print("Added column: header_count")
        else:
            print("Column header_count already exists.")

        # Empty/blank entries between commas are not counted as headers.
        update_sql = """
        UPDATE dublin_core_metadata
        SET header_count = CASE
            WHEN "Conforms To" IS NULL OR TRIM("Conforms To") = '' THEN 0
            ELSE len(list_filter(
                string_split("Conforms To", ','),
                x -> TRIM(x) != ''
            ))
        END
        """

        if dry_run:
            preview = con.execute("""
            SELECT
                "Conforms To",
                CASE
                    WHEN "Conforms To" IS NULL OR TRIM("Conforms To") = '' THEN 0
                    ELSE len(list_filter(
                        string_split("Conforms To", ','),
                        x -> TRIM(x) != ''
                    ))
                END AS header_count
            FROM dublin_core_metadata
            LIMIT 5
            """).fetchdf()
            print("\n[dry-run] Preview of computed counts:")
            print(preview.to_string(index=False))
            return

        con.execute(update_sql)

        summary = con.execute("""
        SELECT
            COUNT(*)                                AS total_rows,
            COUNT(header_count)                     AS rows_with_count,
            MIN(header_count)                       AS min_headers,
            MAX(header_count)                       AS max_headers,
            ROUND(AVG(header_count), 2)             AS avg_headers
        FROM dublin_core_metadata
        """).fetchdf()
        print("\nUpdate complete:")
        print(summary.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add header_count column to dublin_core_metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
