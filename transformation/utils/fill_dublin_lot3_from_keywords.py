"""
Fill dublin_core_lot3 from llm_keyword_results_lot3, the way dublin_core_remaining
(lot 2) was filled from llm_keyword_results.

Mapping (the same one backfill_dublin_from_keywords.py uses for lot 2):

  llm_keyword_results_lot3      → dublin_core_lot3
  ─────────────────────────────────────────────────────
  generated_description         → Description
  generated_short_description   → Abstract
  generated_alt_title           → Alternative Title
  generated_note                → Note
  generated_theme               → Subject[sector]

Fixed values applied to every row, as in lot 2:
  License    → https://data.gov.in/government-open-data-license-india
  Language   → en

Deliberately NOT touched:
  - Title. Lot 2 keeps the original Title and puts generated_title in new_title;
    dublin_core_lot3's new_title holds the Collection, else the Title (added
    2026-10-09), so generated_title is not written anywhere.
  - Subject[keyword] (llm_keyword_results_lot3 carries no keywords)
  - Rights Statement / Relation[Access URL] / Creator / Source (empty in lot 2 too)

Every generated field is empty-guarded: a blank generated value never overwrites
an existing dublin value (generated_note is blank for about half the rows and
would otherwise wipe their Notes). The raw sector stays in Subject[sector_resource]
and the raw note in lot3_raw.note.

Source of the keyword rows: the local DuckDB table if it has any, otherwise the
export llm_keyword_results_lot3.xlsx (--keywords-xlsx). The local table is
currently empty -- the rows live in the DuckLake copy.

Join notes: dublin_core_lot3 has one duplicate nid (88731, two identical rows,
both get the same values) and one null-nid row (no keyword row; it only gets
License and Language).

No snapshot is written. Both UPDATEs run in one transaction, with the counts and
a hash of the untouched columns checked before the commit. Idempotent.

Usage:
  python fill_dublin_lot3_from_keywords.py --dry-run   # counts only
  python fill_dublin_lot3_from_keywords.py
"""
import argparse
from pathlib import Path

import duckdb
import pandas as pd
from python_calamine import CalamineWorkbook

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
KEYWORDS_XLSX = str(HERE.parent.parent / "llm_keyword_results_lot3.xlsx")
KEYWORDS_SHEET = "llm_keyword_lot3"

TABLE = "dublin_core_lot3"
SOURCE = "llm_keyword_results_lot3"

GODL_LICENSE = "https://data.gov.in/government-open-data-license-india"
DEFAULT_LANGUAGE = "en"

# llm_keyword_results_lot3 column → dublin_core_lot3 column
LLM_TO_DUBLIN = {
    "generated_description":       "Description",
    "generated_short_description": "Abstract",
    "generated_alt_title":         "Alternative Title",
    "generated_note":              "Note",
    "generated_theme":             "Subject[sector]",
}
FIXED = {"License": GODL_LICENSE, "Language": DEFAULT_LANGUAGE}


def load_keywords(con: duckdb.DuckDBPyConnection, xlsx: str) -> str:
    """Create temp table kw (one row per nid) and return where it came from."""
    cols = ", ".join(f'"{c}"' for c in ["nid", *LLM_TO_DUBLIN])
    if con.execute(f'SELECT count(*) FROM "{SOURCE}"').fetchone()[0]:
        con.execute(f"""
            CREATE TEMP TABLE kw AS
            SELECT {cols} FROM "{SOURCE}"
            QUALIFY ROW_NUMBER() OVER (PARTITION BY nid ORDER BY rowid DESC) = 1
        """)
        return f"table {SOURCE}"

    rows = CalamineWorkbook.from_path(xlsx).get_sheet_by_name(KEYWORDS_SHEET).to_python()
    df = pd.DataFrame(rows[1:], columns=rows[0])[["nid", *LLM_TO_DUBLIN]].astype(str)
    if df["nid"].duplicated().any():
        raise SystemExit(f"duplicate nids in {xlsx}")
    con.register("kw_df", df)
    con.execute(f"CREATE TEMP TABLE kw AS SELECT {cols} FROM kw_df")
    con.unregister("kw_df")
    return xlsx


def build_guarded_set_clause() -> str:
    """Only overwrite when the generated value is non-empty (never blank an existing)."""
    parts = []
    for llm_col, dc_col in LLM_TO_DUBLIN.items():
        parts.append(
            f'"{dc_col}" = CASE WHEN NULLIF(trim(k."{llm_col}"), \'\') IS NOT NULL '
            f'THEN k."{llm_col}" ELSE d."{dc_col}" END'
        )
    return ",\n            ".join(parts)


def filled_counts(con: duckdb.DuckDBPyConnection, cols: list[str]) -> dict[str, int]:
    exprs = ", ".join(
        f'count(*) FILTER (WHERE "{c}" IS NOT NULL AND "{c}" <> \'\')' for c in cols)
    return dict(zip(cols, con.execute(f'SELECT {exprs} FROM "{TABLE}"').fetchone()))


def untouched_hash(con: duckdb.DuckDBPyConnection, cols: list[str]) -> tuple:
    exprs = ", ".join(f'"{c}"' for c in cols)
    return con.execute(f'SELECT count(*), bit_xor(hash({exprs})) FROM "{TABLE}"').fetchone()


def main(dry_run: bool = False, xlsx: str = KEYWORDS_XLSX) -> None:
    con = duckdb.connect(DB_PATH, read_only=dry_run)
    tbl = f'"{TABLE}"'
    targets = [*LLM_TO_DUBLIN.values(), *FIXED]
    try:
        origin = load_keywords(con, xlsx)
        n_kw = con.execute("SELECT count(*) FROM kw").fetchone()[0]
        n_rows = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        matched = con.execute(
            f"SELECT count(*) FROM {tbl} d JOIN kw k ON d.nid = k.nid").fetchone()[0]
        orphans = con.execute(f"""
            SELECT count(*) FROM kw k
            WHERE NOT EXISTS (SELECT 1 FROM {tbl} d WHERE d.nid = k.nid)
        """).fetchone()[0]
        print(f"Keyword rows        : {n_kw} from {origin}")
        print(f"{TABLE} rows: {n_rows}")
        print(f"Matched on nid      : {matched} ({n_rows - matched} without a keyword row, "
              f"{orphans} keyword rows without a dublin row)")

        # What each guarded field will do. LEFT JOIN so a row with no keyword row
        # counts as "existing kept" and the totals cover the whole table.
        print("\nPer field:")
        expected = {}
        for llm_col, dc_col in LLM_TO_DUBLIN.items():
            new, changed, same, kept = con.execute(f"""
                SELECT
                  count(*) FILTER (WHERE gen AND NOT cur),
                  count(*) FILTER (WHERE gen AND cur AND cur_val <> gen_val),
                  count(*) FILTER (WHERE gen AND cur AND cur_val =  gen_val),
                  count(*) FILTER (WHERE NOT gen AND cur)
                FROM (
                  SELECT d."{dc_col}" AS cur_val, k."{llm_col}" AS gen_val,
                         NULLIF(trim(k."{llm_col}"), '') IS NOT NULL AS gen,
                         NULLIF(d."{dc_col}", '') IS NOT NULL        AS cur
                  FROM {tbl} d LEFT JOIN kw k ON d.nid = k.nid
                )
            """).fetchone()
            expected[dc_col] = new + changed + same + kept
            print(f"  {llm_col:28s} → {dc_col:18s} fill blank: {new:6d}  replace: {changed:6d}  "
                  f"already equal: {same:6d}  existing kept (nothing generated): {kept:6d}")

        before = filled_counts(con, targets)
        if dry_run:
            print("\nFilled now:", before)
            print("\n[dry-run] No changes written.")
            return

        untouched = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [TABLE]).fetchall()
            if r[0] not in targets]
        hash_before = untouched_hash(con, untouched)

        con.execute("BEGIN")
        try:
            # ── 1. Guarded LLM-generated fields ──
            con.execute(f"""
            UPDATE {tbl} AS d
            SET
                {build_guarded_set_clause()}
            FROM kw AS k
            WHERE d.nid = k.nid
            """)
            # ── 2. Fixed License and Language, every row ──
            con.execute(
                f'UPDATE {tbl} SET "License" = ?, "Language" = ?',
                [GODL_LICENSE, DEFAULT_LANGUAGE])

            # ── 3. Verify before committing ──
            after = filled_counts(con, targets)
            assert con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0] == n_rows
            assert untouched_hash(con, untouched) == hash_before, "an untouched column changed"
            for dc_col in LLM_TO_DUBLIN.values():
                assert after[dc_col] == expected[dc_col], (dc_col, after[dc_col], expected[dc_col])
            for dc_col, value in FIXED.items():
                assert con.execute(
                    f'SELECT count(*) FROM {tbl} WHERE "{dc_col}" = ?', [value]
                ).fetchone()[0] == n_rows, dc_col
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

        print(f"\n{'column':20s} {'filled before':>14s} {'filled after':>13s}")
        for c in targets:
            print(f"{c:20s} {before[c]:14d} {after[c]:13d}")
        print(f"\nUntouched columns verified unchanged: {len(untouched)}")
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fill dublin_core_lot3 from llm_keyword_results_lot3 (lot 2 mapping).")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without writing.")
    parser.add_argument("--keywords-xlsx", default=KEYWORDS_XLSX,
                        help="Keyword export, used when the local table is empty.")
    args = parser.parse_args()
    main(dry_run=args.dry_run, xlsx=args.keywords_xlsx)
