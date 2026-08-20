import duckdb

DB_PATH = "transformation/metadata.db"
OUT_CSV = "pii_test_timestamps.csv"

con = duckdb.connect(DB_PATH, read_only=True)
con.execute(f"""
    COPY (
        SELECT nid, pii_test_timestamp
        FROM dublin_core_metadata
        ORDER BY pii_test_timestamp DESC NULLS LAST
    ) TO '{OUT_CSV}' (HEADER, DELIMITER ',')
""")
n = con.execute("SELECT COUNT(*) FROM dublin_core_metadata").fetchone()[0]
con.close()

print(f"Wrote {n:,} rows → {OUT_CSV}")