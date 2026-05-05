"""
Collection stats generator.

Reads dublin_core_metadata and produces:
  - collection_stats.json  : per-collection stats with dataset titles
  - collection_datasets.csv: flat mapping of dataset_name -> collection_name

Usage:
    python collection_stats.py
    python collection_stats.py --db /path/to/metadata.db
    python collection_stats.py --out-dir /tmp/output
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).parent / "metadata.db"
DEFAULT_OUT_DIR = Path(__file__).parent


def build_collection_stats(conn: duckdb.DuckDBPyConnection) -> dict:
    rows = conn.execute("""
        SELECT
            "Collection",
            "Title",
            "nid"
        FROM dublin_core_metadata
        WHERE "Collection" IS NOT NULL
        ORDER BY "Collection", "Title"
    """).fetchall()

    collections: dict[str, dict] = {}
    for collection, title, nid in rows:
        if collection not in collections:
            collections[collection] = {"collection": collection, "dataset_count": 0, "datasets": []}
        collections[collection]["dataset_count"] += 1
        collections[collection]["datasets"].append({"nid": nid, "title": title})

    total_collections = len(collections)
    total_datasets = sum(c["dataset_count"] for c in collections.values())

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_collections": total_collections,
        "total_datasets_in_collections": total_datasets,
        "collections": list(collections.values()),
    }


def write_json(stats: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def write_csv(conn: duckdb.DuckDBPyConnection, path: Path) -> None:
    rows = conn.execute("""
        SELECT
            "Title"      AS dataset_name,
            "Collection" AS collection_name
        FROM dublin_core_metadata
        WHERE "Collection" IS NOT NULL
        ORDER BY "Collection", "Title"
    """).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dataset_name", "collection_name"])
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Generate collection stats JSON and CSV")
    parser.add_argument("--db", default=str(DB_PATH), help="DuckDB database path")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(args.db, read_only=True)

    stats = build_collection_stats(conn)
    json_path = out_dir / "collection_stats.json"
    write_json(stats, json_path)
    print(f"JSON written: {json_path}  ({stats['total_collections']} collections, {stats['total_datasets_in_collections']} datasets)")

    csv_path = out_dir / "collection_datasets.csv"
    write_csv(conn, csv_path)
    print(f"CSV  written: {csv_path}")

    conn.close()


if __name__ == "__main__":
    main()