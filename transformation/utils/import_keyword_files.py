"""
Import per-ministry keyword workbooks into Subject[keyword], joined on nid.

The keyword deliverables arrive as a zip (or folder) of one .xlsx per ministry,
each sharing the layout:

    nid | New title | New Description | Note | Alt_title | Abstract | sector
        | generated_keywords | generated_sponsored_keywords | matched_* | status | error

Only `generated_keywords` is imported, into "Subject[keyword]". The other
generated columns are read and reported but never written -- swapping titles,
descriptions or abstracts is a separate decision (see the --overrides path in
export_dublin_metadata.py for how that was handled for dublin_core_metadata).

Separator handling. The source is not internally consistent: most rows separate
keywords with ';', some use ',', a few use ';' with no following space, and at
least one row uses ';' as the separator while a keyword itself contains a comma
("...; cepi;AQI,NAMP"). So the split is per row, not global:
    row contains ';'  -> split on ';' only   (a comma is then part of a keyword)
    row has no ';'    -> split on ','
Keywords are trimmed, blanks dropped, duplicates removed keeping first order,
then joined with ", " -- the convention dublin_core_metadata already uses for
this column (206,942 rows, zero semicolons), which build_dcat_mapping.py exposes
as dcat:keyword.

nids come out of Excel as floats in some files ("88904.0"), so a trailing ".0"
is stripped before the join.

Only rows matching the table on nid are written; everything else is left alone.
Idempotent: re-running rewrites the same values.

Usage:
  python import_keyword_files.py --src "keyword final list-*.zip" --dry-run
  python import_keyword_files.py --src /path/to/folder
"""

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import duckdb
from python_calamine import CalamineWorkbook

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
COLUMN = "Subject[keyword]"
KEY_COL = "generated_keywords"
JOIN = ", "


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v).strip()


def parse_keywords(raw: str) -> str:
    """Normalise one cell of keywords to the table's ', ' convention."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    parts = raw.split(";") if ";" in raw else raw.split(",")
    out, seen = [], set()
    for p in parts:
        k = p.strip().strip(",").strip()
        if not k:
            continue
        low = k.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(k)
    return JOIN.join(out)


def read_source(src: Path):
    """Return (rows, skipped_sheets). rows = [(file, nid, keywords_raw, status)]."""
    rows, skipped = [], []
    for f in sorted(src.rglob("*.xlsx")):
        if f.name.startswith("~$"):
            continue
        wb = CalamineWorkbook.from_path(str(f))
        for sheet in wb.sheet_names:
            data = wb.get_sheet_by_name(sheet).to_python(skip_empty_area=False)
            if not data:
                continue
            hdr = [_cell(c) for c in data[0]]
            if "nid" not in hdr or KEY_COL not in hdr:
                skipped.append((f"{f.parent.name}/{f.name}", sheet, hdr[:4]))
                continue
            i_nid, i_kw = hdr.index("nid"), hdr.index(KEY_COL)
            i_st = hdr.index("status") if "status" in hdr else None
            for r in data[1:]:
                nid = _cell(r[i_nid]) if i_nid < len(r) else ""
                if not nid:
                    continue
                nid = re.sub(r"\.0+$", "", nid)
                kw = _cell(r[i_kw]) if i_kw < len(r) else ""
                st = _cell(r[i_st]) if i_st is not None and i_st < len(r) else ""
                rows.append((f.name, nid, kw, st))
    return rows, skipped


def main(src_arg, db_path, table, column, dry_run):
    src = Path(src_arg)
    tmp = None
    if src.is_file() and src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="kwimport_"))
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp)
        src = tmp
    if not src.is_dir():
        raise SystemExit(f"Not a folder or zip: {src_arg}")

    try:
        rows, skipped = read_source(src)
        print(f"workbooks read from {src_arg}")
        print(f"  rows with an nid and {KEY_COL} : {len(rows)}")
        for name, sheet, hdr in skipped:
            print(f"  SKIPPED (no nid/{KEY_COL}): {name} [{sheet}] header={hdr}")

        statuses = Counter(s for _, _, _, s in rows)
        if set(statuses) - {"success", ""}:
            print(f"  status values: {dict(statuses)}")

        mixed = sum(1 for _, _, kw, _ in rows if ";" in kw and "," in kw)
        comma_only = sum(1 for _, _, kw, _ in rows if ";" not in kw and "," in kw)
        empty = sum(1 for _, _, kw, _ in rows if not kw.strip())
        print(f"  separator: ';' rows {sum(1 for _, _, kw, _ in rows if ';' in kw)}"
              f" | ',' only {comma_only} | both (kept ';') {mixed} | empty {empty}")

        parsed = {}
        for _, nid, kw, _ in rows:
            v = parse_keywords(kw)
            if v:
                parsed[nid] = v          # last file wins; nids are unique in practice
        print(f"  distinct nids with keywords : {len(parsed)}")

        con = duckdb.connect(db_path, read_only=dry_run)
        try:
            con.execute("DROP TABLE IF EXISTS _kw")
            con.execute("CREATE TEMP TABLE _kw(nid VARCHAR, kw VARCHAR)")
            con.executemany("INSERT INTO _kw VALUES (?,?)", list(parsed.items()))

            matched = con.execute(
                f"SELECT COUNT(*) FROM _kw k JOIN {table} d USING(nid)").fetchone()[0]
            print(f"\n  nids matching {table} : {matched}")
            print(f"  nids not in the table          : {len(parsed) - matched}")
            before = con.execute(
                f'SELECT COUNT("{column}") FROM {table}').fetchone()[0]
            print(f'  rows already carrying {column} : {before}')

            print(f"\ncoverage of {table} after this import:")
            for mm, tot, cov in con.execute(f"""
                SELECT COALESCE(merge_method, '(null)'), COUNT(*),
                       COUNT(*) FILTER (WHERE d.nid IN (SELECT nid FROM _kw))
                FROM {table} d GROUP BY 1 ORDER BY 2 DESC
            """).fetchall():
                print(f"  {mm:<18} {cov:>7} / {tot:<7} ({100 * cov / tot:5.1f}%)")

            ambiguous = con.execute(
                "SELECT COUNT(*) FROM _kw WHERE kw LIKE '%,%,%' AND kw NOT LIKE '%, %'"
            ).fetchone()[0]
            if ambiguous:
                print(f"  WARNING: {ambiguous} value(s) may re-parse ambiguously")

            if dry_run:
                print("\n[dry-run] No changes written.")
                print(con.execute("SELECT nid, kw FROM _kw LIMIT 5").fetchdf().to_string())
                return

            con.execute(f"""
                UPDATE {table} AS d SET "{column}" = k.kw
                FROM _kw k WHERE d.nid = k.nid
            """)
            after = con.execute(f'SELECT COUNT("{column}") FROM {table}').fetchone()[0]
            print(f"\nWritten. {column} non-null: {before} -> {after}")
            print("  rows still without keywords :",
                  con.execute(f'SELECT COUNT(*) FROM {table} WHERE "{column}" IS NULL'
                              ).fetchone()[0])
            print("  distinct keywords in table  :",
                  con.execute(f"""SELECT COUNT(DISTINCT trim(k)) FROM (
                      SELECT unnest(string_split("{column}", ',')) AS k
                      FROM {table} WHERE "{column}" IS NOT NULL)""").fetchone()[0])
            con.execute("DROP TABLE IF EXISTS _kw")
        finally:
            con.close()
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Import ministry keyword workbooks on nid.")
    p.add_argument("--src", required=True, help="Zip or folder of *_keywords.xlsx files.")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--table", default=TABLE)
    p.add_argument("--column", default=COLUMN)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    main(a.src, a.db, a.table, a.column, a.dry_run)
