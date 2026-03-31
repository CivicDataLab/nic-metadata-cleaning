import duckdb

conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")

#duckdb.read_csv('/home/aakash/NIC/Newfolder/nic-metadata-cleaning/nic_sample_dataset.csv')


# conn.execute("CREATE TABLE raw_metadata AS FROM '/home/aakash/NIC/Newfolder/ResourceList_DoFHW/ResourceList_Department-of-Health-and-Family-Welfare.xlsx';")

# conn.execute("SELECT * FROM raw_metadata LIMIT 10")


conn.execute("""
CREATE OR REPLACE TABLE raw_metadata_with_batch AS
SELECT *, 
       CAST((ROW_NUMBER() OVER (ORDER BY rowid) - 1) // 5000 AS INTEGER) + 1 AS batch
FROM raw_metadata;
""")

if __name__ == "__main__":
    total_count = conn.execute("SELECT COUNT(*) FROM raw_metadata_with_batch").fetchall()
    print(f"Total rows: {total_count}")
    
    # Check batch distribution
    print("\nBatch distribution:")
    result = conn.execute("SELECT batch, COUNT(*) as count FROM raw_metadata_with_batch GROUP BY batch ORDER BY batch").fetchall()
    print(result)
    
    # Check specific rows around batch boundaries
    print("\nFirst row of each batch:")
    result = conn.execute("SELECT rowid, batch FROM raw_metadata_with_batch WHERE rowid IN (1, 5001, 10001, 15001, 20001)").fetchall()
    print(result)
    
    print("\nLast row of each batch:")
    result = conn.execute("SELECT rowid, batch FROM raw_metadata_with_batch WHERE rowid IN (5000, 10000, 15000, 20000, 25000)").fetchall()
    print(result)

