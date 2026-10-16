"""
Update dublin_core_metadata table with values from llm_collection_results.

This is the collection-classifier counterpart to update_dublin_metadata.py.
The generated title is written to a NEW column `new_title` (the original Title
is left untouched); the remaining generated fields map onto existing columns.

Mapping:
  llm_collection_results           → dublin_core_metadata
  ─────────────────────────────────────────────────────────
  generated_title                  → new_title            (NEW column)
  generated_description            → Description
  generated_note                   → Note
  generated_alt_title              → Alternative Title
  generated_short_description      → Abstract
  generated_theme                  → Subject[sector]

Usage:
  python update_dublin_metadata_collection.py
  python update_dublin_metadata_collection.py --dry-run   # preview counts only
  python update_dublin_metadata_collection.py --batch N   # only rows from batch N
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

# Mapping: llm_collection_results column → dublin_core_metadata column.
# generated_title goes to the new `new_title` column; the rest already exist.
LLM_TO_DUBLIN = {
    "generated_title":             "new_title",
    "generated_description":       "Description",
    "generated_note":              "Note",
    "generated_alt_title":         "Alternative Title",
    "generated_short_description": "Abstract",
    "generated_theme":             "Subject[sector]",
}


def build_set_clause(alias: str, mapping: dict) -> str:
    parts = []
    for llm_col, dc_col in mapping.items():
        # DuckDB requires quoting column names that contain brackets or spaces
        parts.append(f'"{dc_col}" = {alias}."{llm_col}"')
    return ",\n        ".join(parts)


def main(dry_run: bool = False, batch: int | None = None) -> None:
    con = duckdb.connect(DB_PATH)

    batch_filter = ""
    if batch is not None:
        batch_filter = f" AND CAST(d.batch AS INTEGER) = {batch}"
        print(f"Filtering to batch: {batch}")

    # Dedupe llm_collection_results by nid, keeping the latest-inserted row
    # (highest rowid wins). Reused by both the match-count query and the UPDATE
    # so the two stay consistent.
    llm_dedup_sql = """
        SELECT * FROM llm_collection_results
        QUALIFY ROW_NUMBER() OVER (PARTITION BY nid ORDER BY rowid DESC) = 1
    """

    try:
        llm_count = con.execute("SELECT COUNT(*) FROM llm_collection_results").fetchone()[0]
        llm_unique = con.execute(f"SELECT COUNT(*) FROM ({llm_dedup_sql})").fetchone()[0]
        dc_count  = con.execute("SELECT COUNT(*) FROM dublin_core_metadata").fetchone()[0]
        print(f"llm_collection_results rows : {llm_count} ({llm_unique} unique nids after dedup)")
        print(f"dublin_core_metadata rows   : {dc_count}")

        matched = con.execute(f"""
            SELECT COUNT(*)
            FROM dublin_core_metadata d
            JOIN ({llm_dedup_sql}) l ON CAST(d.nid AS VARCHAR) = l.nid
            WHERE 1=1{batch_filter}
        """).fetchone()[0]
        print(f"Matched on nid              : {matched}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # ── 0. Ensure new column exists ──────────────────────────────────────
        existing_cols = {row[0] for row in con.execute("DESCRIBE dublin_core_metadata").fetchall()}
        if "new_title" not in existing_cols:
            con.execute('ALTER TABLE dublin_core_metadata ADD COLUMN "new_title" VARCHAR')
            print("Added column: new_title")

        # ── 1. Update generated fields ───────────────────────────────────────
        set_clause = build_set_clause("l", LLM_TO_DUBLIN)
        update_sql = f"""
        UPDATE dublin_core_metadata AS d
        SET
            {set_clause}
        FROM ({llm_dedup_sql}) AS l
        WHERE CAST(d.nid AS VARCHAR) = l.nid{batch_filter}
        """
        con.execute(update_sql)
        print("\nGenerated fields updated.")

        # ── 2. Verify ────────────────────────────────────────────────────────
        updated = con.execute(f"""
            SELECT COUNT(*) FROM dublin_core_metadata d
            JOIN ({llm_dedup_sql}) l ON CAST(d.nid AS VARCHAR) = l.nid
            WHERE d.new_title IS NOT NULL AND d.new_title <> ''{batch_filter}
        """).fetchone()[0]
        print(f"Rows with new_title populated: {updated}")

        sample = con.execute("""
        SELECT nid, "Title", "new_title"
        FROM dublin_core_metadata
        WHERE new_title IS NOT NULL AND new_title <> ''
        LIMIT 3
        """).fetchdf()
        print("\nSample rows after update:")
        print(sample.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update dublin_core_metadata from llm_collection_results.")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing changes.")
    parser.add_argument("--batch", type=int, default=None,
                        help="Update only rows from this batch number.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, batch=args.batch)
