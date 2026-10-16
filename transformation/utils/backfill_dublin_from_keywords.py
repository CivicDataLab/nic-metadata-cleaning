"""
Backfill dublin_core_metadata rows that the collection updater missed.

update_dublin_metadata_collection.py only covers nids present in
llm_collection_results (the collection classifier). The non-mergeable / standalone
datasets were classified into llm_keyword_results instead, so their generated
fields never landed in dublin_core_metadata (their `new_title` is still blank).

This script fills ONLY those blank-`new_title` rows from llm_keyword_results,
using the SAME column mapping as the collection updater so the whole table stays
consistent:

  llm_keyword_results           → dublin_core_metadata
  ─────────────────────────────────────────────────────
  generated_title               → new_title           (original Title preserved)
  generated_description         → Description
  generated_note                → Note
  generated_alt_title           → Alternative Title
  generated_short_description   → Abstract
  generated_theme               → Subject[sector]

Deliberately NOT touched:
  - Title (kept; generated title goes to new_title, matching the collection run)
  - Subject[keyword] / Subject[sponsored_keyword] (already assigned deterministically;
    generated_keywords is empty for these rows under the keyword-free prompt)
  - License / Language / Relation[Access URL] (global concerns, handled elsewhere)

Every field is empty-guarded: a blank generated value never overwrites an existing
dublin value (generated_note is empty for most rows and would otherwise wipe Notes).

Usage:
  python backfill_dublin_from_keywords.py --dry-run   # counts only
  python backfill_dublin_from_keywords.py             # snapshot + write
"""
import argparse
import os
import time
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"

# llm_keyword_results column → dublin_core_metadata column (collection-style)
LLM_TO_DUBLIN = {
    "generated_title":             "new_title",
    "generated_description":       "Description",
    "generated_note":              "Note",
    "generated_alt_title":         "Alternative Title",
    "generated_short_description": "Abstract",
    "generated_theme":             "Subject[sector]",
}

# Only fill rows the collection updater never touched.
SCOPE = "(d.new_title IS NULL OR d.new_title = '')"

LLM_DEDUP = """
    SELECT * FROM llm_keyword_results
    QUALIFY ROW_NUMBER() OVER (PARTITION BY nid ORDER BY rowid DESC) = 1
"""


def build_guarded_set_clause() -> str:
    """Only overwrite when the generated value is non-empty (never blank an existing)."""
    parts = []
    for llm_col, dc_col in LLM_TO_DUBLIN.items():
        parts.append(
            f'"{dc_col}" = CASE WHEN NULLIF(l."{llm_col}", \'\') IS NOT NULL '
            f'THEN l."{llm_col}" ELSE d."{dc_col}" END'
        )
    return ",\n            ".join(parts)


def main(dry_run: bool = False, table: str = "dublin_core_metadata") -> None:
    con = duckdb.connect(DB_PATH)
    tbl = f'"{table}"'
    try:
        has_new_title = con.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = 'new_title'", [table],
        ).fetchone()[0]
        if not has_new_title:
            raise SystemExit(
                f"{table} has no `new_title` column — it is both the destination of "
                f"generated_title and the SCOPE predicate. Add it first:\n"
                f'  ALTER TABLE "{table}" ADD COLUMN new_title VARCHAR;'
            )

        matched = con.execute(f"""
            SELECT COUNT(*) FROM {tbl} d
            JOIN ({LLM_DEDUP}) l ON CAST(d.nid AS VARCHAR) = l.nid
            WHERE {SCOPE}
        """).fetchone()[0]
        print(f"Scoped rows to backfill (blank new_title, has kw_results source): {matched}")

        # How many existing non-empty values the guards will protect
        prot = con.execute(f"""
            SELECT
              COUNT(*) FILTER (WHERE d."Note" IS NOT NULL AND d."Note" <> ''
                               AND NULLIF(l.generated_note,'') IS NULL) AS notes_kept,
              COUNT(*) FILTER (WHERE d."Description" IS NOT NULL AND d."Description" <> ''
                               AND NULLIF(l.generated_description,'') IS NULL) AS desc_kept
            FROM {tbl} d JOIN ({LLM_DEDUP}) l ON CAST(d.nid AS VARCHAR)=l.nid
            WHERE {SCOPE}
        """).fetchone()
        print(f"Empty-guard will preserve existing: {prot[0]} Note(s), {prot[1]} Description(s)")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # ── Snapshot target columns for scoped rows (reversibility) ──
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = os.path.join(os.path.dirname(__file__), f"backfill_snapshot_{table}_{ts}.csv")
        target_cols = ", ".join(f'd."{c}"' for c in LLM_TO_DUBLIN.values())
        con.execute(f"""
            COPY (
              SELECT d.nid, {target_cols}
              FROM {tbl} d
              JOIN ({LLM_DEDUP}) l ON CAST(d.nid AS VARCHAR) = l.nid
              WHERE {SCOPE}
            ) TO '{snap}' (HEADER, DELIMITER ',')
        """)
        print(f"Snapshot of pre-update values → {snap}")

        # ── Guarded UPDATE ──
        con.execute(f"""
        UPDATE {tbl} AS d
        SET
            {build_guarded_set_clause()}
        FROM ({LLM_DEDUP}) AS l
        WHERE CAST(d.nid AS VARCHAR) = l.nid AND {SCOPE}
        """)
        print("Backfill applied.")

        # ── Verify ──
        still_blank = con.execute(f"""
            SELECT COUNT(*) FROM {tbl} d
            JOIN ({LLM_DEDUP}) l ON CAST(d.nid AS VARCHAR) = l.nid
            WHERE (d.new_title IS NULL OR d.new_title = '')
        """).fetchone()[0]
        print(f"Scoped rows still blank new_title after update: {still_blank} (expect 0)")

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill dublin_core_metadata from llm_keyword_results (blank new_title rows).")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing.")
    parser.add_argument("--table", default="dublin_core_metadata",
                        help="Target dublin table (default: dublin_core_metadata). "
                             "Use dublin_core_remaining for the remaining-raw-datasets corpus.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, table=args.table)
