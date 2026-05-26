import duckdb
import pandas as pd

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
SOURCE_CSV = "/home/aakash/NIC/Newfolder/geo_coverage.csv"  # set to /home/aakash/NIC/Newfolder/geo_coverage.csv (or wherever)


def _clean(value):
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s or s.upper() == "NA":
        return None
    return s.title()


def build_spatial_coverage(state, district, subdistrict):
    parts = [_clean(subdistrict), _clean(district), _clean(state)]
    parts = [p for p in parts if p]
    parts.append("India")
    return ", ".join(parts)


def main():
    if not SOURCE_CSV:
        raise SystemExit("SOURCE_CSV is not set. Edit import_spatial_coverage.py and set the path to the source csv.")

    df = pd.read_csv(SOURCE_CSV, dtype={"nid": "Int64"})

    expected = {"nid", "state", "district", "subdistrict"}
    missing_cols = expected - set(df.columns)
    if missing_cols:
        raise SystemExit(f"Source csv is missing required columns: {sorted(missing_cols)}. Found: {df.columns.tolist()}")

    df = df.dropna(subset=["nid"]).copy()
    df["spatial_coverage"] = df.apply(
        lambda r: build_spatial_coverage(r["state"], r["district"], r["subdistrict"]),
        axis=1,
    )
    df = df[["nid", "spatial_coverage"]]

    dup_count = df["nid"].duplicated().sum()
    if dup_count:
        print(f"Warning: {dup_count} duplicate nids in source — collapsing to first occurrence.")
        df = df.drop_duplicates(subset=["nid"], keep="first")

    print(f"Loaded {len(df)} unique-nid rows from {SOURCE_CSV}")

    conn = duckdb.connect(DB_PATH)

    conn.execute('ALTER TABLE dublin_core_metadata ADD COLUMN IF NOT EXISTS "Spatial Coverage" VARCHAR')

    conn.register("updates", df)

    not_found = conn.execute("""
        SELECT COUNT(*) FROM updates u
        LEFT JOIN dublin_core_metadata d ON d.nid = u.nid
        WHERE d.nid IS NULL
    """).fetchone()[0]
    print(f"nids in source not found in dublin_core_metadata: {not_found}")

    matched = conn.execute("""
        SELECT COUNT(*) FROM dublin_core_metadata d
        JOIN updates u ON d.nid = u.nid
    """).fetchone()[0]

    conn.execute("""
        UPDATE dublin_core_metadata AS d
        SET "Spatial Coverage" = u.spatial_coverage
        FROM updates AS u
        WHERE d.nid = u.nid
    """)

    print(f"Rows matched and updated in dublin_core_metadata: {matched}")

    sample = conn.execute("""
        SELECT d.nid, d."Spatial Coverage"
        FROM dublin_core_metadata d
        JOIN updates u ON d.nid = u.nid
        LIMIT 5
    """).fetchall()
    print("Sample updated rows (dublin_core_metadata):")
    for row in sample:
        print(f"  {row[0]} | Spatial Coverage={row[1]}")

    conn.close()


if __name__ == "__main__":
    main()
