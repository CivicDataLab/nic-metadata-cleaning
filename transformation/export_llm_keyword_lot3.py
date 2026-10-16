"""Export llm_keyword_results_lot3 to .xlsx, with context columns from lot3_raw.

The keyword table holds only nid + the LLM-generated fields, which is not enough
to review a row on its own. title / ministry_department / state_department are
joined in from lot3_raw on nid so each generated value can be judged against the
dataset it describes.

Source of the keyword rows: the local DuckDB table if it has any, otherwise a
Parquet file (--keywords-parquet). The local table is currently empty -- the rows
live in the DuckLake copy -- so fetch them to Parquet first and pass that in.

Join notes, all verified against the data:
  * lot3_raw has one duplicate nid (88731, present in two source CSVs) and one
    null-nid row. The lot3_raw side is collapsed with GROUP BY nid so the join
    cannot fan out; the duplicate's two rows agree on all three joined columns,
    so any_value() is not picking between conflicting values.
  * lot3_raw titles carry stray leading/trailing spaces and tabs. They are
    stripped, which makes the title identical to the keyword table's own title
    column on every row -- so that redundant column is dropped rather than
    shipped twice.

Usage:
    python3 export_llm_keyword_lot3.py --keywords-parquet /path/to/kw.parquet
    python3 export_llm_keyword_lot3.py --output /path/to/sheet.xlsx
"""

import argparse
from pathlib import Path

import duckdb
from openpyxl.utils import get_column_letter

TABLE = "llm_keyword_results_lot3"
SOURCE = "lot3_raw"

# Context first, then the generated fields, with the raw llm_response last --
# it is the debugging payload, not something a reviewer reads first.
COLUMN_ORDER = [
    "nid", "title", "ministry_department", "state_department",
    "generated_title", "generated_alt_title", "generated_short_description",
    "generated_description", "generated_note", "generated_theme",
    "llm_response",
]
WIDTHS = {"nid": 10, "title": 60, "ministry_department": 34,
          "state_department": 24, "llm_response": 60}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(Path(__file__).parent / "metadata.db"))
    ap.add_argument("--keywords-parquet", default=None,
                    help="Parquet of the keyword rows, used when the local table is empty")
    ap.add_argument("--output", default=str(
        Path(__file__).parent.parent / f"{TABLE}.xlsx"))
    args = ap.parse_args()

    out = Path(args.output)
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing {out}; pass --output")

    con = duckdb.connect(args.db, read_only=True)
    try:
        local_rows = con.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0]
        if local_rows:
            con.execute(f'CREATE OR REPLACE TEMP VIEW kw AS SELECT * FROM "{TABLE}"')
            origin = f"{TABLE} ({args.db})"
        elif args.keywords_parquet:
            # CREATE VIEW cannot take a prepared parameter, so the path is
            # inlined with its quotes escaped.
            pq = args.keywords_parquet.replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE TEMP VIEW kw AS SELECT * FROM read_parquet('{pq}')")
            origin = args.keywords_parquet
        else:
            raise SystemExit(
                f'"{TABLE}" is empty in {args.db} and no --keywords-parquet given. '
                "Fetch the rows from the DuckLake copy first.")

        n_kw = con.execute("SELECT count(*) FROM kw").fetchone()[0]
        print(f"Keyword rows: {n_kw} from {origin}")

        # GROUP BY collapses the duplicate nid; the whitespace strip makes the
        # lot3_raw title match the keyword table's.
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW ctx AS
            SELECT nid,
                   any_value(regexp_replace(title, '^\\s+|\\s+$', '', 'g')) AS title,
                   any_value(ministry_department) AS ministry_department,
                   any_value(state_department)    AS state_department
            FROM "{SOURCE}" WHERE nid IS NOT NULL GROUP BY nid
        """)

        select_list = ", ".join(
            f'c."{c}"' if c in ("title", "ministry_department", "state_department")
            else f'k."{c}"' for c in COLUMN_ORDER)
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW joined AS
            SELECT {select_list} FROM kw k LEFT JOIN ctx c USING (nid)
        """)

        n_out = con.execute("SELECT count(*) FROM joined").fetchone()[0]
        if n_out != n_kw:
            raise SystemExit(f"join changed the row count: {n_kw} -> {n_out}")
        missing = con.execute(
            "SELECT count(*) FROM joined WHERE title IS NULL").fetchone()[0]
        print(f"Joined {n_out} rows; {missing} with no {SOURCE} match")
        for col in ("ministry_department", "state_department"):
            filled = con.execute(f'SELECT count("{col}") FROM joined').fetchone()[0]
            print(f"  {col}: {filled} populated")

        df = con.execute("SELECT * FROM joined ORDER BY nid").fetchdf()
    finally:
        con.close()

    df.to_excel(out, index=False, sheet_name="llm_keyword_lot3", engine="openpyxl")

    # Freeze the header and widen the columns a reviewer actually reads.
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb.active
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(df.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(col, 30)
    wb.save(out)

    print(f"\n✓ {out}  ({out.stat().st_size / 1e6:.1f} MB, "
          f"{len(df)} rows x {len(df.columns)} cols)")


if __name__ == "__main__":
    main()
