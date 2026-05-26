"""
Collection -> catalog link CSV.

Reads dublin_core_metadata and writes a flat CSV with one row per
(collection, unique catalog URL) pair. Catalog URLs are derived from
"Relation[Catalog Title]" by lowercasing, replacing spaces with '-',
and prefixing with https://data.gov.in/catalog/.

Usage:
    python collection_catalog_links.py
    python collection_catalog_links.py --db /path/to/metadata.db
    python collection_catalog_links.py --out /tmp/collection_catalog_links.csv
"""

import argparse
import csv
import re
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "metadata.db"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "collection_catalog_links.csv"
BASE_URL = "https://data.gov.in/catalog/"


def catalog_title_to_url(title: str) -> str:
    slug = re.sub(r"\s+", "-", title.strip().lower())
    return BASE_URL + slug


def fetch_pairs(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    rows = conn.execute("""
        SELECT DISTINCT
            "Collection"              AS collection_name,
            "Relation[Catalog Title]" AS catalog_title
        FROM dublin_core_metadata
        WHERE "Collection" IS NOT NULL
          AND "Relation[Catalog Title]" IS NOT NULL
          AND TRIM("Relation[Catalog Title]") <> ''
        ORDER BY collection_name, catalog_title
    """).fetchall()
    return [(c, catalog_title_to_url(t)) for c, t in rows]


def write_csv(pairs: list[tuple[str, str]], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["collection_name", "catalog_url"])
        w.writerows(pairs)


def main():
    parser = argparse.ArgumentParser(description="Generate collection -> catalog link CSV")
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB database path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output CSV path")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(args.db, read_only=True)
    try:
        pairs = fetch_pairs(conn)
    finally:
        conn.close()

    write_csv(pairs, out_path)
    collections = len({c for c, _ in pairs})
    print(f"CSV written: {out_path}  ({collections} collections, {len(pairs)} rows)")


if __name__ == "__main__":
    main()
