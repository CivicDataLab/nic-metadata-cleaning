import duckdb

# DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
# OUTPUT_CSV = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/dublin_core_metadata.csv"

# conn = duckdb.connect(DB_PATH)
# conn.execute(f"COPY dublin_core_metadata TO '{OUTPUT_CSV}' (HEADER, DELIMITER ',')")
# row_count = conn.execute("SELECT COUNT(*) FROM dublin_core_metadata").fetchone()[0]
# conn.close()

# print(f"Exported {row_count} rows to {OUTPUT_CSV}")



conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")
result = conn.execute("SELECT * FROM llm_keyword_results LIMIT 10;")

print(result)
# columns = [desc[0] for desc in result]
# print("Columns in raw_metadata_with_batch:", columns)



# import duckdb

# conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")

# # Show first few rows with all columns to identify which has UUIDs
# result = conn.execute("SELECT * FROM raw_metadata LIMIT 3").fetchall()

# # Print with column names
# for i, row in enumerate(result):
#     print(f"\nRow {i+1}:")
#     for j, value in enumerate(row):
#         columns = ['A1', 'B1', 'C1', 'D1', 'E1', 'F1', 'G1', 'H1', 'I1', 'J1', 'K1', 'L1', 'M1', 'N1', 'O1', 'P1', 'Q1', 'R1', 'S1', 'T1', 'U1', 'V1', 'W1', 'X1', 'Y1', 'Z1', 'AA1', 'AB1', 'AC1', 'AD1', 'AE1', 'AF1', 'AG1', 'AH1', 'AI1', 'AJ1', 'AK1', 'batch']
#         if j < len(columns):
#             print(f"  {columns[j]}: {value}")

# conn.close()

