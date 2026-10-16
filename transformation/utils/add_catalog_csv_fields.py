"""
Add the catalog fields the raw catalog tables are missing, from two
data.gov.in exports, matched by nid.

  catalog_metadata.csv        -> group_name, field_search_keywords,
                                 field_state_department:name
  catalog_state_metadata.csv  -> govt_type, state_department  (State catalogs only)

Both raw catalog tables get the same five columns: catalog_metadata (lot 1) and
remaining_catalog (lot 2). Columns the tables already have are left alone.

group_name and field_search_keywords are NOT row-aligned in catalog_metadata.csv
as exported on 2026-10-07: the rows are in published_date order but those two
columns are in nid-descending order, so the value on file row i belongs to the
catalog with the i-th largest nid. --group-order nid-desc (the default) undoes
that; pass --group-order row for an export that has it fixed. The run stops if
the chosen order explains the group names worse than the other one.

Values are trimmed; blanks and literal 'NULL' strings become SQL NULL.

Idempotent and re-runnable.

Usage:
  python add_catalog_csv_fields.py CATALOG_CSV STATE_CSV --dry-run   # counts, no write
  python add_catalog_csv_fields.py CATALOG_CSV STATE_CSV             # apply
"""

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")

# table -> its name for the state-department column (lot 1 uses underscore names)
TABLES = {
    "catalog_metadata": "field_state_department_name",
    "remaining_catalog": "field_state_department:name",
}
NID_ORDERED = ["group_name", "field_search_keywords"]
NEW_COLS = ["field_state_department", *NID_ORDERED, "govt_type", "state_department"]


def read_export(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    df["nid"] = df["nid"].str.strip()
    dupes = int(df["nid"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{path}: {dupes} duplicated nids")
    return df


def words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]{4,}", text.lower()))


def overlap(groups, texts) -> float:
    """Share of named groups that share a word with the catalog's own text."""
    named = [(g, t) for g, t in zip(groups, texts) if g.strip() not in ("", "NULL")]
    return sum(bool(words(g) & words(t)) for g, t in named) / max(len(named), 1)


def align_groups(main: pd.DataFrame, group_order: str) -> pd.DataFrame:
    """Put group_name / field_search_keywords on the nid they belong to."""
    by_nid = main["nid"].astype("int64").sort_values(ascending=False).index
    text = main["title"] + " " + main["body:value"] + " " + main["keywords"]
    scores = {
        "row": overlap(main["group_name"], text),
        "nid-desc": overlap(main["group_name"], text.loc[by_nid]),
    }
    print("group_name matches its catalog's text: "
          + ", ".join(f"{k} order {v:.1%}" for k, v in scores.items()))
    other = "row" if group_order == "nid-desc" else "nid-desc"
    if scores[group_order] < scores[other]:
        raise SystemExit(f"--group-order {group_order} fits worse than {other}; "
                         f"check the export or pass --group-order {other}")
    if group_order == "row":
        return main
    aligned = main.loc[by_nid, ["nid"]].reset_index(drop=True)
    for col in NID_ORDERED:
        aligned[col] = main[col].to_numpy()  # file row i -> i-th largest nid
    moved = int((aligned["group_name"].to_numpy()
                 != main.loc[by_nid, "group_name"].to_numpy()).sum())
    print(f"Realigned {', '.join(NID_ORDERED)} by nid: group changes on {moved} "
          f"of {len(main)} catalogs")
    return main.drop(columns=NID_ORDERED).merge(aligned, on="nid")


def main(catalog_csv: str, state_csv: str, group_order: str, dry_run: bool) -> None:
    cat = align_groups(read_export(catalog_csv), group_order)
    state = read_export(state_csv)
    print(f"{Path(catalog_csv).name}: {len(cat)} catalogs; "
          f"{Path(state_csv).name}: {len(state)} catalogs")

    con = duckdb.connect(DB_PATH, read_only=dry_run)
    con.register("cat_df", cat)
    con.register("state_df", state)
    orphans = con.execute(
        "SELECT count(*) FROM state_df WHERE nid NOT IN (SELECT nid FROM cat_df)").fetchone()[0]
    if orphans:
        print(f"WARNING: {orphans} nids of {Path(state_csv).name} are not in {Path(catalog_csv).name}")

    null = "nullif(nullif(trim({0}), ''), 'NULL')".format
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE src AS
        SELECT c.nid,
               {null('c."field_state_department:name"')} AS field_state_department,
               {null('c.group_name')}                    AS group_name,
               {null('c.field_search_keywords')}         AS field_search_keywords,
               {null('s.govt_type')}                     AS govt_type,
               {null('s.state_department')}              AS state_department
        FROM cat_df c LEFT JOIN state_df s USING (nid)
    """)

    known = " UNION ALL ".join(f"SELECT CAST(nid AS VARCHAR) AS nid FROM {t}" for t in TABLES)
    new = con.execute(f"SELECT nid FROM src WHERE nid NOT IN ({known}) ORDER BY nid").fetchall()
    if new:
        print(f"In the CSV but in neither table (not inserted): {[r[0] for r in new]}")

    for table, state_dept_col in TABLES.items():
        cols = dict(zip(NEW_COLS, [state_dept_col, *NEW_COLS[1:]]))  # src name -> table name
        join = f"{table} t JOIN src ON CAST(t.nid AS VARCHAR) = src.nid"
        total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        matched = con.execute(f"SELECT count(*) FROM {join}").fetchone()[0]
        filled = con.execute(
            f"SELECT {', '.join(f'count(src.{c})' for c in NEW_COLS)} FROM {join}").fetchone()
        print(f"\n{table}: {matched}/{total} rows matched by nid")
        for (src_col, col), n in zip(cols.items(), filled):
            print(f"  {col:30} {n:6d} non-null")
        if dry_run:
            continue

        # Outside the transaction: DuckDB can't UPDATE a table altered in the same one.
        for col in cols.values():
            con.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{col}" VARCHAR')
        sets = ", ".join(f'"{col}" = src.{src_col}' for src_col, col in cols.items())
        same = " AND ".join(f't."{col}" IS NOT DISTINCT FROM src.{src_col}'
                            for src_col, col in cols.items())
        con.execute("BEGIN")
        try:
            con.execute(f"UPDATE {table} SET {sets} FROM src "
                        f"WHERE CAST({table}.nid AS VARCHAR) = src.nid")
            written = con.execute(f"SELECT count(*) FROM {join} WHERE {same}").fetchone()[0]
            total_after = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert written == matched, f"{written} rows carry the new values, expected {matched}"
            assert total_after == total, f"row count changed {total} -> {total_after}"
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        print(f"  written to {written} rows")

    con.close()
    if dry_run:
        print("\n[dry-run] No changes written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add group and state-department fields to the raw catalog tables by nid.")
    parser.add_argument("catalog_csv", help="catalog_metadata.csv export")
    parser.add_argument("state_csv", help="catalog_state_metadata.csv export")
    parser.add_argument("--group-order", choices=["nid-desc", "row"], default="nid-desc",
                        help="How group_name / field_search_keywords are ordered in the catalog CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts, no write")
    args = parser.parse_args()
    main(args.catalog_csv, args.state_csv, args.group_order, args.dry_run)
