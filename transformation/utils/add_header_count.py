"""
Add a `header_count` column to a metadata table, populated from the
comma-separated header list in `Conforms To`.

Usage:
  python add_header_count.py
  python add_header_count.py --dry-run
  python add_header_count.py --table dublin_core_remaining
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"


DEFAULT_TABLE = "dublin_core_metadata"


def main(dry_run: bool = False, table: str = DEFAULT_TABLE,
         keep_null_when_blank: bool = False) -> None:
    con = duckdb.connect(DB_PATH)
    try:
        existing_cols = {row[0] for row in con.execute(f'DESCRIBE "{table}"').fetchall()}
        if "header_count" not in existing_cols:
            if dry_run:
                print("[dry-run] Would add column: header_count INTEGER")
            else:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN header_count INTEGER')
                print("Added column: header_count")
        else:
            print("Column header_count already exists.")

        # Empty/blank entries between commas are not counted as headers.
        #
        # A blank "Conforms To" means two different things depending on the
        # table. On dublin_core_metadata it is a genuine empty header list, so
        # 0 is right. On dublin_core_remaining it means the dataset was never
        # downloaded and its headers are unknown — writing 0 there would make
        # "no file to read" indistinguishable from "a file with no columns",
        # so --keep-null-when-blank leaves those rows NULL.
        blank_case = "NULL" if keep_null_when_blank else "0"
        where = ('WHERE "Conforms To" IS NOT NULL AND TRIM("Conforms To") != \'\''
                 if keep_null_when_blank else "")
        update_sql = f"""
        UPDATE "{table}"
        SET header_count = CASE
            WHEN "Conforms To" IS NULL OR TRIM("Conforms To") = '' THEN {blank_case}
            ELSE len(list_filter(
                string_split("Conforms To", ','),
                x -> TRIM(x) != ''
            ))
        END
        {where}
        """

        if dry_run:
            preview = con.execute(f"""
            SELECT
                "Conforms To",
                CASE
                    WHEN "Conforms To" IS NULL OR TRIM("Conforms To") = '' THEN 0
                    ELSE len(list_filter(
                        string_split("Conforms To", ','),
                        x -> TRIM(x) != ''
                    ))
                END AS header_count
            FROM "{table}"
            LIMIT 5
            """).fetchdf()
            print("\n[dry-run] Preview of computed counts:")
            print(preview.to_string(index=False))
            return

        con.execute(update_sql)

        summary = con.execute(f"""
        SELECT
            COUNT(*)                                AS total_rows,
            COUNT(header_count)                     AS rows_with_count,
            MIN(header_count)                       AS min_headers,
            MAX(header_count)                       AS max_headers,
            ROUND(AVG(header_count), 2)             AS avg_headers
        FROM "{table}"
        """).fetchdf()
        print("\nUpdate complete:")
        print(summary.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add header_count column to a metadata table.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing.")
    parser.add_argument("--table", default=DEFAULT_TABLE,
                        help=f"target table (default {DEFAULT_TABLE})")
    parser.add_argument("--keep-null-when-blank", action="store_true",
                        help="leave header_count NULL where Conforms To is blank, "
                             "instead of writing 0 (use on dublin_core_remaining, "
                             "where blank means never downloaded)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, table=args.table,
         keep_null_when_blank=args.keep_null_when_blank)
