"""Append the ministry_data_with_CDO CSVs to lot3_raw.

These are 419 Central-government datasets (govt_type='Central') delivered as one
CSV per ministry inside ministry_data_with_CDO.zip. Their 36 columns match
lot3_raw's exactly, so they land as additional rows rather than a new table.

Load choices mirror the original Lot 3 import, so the table stays uniform:
all columns VARCHAR (no type inference), nullstr=['NULL',''] because these
data.gov.in exports use the literal string NULL as their null marker, and
source_file records the originating CSV basename.

Two source quirks are handled here:
  * 4 of the 22 files misspell the cdo_email header as "cdo_eamil". The two
    spellings are coalesced into cdo_email; no row populates both.
  * "Ministry of Personnel, Public Grievances and Pensions.csv" ends with an
    all-empty row, as Tamilnadu_resources.csv did in the original import. It is
    dropped.

Re-running is refused if any of the incoming source_file values are already in
lot3_raw, so a repeat invocation cannot silently double the rows.

Usage:
    python3 append_lot3_ministry_cdo.py [--zip PATH] [--db PATH] [--dry-run]
"""

import argparse
import tempfile
import zipfile
from pathlib import Path

import duckdb

DEFAULT_ZIP = Path.home() / "Downloads" / "ministry_data_with_CDO.zip"
TABLE = "lot3_raw"

# union_by_name gives us both header spellings; these are resolved, not stored.
TYPO_COL = "cdo_eamil"
REAL_COL = "cdo_email"


def build_incoming(con: duckdb.DuckDBPyConnection, csv_dir: Path) -> None:
    """Stage the CSVs as a temp table shaped exactly like lot3_raw."""
    target_cols = [
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [TABLE]
        ).fetchall()
    ]

    con.execute(
        """CREATE OR REPLACE TEMP TABLE staged AS
           SELECT * FROM read_csv(?, all_varchar=true, nullstr=['NULL',''],
                                  header=true, union_by_name=true, filename=true)""",
        [str(csv_dir / "*.csv")],
    )
    # DESCRIBE yields (column_name, column_type, ...) -- r[0], not r[1].
    staged_cols = {r[0] for r in con.execute("DESCRIBE staged").fetchall()}

    # Coalesce the misspelled header into the real one. Guard on presence so the
    # script still works against a corrected export.
    if TYPO_COL in staged_cols:
        both = con.execute(
            f'SELECT count(*) FROM staged WHERE "{TYPO_COL}" IS NOT NULL '
            f'AND "{REAL_COL}" IS NOT NULL'
        ).fetchone()[0]
        if both:
            raise SystemExit(
                f"{both} row(s) populate both {TYPO_COL} and {REAL_COL}; "
                "coalescing would silently drop data. Inspect before loading."
            )
        email_expr = f'coalesce("{REAL_COL}", "{TYPO_COL}")'
    else:
        email_expr = f'"{REAL_COL}"'

    select_list = []
    for c in target_cols:
        if c == REAL_COL:
            select_list.append(f'{email_expr} AS "{REAL_COL}"')
        elif c == "source_file":
            select_list.append("regexp_extract(filename, '[^/]+$') AS source_file")
        elif c in staged_cols:
            select_list.append(f'"{c}"')
        else:
            select_list.append(f'CAST(NULL AS VARCHAR) AS "{c}"')

    # The trailing all-empty row carries no identifier; every real row has both.
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE incoming AS SELECT {', '.join(select_list)} "
        "FROM staged WHERE nid IS NOT NULL OR uuid IS NOT NULL"
    )

    # The WHERE above filters `staged`, so a select-list that resolves to NULL
    # still yields the right ROW COUNT -- the count alone cannot tell us the
    # columns actually carried over. Check the identity columns explicitly.
    for col in ("nid", "uuid", "title"):
        filled = con.execute(f'SELECT count("{col}") FROM incoming').fetchone()[0]
        if filled == 0:
            raise SystemExit(
                f"staging produced 0 non-null {col} values -- the select list did "
                f"not resolve against the CSVs. Refusing to insert."
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", default=str(DEFAULT_ZIP), help="ministry_data_with_CDO.zip")
    ap.add_argument("--db", default=str(Path(__file__).parent / "metadata.db"))
    ap.add_argument("--dry-run", action="store_true",
                    help="Stage and report, but do not insert")
    args = ap.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.is_file():
        raise SystemExit(f"zip not found: {zip_path}")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        csv_dirs = {p.parent for p in Path(tmp).rglob("*.csv")}
        if len(csv_dirs) != 1:
            raise SystemExit(f"expected CSVs in one directory, found: {sorted(csv_dirs)}")
        csv_dir = csv_dirs.pop()
        n_files = len(list(csv_dir.glob("*.csv")))

        con = duckdb.connect(args.db, read_only=args.dry_run)
        try:
            before = con.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0]
            build_incoming(con, csv_dir)

            n_in = con.execute("SELECT count(*) FROM incoming").fetchone()[0]
            dropped = con.execute("SELECT count(*) FROM staged").fetchone()[0] - n_in
            print(f"Staged {n_in} rows from {n_files} CSVs in {zip_path.name} "
                  f"({dropped} empty row(s) dropped)")

            clash = con.execute(
                f'SELECT DISTINCT source_file FROM incoming WHERE source_file IN '
                f'(SELECT DISTINCT source_file FROM "{TABLE}")'
            ).fetchall()
            if clash:
                raise SystemExit(
                    f"{TABLE} already contains rows from {[c[0] for c in clash]}. "
                    "Refusing to append; this looks like a re-run."
                )

            for key in ("nid", "uuid"):
                dupes = con.execute(
                    f'SELECT count(*) FROM incoming i '
                    f'WHERE EXISTS (SELECT 1 FROM "{TABLE}" t WHERE t."{key}" = i."{key}")'
                ).fetchone()[0]
                print(f"  existing {TABLE} rows sharing a {key}: {dupes}")

            if args.dry_run:
                print("\n--dry-run: nothing written.")
                return

            con.execute(f'INSERT INTO "{TABLE}" BY NAME SELECT * FROM incoming')
            after = con.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0]
            print(f"\n✓ {TABLE}: {before} -> {after} rows (+{after - before})")
            print(f"  To undo: DELETE FROM \"{TABLE}\" WHERE source_file IN "
                  f"(SELECT DISTINCT source_file FROM incoming);  -- or by the "
                  f"{n_files} CSV basenames")
        finally:
            con.close()


if __name__ == "__main__":
    main()
