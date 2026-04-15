"""
Update dublin_core_metadata table with values from llm_keyword_results.

Mapping:
  llm_keyword_results              → dublin_core_metadata
  ─────────────────────────────────────────────────────────
  generated_title                  → Title
  generated_description            → Description
  generated_note                   → Note
  generated_alt_title              → Alternative Title
  generated_short_description      → Abstract
  generated_keywords               → Subject[keyword]
  generated_theme                  → Subject[sector]

Fixed values applied to all rows:
  License    → https://data.gov.in/government-open-data-license-india
  Language   → en
  Depiction  → (left empty / unchanged)
  Relation[Access URL] → same as Identifier[landing_page]

Usage:
  python update_dublin_metadata.py
  python update_dublin_metadata.py --dry-run   # preview counts only
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

GODL_LICENSE = "https://data.gov.in/government-open-data-license-india"
DEFAULT_LANGUAGE = "en"

# Mapping: llm_keyword_results column → dublin_core_metadata column
LLM_TO_DUBLIN = {
    "generated_title":             "Title",
    "generated_description":       "Description",
    "generated_note":              "Note",
    "generated_alt_title":         "Alternative Title",
    "generated_short_description": "Abstract",
    "generated_keywords":          "Subject[keyword]",
    "generated_sponsored_keywords": "Subject[sponsored_keyword]",
    "generated_theme":             "Subject[sector]",
}


def build_set_clause(alias: str, mapping: dict) -> str:
    parts = []
    for llm_col, dc_col in mapping.items():
        # DuckDB requires quoting column names that contain brackets or spaces
        parts.append(f'"{dc_col}" = {alias}."{llm_col}"')
    return ",\n        ".join(parts)


def main(dry_run: bool = False) -> None:
    con = duckdb.connect(DB_PATH)

    try:
        llm_count = con.execute("SELECT COUNT(*) FROM llm_keyword_results").fetchone()[0]
        dc_count  = con.execute("SELECT COUNT(*) FROM dublin_core_metadata").fetchone()[0]
        print(f"llm_keyword_results rows : {llm_count}")
        print(f"dublin_core_metadata rows: {dc_count}")

        matched = con.execute("""
            SELECT COUNT(*)
            FROM dublin_core_metadata d
            JOIN llm_keyword_results l ON CAST(d.nid AS VARCHAR) = l.nid
        """).fetchone()[0]
        print(f"Matched on nid           : {matched}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # ── 0. Ensure new column exists ──────────────────────────────────────
        existing_cols = {row[0] for row in con.execute("DESCRIBE dublin_core_metadata").fetchall()}
        if "Subject[sponsored_keyword]" not in existing_cols:
            con.execute('ALTER TABLE dublin_core_metadata ADD COLUMN "Subject[sponsored_keyword]" VARCHAR')
            print("Added column: Subject[sponsored_keyword]")

        # ── 1. Update LLM-generated fields ──────────────────────────────────
        set_clause = build_set_clause("l", LLM_TO_DUBLIN)
        update_llm_sql = f"""
        UPDATE dublin_core_metadata AS d
        SET
            {set_clause}
        FROM llm_keyword_results AS l
        WHERE CAST(d.nid AS VARCHAR) = l.nid
        """
        con.execute(update_llm_sql)
        print("\nLLM-generated fields updated.")

        # ── 2. Set fixed License and Language for all rows ───────────────────
        con.execute("""
        UPDATE dublin_core_metadata
        SET
            "License"  = ?,
            "Language" = ?
        """, [GODL_LICENSE, DEFAULT_LANGUAGE])
        print(f"License set to : {GODL_LICENSE}")
        print(f"Language set to: {DEFAULT_LANGUAGE}")

        # ── 3. Set Relation[Access URL] = Identifier[landing_page] ──────────
        con.execute("""
        UPDATE dublin_core_metadata
        SET "Relation[Access URL]" = "Identifier[landing_page]"
        WHERE "Identifier[landing_page]" IS NOT NULL
          AND "Identifier[landing_page]" <> ''
        """)
        print("Relation[Access URL] synced from Identifier[landing_page].")

        # ── 4. Verify ────────────────────────────────────────────────────────
        sample = con.execute("""
        SELECT nid, "Title", "License", "Language", "Relation[Access URL]"
        FROM dublin_core_metadata
        LIMIT 3
        """).fetchdf()
        print("\nSample rows after update:")
        print(sample.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update dublin_core_metadata from llm_keyword_results.")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing changes.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

