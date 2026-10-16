"""
Fill dublin_core_remaining."Subject[keyword_fullform]" with the full forms of the
abbreviations used in a row's keywords.

Source of the full forms: the "abbreviations" sheet of the 2nd-lot keyword
workbook, exported to csv (abbreviation, full form, optional note). Both keyword
columns are read, Subject[keyword] first and then Subject[sponsored_keyword], and
each abbreviation found is listed once, in order of first appearance:

    BE: Budget Estimates; UDISE: Unified District Information System for Education

Matching rules:
  * A keyword counts only when the WHOLE keyword is the abbreviation ("pmay-u" is
    its own entry; "pmay-u" does not also trigger "pmay"). Keywords are split the
    way import_keyword_files.py splits them: on ';' if the cell has one, else ','.
  * Case-insensitive, because the keywords mix forms ("NRDWP" / "nrdwp"), except
    where the abbreviation sheet's note forbids it: lowercase "oil" is the
    ordinary word, so only "OIL" expands (CASE_SENSITIVE below).
  * Rows with no abbreviation get NULL.

The column is created if missing (appended to the table; the export decides where
it sits in the sheet). The write is one transaction: the column is recomputed for
every row, so re-running gives the same result. No snapshot, per the user.

Usage:
  python add_keyword_fullforms.py --dry-run
  python add_keyword_fullforms.py
"""
import argparse
import csv
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
ABBREVIATIONS_CSV = str(Path.home() / "Downloads" / "sponsored_keywords_2nd lot.xlsx - abbreviations.csv")

TABLE = "dublin_core_remaining"
COLUMN = "Subject[keyword_fullform]"
SOURCES = ["Subject[keyword]", "Subject[sponsored_keyword]"]

# The sheet's note on OIL: do not expand ordinary lowercase "oil".
CASE_SENSITIVE = {"OIL"}


def load_abbreviations(path: str) -> dict[str, tuple[str, str]]:
    """lowercased abbreviation -> (abbreviation as written, full form)."""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                continue
            abbr, full = row[0].strip(), row[1].strip()
            if abbr.lower() in out:
                raise SystemExit(f"duplicate abbreviation {abbr!r} in {path}")
            out[abbr.lower()] = (abbr, full)
    return out


def split_keywords(cell: str | None) -> list[str]:
    if not cell:
        return []
    parts = cell.split(";") if ";" in cell else cell.split(",")
    return [p.strip() for p in parts if p.strip()]


def fullforms(cells: list, abbreviations: dict) -> tuple[str | None, list[str]]:
    found: dict[str, str] = {}
    for cell in cells:
        for kw in split_keywords(cell):
            hit = abbreviations.get(kw.lower())
            if not hit or (hit[0] in CASE_SENSITIVE and kw != hit[0]):
                continue
            found.setdefault(hit[0], hit[1])
    return ("; ".join(f"{a}: {f}" for a, f in found.items()) or None), list(found)


def main(dry_run: bool, csv_path: str) -> None:
    abbreviations = load_abbreviations(csv_path)
    print(f"{len(abbreviations)} abbreviations from {csv_path}")

    con = duckdb.connect(DB_PATH, read_only=dry_run)
    try:
        src = ", ".join(f'"{c}"' for c in SOURCES)
        df = con.execute(f'SELECT nid, {src} FROM "{TABLE}"').fetchdf()
        if df["nid"].duplicated().any() or df["nid"].isna().any():
            raise SystemExit("nid is not unique/non-null; cannot join the update on it")

        values, used = [], Counter()
        for cells in df[SOURCES].itertuples(index=False):
            text, found = fullforms(list(cells), abbreviations)
            values.append(text)
            used.update(found)
        df[COLUMN] = values
        filled = int(df[COLUMN].notna().sum())
        print(f"{filled} of {len(df)} rows get a full form; "
              f"{len(used)} of {len(abbreviations)} abbreviations are used")
        print("most used:", used.most_common(8))
        print("unused:", sorted(set(a for a, _ in abbreviations.values()) - set(used)))
        print("sample:", [v for v in values if v][:2])
        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        con.register("ff", df[["nid", COLUMN]])
        con.execute("BEGIN")
        try:
            n_before = con.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0]
            cols_before = [r[1] for r in con.execute(f'PRAGMA table_info("{TABLE}")').fetchall()]
            if COLUMN not in cols_before:
                con.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN "{COLUMN}" VARCHAR')
            con.execute(f'''UPDATE "{TABLE}" AS d SET "{COLUMN}" = f."{COLUMN}"
                            FROM ff f WHERE d.nid = f.nid''')
            got = con.execute(
                f'SELECT count(*) FROM "{TABLE}" WHERE "{COLUMN}" IS NOT NULL').fetchone()[0]
            assert got == filled, (got, filled)
            assert con.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()[0] == n_before
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        print(f'\n"{COLUMN}" written on {got} rows of {n_before}.')
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--abbreviations", default=ABBREVIATIONS_CSV)
    args = ap.parse_args()
    main(args.dry_run, args.abbreviations)
