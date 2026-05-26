"""
Flag exact-duplicate datasets for archival in dublin_core_metadata.

Source of truth: dataset_relations.csv (source_nid → target_nid pairs with a
family_type). For every row whose family_type is EXACT_DUPLICATE, the
target_nid is treated as the duplicate copy and gets flagged:

  archive        → TRUE
  archive_reason → 'duplicate'

The source_nid is the kept original and is left untouched.

Usage:
  python flag_duplicate_archives.py
  python flag_duplicate_archives.py --dry-run          # preview counts only
  python flag_duplicate_archives.py --csv /path/to/dataset_relations.csv
"""

import argparse
import duckdb

DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
DEFAULT_CSV = "/home/aakash/NIC/dataset_relations.csv"

FAMILY_TYPE = "EXACT_DUPLICATE"
ARCHIVE_REASON = "duplicate"


def main(csv_path: str = DEFAULT_CSV, dry_run: bool = False) -> None:
    con = duckdb.connect(DB_PATH)

    # Read the relations CSV with the proper CSV parser so commas inside
    # quoted titles don't break field splitting.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW rel AS
        SELECT * FROM read_csv_auto('{csv_path}', header=true)
    """)

    try:
        # ── Reporting on the CSV side ────────────────────────────────────────
        total_rows = con.execute(
            "SELECT COUNT(*) FROM rel WHERE family_type = ?", [FAMILY_TYPE]
        ).fetchone()[0]
        unique_targets = con.execute(
            "SELECT COUNT(DISTINCT target_nid) FROM rel WHERE family_type = ?",
            [FAMILY_TYPE],
        ).fetchone()[0]
        print(f"EXACT_DUPLICATE rows in CSV   : {total_rows}")
        print(f"Unique target_nids to flag    : {unique_targets}")

        if total_rows != unique_targets:
            print(f"  (note: {total_rows - unique_targets} target(s) pointed to by "
                  f"more than one source — flagged once, harmless)")

        # nids that appear as both a source (kept) and a target (archived).
        # Under the rule "flag targets", these end up archived; surfaced here
        # so a human can eyeball the chain cases.
        both = con.execute(f"""
            SELECT DISTINCT t.target_nid
            FROM rel t
            JOIN rel s ON t.target_nid = s.source_nid
            WHERE t.family_type = '{FAMILY_TYPE}'
              AND s.family_type = '{FAMILY_TYPE}'
            ORDER BY t.target_nid
        """).fetchall()
        if both:
            ids = ", ".join(str(r[0]) for r in both)
            print(f"nids that are both source & target ({len(both)}): {ids}")
            print("  -> these are archived as targets (kept original is upstream in the chain)")

        # ── Reporting on the DB side ─────────────────────────────────────────
        target_filter = f"""
            CAST(nid AS VARCHAR) IN (
                SELECT DISTINCT CAST(target_nid AS VARCHAR)
                FROM rel WHERE family_type = '{FAMILY_TYPE}'
            )
        """
        matched = con.execute(
            f"SELECT COUNT(*) FROM dublin_core_metadata WHERE {target_filter}"
        ).fetchone()[0]
        already = con.execute(
            f"SELECT COUNT(*) FROM dublin_core_metadata WHERE {target_filter} AND archive = TRUE"
        ).fetchone()[0]
        print(f"Target rows found in DB       : {matched}")
        print(f"Already archived              : {already}")
        print(f"Will be flipped to archived   : {matched - already}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        # ── Ensure archive_reason column exists ──────────────────────────────
        existing_cols = {row[0] for row in con.execute("DESCRIBE dublin_core_metadata").fetchall()}
        if "archive_reason" not in existing_cols:
            con.execute('ALTER TABLE dublin_core_metadata ADD COLUMN archive_reason VARCHAR')
            print("\nAdded column: archive_reason")

        # ── Flag the targets ─────────────────────────────────────────────────
        con.execute(f"""
            UPDATE dublin_core_metadata
            SET archive = TRUE,
                archive_reason = '{ARCHIVE_REASON}'
            WHERE {target_filter}
        """)
        print(f"\nFlagged {matched} dataset(s): archive=TRUE, archive_reason='{ARCHIVE_REASON}'.")

        # ── Verify ───────────────────────────────────────────────────────────
        flagged_total = con.execute(
            "SELECT COUNT(*) FROM dublin_core_metadata WHERE archive_reason = ?",
            [ARCHIVE_REASON],
        ).fetchone()[0]
        print(f"Total rows with archive_reason='{ARCHIVE_REASON}': {flagged_total}")

        sample = con.execute(f"""
            SELECT nid, "Title", archive, archive_reason
            FROM dublin_core_metadata
            WHERE {target_filter}
            LIMIT 5
        """).fetchdf()
        print("\nSample flagged rows:")
        print(sample.to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flag EXACT_DUPLICATE target datasets as archived in dublin_core_metadata."
    )
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to dataset_relations.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing.")
    args = parser.parse_args()
    main(csv_path=args.csv, dry_run=args.dry_run)
