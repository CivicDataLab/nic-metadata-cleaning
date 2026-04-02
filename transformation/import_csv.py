import duckdb
import pandas as pd

conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")

excel_file = '/home/aakash/NIC/Newfolder/ResourceList_DoFHW/ResourceList_Department-of-Health-and-Family-Welfare.xlsx'

# Read Excel file with first row as headers (header=0 is default)
df = pd.read_excel(excel_file, header=0)

# Drop unnamed columns (empty columns)
df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

print("Column names after reading Excel:")
print(df.columns.tolist())

# Create the raw_metadata table from the properly formatted dataframe
conn.execute("DROP TABLE IF EXISTS raw_metadata")
conn.from_df(df).create("raw_metadata")

# Create the table with batch column
conn.execute("""
CREATE OR REPLACE TABLE raw_metadata AS
SELECT *, 
       CAST((ROW_NUMBER() OVER (ORDER BY rowid) - 1) // 5000 AS INTEGER) + 1 AS batch
FROM raw_metadata;
""")

if __name__ == "__main__":
    # Verify the fix
    print("\n✓ Column names in raw_metadata after fix:")
    columns = conn.execute("SELECT * FROM raw_metadata LIMIT 0").description
    col_names = [desc[0] for desc in columns]
    print(col_names)
    
    # Show sample data
    print("\n✓ Sample data (first row with key columns):")
    result = conn.execute("SELECT nid, uuid, title, batch FROM raw_metadata LIMIT 1").fetchall()
    for row in result:
        print(f"  nid: {row[0]}, uuid: {row[1]}, title: {row[2]}, batch: {row[3]}")
    
    total_count = conn.execute("SELECT COUNT(*) FROM raw_metadata").fetchall()
    print(f"\n✓ Total rows: {total_count[0][0]}")
    
    # Check batch distribution
    print("\n✓ Batch distribution:")
    result = conn.execute("SELECT batch, COUNT(*) as count FROM raw_metadata GROUP BY batch ORDER BY batch").fetchall()
    for row in result:
        print(f"  Batch {row[0]}: {row[1]} rows")
    
    print("\n✓ Headers successfully updated!")

conn.close()