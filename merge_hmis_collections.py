#!/usr/bin/env python3
"""
Merge HMIS Item-wise State level collections vertically.
Reads from first_batch_downloads, groups by collection, and merges with financial_year and month columns.

Each source collection is split by report basis before merging: datasets titled
"... at State level for {Month}-{FY}" are Monthly, "... upto {Month}-{FY}" are Cumulative.
So 'Item-wise HMIS report at State level from financial year 2008-09 to 2013-14' becomes
'Item-wise Monthly HMIS report ...' and 'Item-wise Cumulative HMIS report ...'.
"""

import pandas as pd
import os
import duckdb
from pathlib import Path

# Paths
downloads_dir = 'data/first_batch_downloads'
output_dir = 'data/hmis_itemwise_state_level_merged_collections'
db_path = 'transformation/metadata.db'

# Create output directory
os.makedirs(output_dir, exist_ok=True)

# Read from DuckDB instead of manifest
conn = duckdb.connect(db_path, read_only=True)
manifest = conn.execute("""
    SELECT
        "Identifier[UUID]" as source_uuid,
        Title as source_title,
        Collection as source_collection,
        -- report basis lives only in the title: 'for {Month}' = that month alone,
        -- 'upto {Month}' = cumulative from the start of the financial year
        CASE WHEN Title LIKE '%level for %' THEN 'Monthly'
             WHEN Title LIKE '%level upto %' THEN 'Cumulative'
        END as report_basis,
        replace(
            Collection,
            'Item-wise HMIS',
            'Item-wise ' || CASE WHEN Title LIKE '%level for %' THEN 'Monthly'
                                 WHEN Title LIKE '%level upto %' THEN 'Cumulative'
                            END || ' HMIS'
        ) as new_collection,
        Financial_Year,
        Month
    FROM dublin_core_metadata
    WHERE Collection LIKE '%Item-wise HMIS report at State level from financial year%'
    ORDER BY new_collection, Financial_Year,
        CASE Month
            WHEN 'April' THEN 1 WHEN 'May' THEN 2 WHEN 'June' THEN 3
            WHEN 'July' THEN 4 WHEN 'August' THEN 5 WHEN 'September' THEN 6
            WHEN 'October' THEN 7 WHEN 'November' THEN 8 WHEN 'December' THEN 9
            WHEN 'January' THEN 10 WHEN 'February' THEN 11 WHEN 'March' THEN 12
        END
""").df()
conn.close()

# Every title must classify as Monthly or Cumulative — a NULL basis would silently
# produce a collection named 'Item-wise None HMIS report ...'
unclassified = manifest[manifest['report_basis'].isna()]
if len(unclassified):
    raise SystemExit(f"{len(unclassified)} datasets have neither 'for' nor 'upto' in the title:\n"
                     f"{unclassified['source_title'].tolist()}")

# Get unique collections (post-rename: one per source collection x report basis)
collections = manifest['new_collection'].unique()

print(f"Found {len(collections)} collections")
for c in collections:
    print(f"  - {c}")

# Process each collection
for collection in collections:
    print(f"\n{'='*80}")
    print(f"Processing: {collection}")
    print(f"{'='*80}")

    # Get all rows for this collection
    collection_data = manifest[manifest['new_collection'] == collection].copy()
    print(f"Found {len(collection_data)} datasets in this collection")

    # Load all CSV files
    dfs = []
    for _, row in collection_data.iterrows():
        uuid = row['source_uuid']
        fy = row['Financial_Year']
        month = row['Month']

        csv_path = os.path.join(downloads_dir, f"{uuid}.csv")

        if os.path.exists(csv_path):
            try:
                # Try different encodings. Only swallow decode errors — a parser
                # error must surface rather than be retried as latin-1 garbage.
                encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin-1']
                df = None
                for encoding in encodings:
                    try:
                        df = pd.read_csv(csv_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue

                if df is not None:
                    # Add financial_year and month columns
                    df['financial_year'] = fy
                    df['month'] = month
                    dfs.append(df)
                    print(f"  ✓ Loaded {uuid} ({fy}-{month}): {len(df)} rows")
                else:
                    print(f"  ✗ Failed to load {uuid}: unsupported encoding")
            except Exception as e:
                print(f"  ✗ Failed to load {uuid}: {e}")
        else:
            print(f"  ✗ File not found: {csv_path}")

    if dfs:
        # Combine all dataframes vertically
        combined_df = pd.concat(dfs, ignore_index=True)
        print(f"\n  Total combined rows: {len(combined_df)}")
        print(f"  Columns: {list(combined_df.columns)}")

        # Create output filename from collection name
        safe_collection_name = collection.replace('/', '_').replace(' ', '_')
        output_path = os.path.join(output_dir, f"{safe_collection_name}.csv")

        # Save to CSV
        combined_df.to_csv(output_path, index=False)
        print(f"\n  Saved to: {output_path}")

        # Print summary stats
        print(f"\n  Summary:")
        print(f"    Total rows: {len(combined_df)}")
        print(f"    Total columns: {len(combined_df.columns)}")
        print(f"    Unique financial years: {combined_df['financial_year'].nunique()}")
        print(f"    Unique months: {combined_df['month'].nunique()}")
        print(f"    Datasets merged: {len(dfs)} of {len(collection_data)}")
    else:
        print(f"  ✗ No data loaded for {collection}")

print(f"\n{'='*80}")
print("Merge complete!")
print(f"Output directory: {output_dir}")
