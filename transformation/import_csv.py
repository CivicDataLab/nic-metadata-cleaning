import duckdb
import pandas as pd

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
# Source xlsx with columns: uuid (unused — values are stale), Title, accrual_periodicity, coverage
# Join key into dublin_core_metadata is Title (xlsx uuid column does not match Identifier[UUID]).
SOURCE_XLSX = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/aacrualCoveragee.xlsx"


def main():
    if not SOURCE_XLSX:
        raise SystemExit("SOURCE_XLSX is not set. Edit import_csv.py and set the path to the source xlsx.")

    df = pd.read_excel(SOURCE_XLSX, header=0)

    expected = {"Title", "accrual_periodicity", "coverage"}
    missing_cols = expected - set(df.columns)
    if missing_cols:
        raise SystemExit(f"Source xlsx is missing required columns: {sorted(missing_cols)}. Found: {df.columns.tolist()}")

    df = df[["Title", "accrual_periodicity", "coverage"]].dropna(subset=["Title"])

    dup_count = df["Title"].duplicated().sum()
    if dup_count:
        print(f"Warning: {dup_count} duplicate Titles in source — collapsing to first occurrence.")
        df = df.drop_duplicates(subset=["Title"], keep="first")

    print(f"Loaded {len(df)} unique-Title rows from {SOURCE_XLSX}")

    conn = duckdb.connect(DB_PATH)
    conn.register("updates", df)

    not_found = conn.execute("""
        SELECT COUNT(*) FROM updates u
        LEFT JOIN dublin_core_metadata d ON d."Title" = u."Title"
        WHERE d."Title" IS NULL
    """).fetchone()[0]
    print(f"Titles in source not found in dublin_core_metadata: {not_found}")

    matched = conn.execute("""
        SELECT COUNT(*) FROM dublin_core_metadata d
        JOIN updates u ON d."Title" = u."Title"
    """).fetchone()[0]

    conn.execute("""
        UPDATE dublin_core_metadata AS d
        SET "Accrual Periodicity" = u.accrual_periodicity,
            "Coverage"            = u.coverage
        FROM updates AS u
        WHERE d."Title" = u."Title"
    """)

    print(f"Rows matched and updated in dublin_core_metadata: {matched}")

    sample = conn.execute("""
        SELECT d."Identifier[UUID]", d."Accrual Periodicity", d."Coverage"
        FROM dublin_core_metadata d
        JOIN updates u ON d."Title" = u."Title"
        LIMIT 5
    """).fetchall()
    print("Sample updated rows (dublin_core_metadata):")
    for row in sample:
        print(f"  {row[0]} | Accrual Periodicity={row[1]} | Coverage={row[2]}")

    not_found_raw = conn.execute("""
        SELECT COUNT(*) FROM updates u
        LEFT JOIN raw_metadata r ON r."Title" = u."Title"
        WHERE r."Title" IS NULL
    """).fetchone()[0]
    print(f"Titles in source not found in raw_metadata: {not_found_raw}")

    matched_raw = conn.execute("""
        SELECT COUNT(*) FROM raw_metadata r
        JOIN updates u ON r."Title" = u."Title"
    """).fetchone()[0]

    conn.execute("""
        UPDATE raw_metadata AS r
        SET frequency   = u.accrual_periodicity,
            granularity = u.coverage
        FROM updates AS u
        WHERE r."Title" = u."Title"
    """)

    print(f"Rows matched and updated in raw_metadata: {matched_raw}")

    sample_raw = conn.execute("""
        SELECT r.uuid, r.frequency, r.granularity
        FROM raw_metadata r
        JOIN updates u ON r."Title" = u."Title"
        LIMIT 5
    """).fetchall()
    print("Sample updated rows (raw_metadata):")
    for row in sample_raw:
        print(f"  {row[0]} | frequency={row[1]} | granularity={row[2]}")

    conn.close()


if __name__ == "__main__":
    main()
