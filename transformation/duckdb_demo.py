# import duckdb

# DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
# OUTPUT_CSV = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/dublin_core_metadata.csv"

# conn = duckdb.connect(DB_PATH)
# conn.execute(f"COPY dublin_core_metadata TO '{OUTPUT_CSV}' (HEADER, DELIMITER ',')")
# row_count = conn.execute("SELECT COUNT(*) FROM dublin_core_metadata").fetchone()[0]
# conn.close()

# print(f"Exported {row_count} rows to {OUTPUT_CSV}")



# conn = duckdb.connect("/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db")
# result = conn.execute("SELECT * FROM llm_keyword_results LIMIT 10;")

# print(result)
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


import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
CSV_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/text_generation/llm_keyword_results.csv"
ROWS_TO_INSERT = 3000

conn = duckdb.connect(DB_PATH)

# Columns present in the DB table
table_cols = {row[0] for row in conn.execute("DESCRIBE llm_keyword_results").fetchall()}

# Columns present in the CSV
csv_cols = [desc[0] for desc in conn.execute(f"SELECT * FROM read_csv('{CSV_PATH}', header=true, null_padding=true, parallel=false) LIMIT 0").description]

# Columns that exist in both (preserve CSV order so SELECT aligns with INSERT)
shared_cols = [c for c in csv_cols if c in table_cols]

# Columns only in the table → supply NULL so every table column gets a value
null_cols = [c for c in conn.execute("DESCRIBE llm_keyword_results").fetchall()
             if c[0] not in set(shared_cols)]

insert_cols = shared_cols + [c[0] for c in null_cols]
select_exprs = shared_cols + [f"NULL AS {c[0]}" for c in null_cols]

total_rows = conn.execute(f"SELECT COUNT(*) FROM read_csv('{CSV_PATH}', header=true, null_padding=true, parallel=false)").fetchone()[0]
offset = max(0, total_rows - ROWS_TO_INSERT)

count_before = conn.execute("SELECT COUNT(*) FROM llm_keyword_results").fetchone()[0]

conn.execute(f"""
    INSERT INTO llm_keyword_results ({', '.join(insert_cols)})
    SELECT {', '.join(select_exprs)}
    FROM read_csv('{CSV_PATH}', header=true, null_padding=true, parallel=false)
    OFFSET {offset}
""")

count_after = conn.execute("SELECT COUNT(*) FROM llm_keyword_results").fetchone()[0]
conn.close()

print(f"Inserted {count_after - count_before} rows into llm_keyword_results")
print(f"  CSV total rows : {total_rows}")
print(f"  Offset applied : {offset}")
print(f"  Shared columns : {shared_cols}")
if null_cols:
    print(f"  NULL-filled cols: {[c[0] for c in null_cols]}")

