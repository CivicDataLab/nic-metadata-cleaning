import duckdb
import pandas as pd

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
SOURCE_CSV = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/utils/pii_test_timestamp.csv"


def main():
    if not SOURCE_CSV:
        raise SystemExit("SOURCE_CSV is not set. Edit import_csv.py and set the path to the source csv.")

    df = pd.read_csv(SOURCE_CSV)

    expected = {"nid", "pii_test_timestamp"}
    missing_cols = expected - set(df.columns)
    if missing_cols:
        raise SystemExit(f"Source csv is missing required columns: {sorted(missing_cols)}. Found: {df.columns.tolist()}")

    df = df[["nid", "pii_test_timestamp"]].dropna(subset=["nid"])

    dup_count = df["nid"].duplicated().sum()
    if dup_count:
        print(f"Warning: {dup_count} duplicate nids in source — keeping latest (last occurrence).")
        df = df.drop_duplicates(subset=["nid"], keep="last")

    print(f"Loaded {len(df)} unique-nid rows from {SOURCE_CSV}")

    conn = duckdb.connect(DB_PATH)

    conn.execute('ALTER TABLE dublin_core_metadata ADD COLUMN IF NOT EXISTS pii_test_timestamp TIMESTAMP')

    conn.register("updates", df)

    not_found = conn.execute("""
        SELECT COUNT(*) FROM updates u
        LEFT JOIN dublin_core_metadata d ON CAST(d.nid AS VARCHAR) = CAST(u.nid AS VARCHAR)
        WHERE d.nid IS NULL
    """).fetchone()[0]
    print(f"nids in source not found in dublin_core_metadata: {not_found}")

    matched = conn.execute("""
        SELECT COUNT(*) FROM dublin_core_metadata d
        JOIN updates u ON CAST(d.nid AS VARCHAR) = CAST(u.nid AS VARCHAR)
    """).fetchone()[0]

    conn.execute("""
        UPDATE dublin_core_metadata AS d
        SET pii_test_timestamp = CAST(u.pii_test_timestamp AS TIMESTAMP)
        FROM updates AS u
        WHERE CAST(d.nid AS VARCHAR) = CAST(u.nid AS VARCHAR)
    """)

    print(f"Rows matched and updated in dublin_core_metadata: {matched}")

    sample = conn.execute("""
        SELECT d.nid, d.pii_test_timestamp
        FROM dublin_core_metadata d
        JOIN updates u ON CAST(d.nid AS VARCHAR) = CAST(u.nid AS VARCHAR)
        LIMIT 5
    """).fetchall()
    print("Sample updated rows (dublin_core_metadata):")
    for row in sample:
        print(f"  {row[0]} | pii_test_timestamp={row[1]}")

    conn.close()


if __name__ == "__main__":
    main()
