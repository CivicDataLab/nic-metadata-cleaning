"""
Group rows that share an identical header set into exact merge groups.

These are the datasets that can be stacked vertically with no curation: same
columns, same order-insensitive schema, differing only in which slice of the
world they cover. set_merge_method.py keys merge_method='direct' off the
exact_merge_group_name this script writes.

Grouping key is (ministry, catalog, normalized header signature, normalized
title base):

  * header signature — "Conforms To" split on comma, serial/index columns
    dropped, each name lowercased with separators removed and a trailing
    plural stripped, then sorted. This collapses pure naming variants
    ("state_code" vs "State Code", "class_1_boys" vs "class1_boys") while
    keeping genuinely different column sets apart. It does NOT collapse
    abbreviations ("st_code" vs "state_code") — those fall to the curate tier.
  * title base — normalize_title() from dataset_merge, so two datasets with
    the same schema but unrelated subjects don't get stacked.

Rows with no header stay ungrouped; they are the title tier's problem.

Usage:
  python dataset_vertical_merge_exact.py --table dublin_core_remaining --output-csv groups.csv
  python dataset_vertical_merge_exact.py --dry-run
  python dataset_vertical_merge_exact.py            # writes to dublin_core_metadata
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset_merge import normalize_title  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_metadata"
HEADER_COL = "Conforms To"
MIN_GROUP = 2

# Row-number / index columns carry no schema meaning and appear inconsistently.
_SERIAL_COL = re.compile(
    r"^(?:s|sl|sr|srl)\.?\s*(?:no|num|number)?\.?$|^unnamed(?::.*)?$|^#$|^index$",
    re.I,
)


def normalize_header_sig(value) -> str | None:
    """Order-insensitive schema fingerprint, or None when there is no header."""
    if not value or not str(value).strip():
        return None
    cols = []
    for col in str(value).split(","):
        col = col.strip()
        if not col or _SERIAL_COL.match(col):
            continue
        col = re.sub(r"[^a-z0-9]", "", col.lower())
        col = re.sub(r"s$", "", col)
        if col:
            cols.append(col)
    if not cols:
        return None
    return ",".join(sorted(cols))


def build_groups(con, table: str, where: str | None) -> dict[int, str]:
    """Return {nid: exact_merge_group_name} for every row in a group of >= MIN_GROUP."""
    sql = (
        f'SELECT nid, "Title", "Publisher[ministry_department]", '
        f'"Relation[Catalog Title]", "{HEADER_COL}" FROM "{table}"'
    )
    if where:
        sql += f" WHERE ({where})"

    buckets: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
    n_rows = n_no_header = 0
    for nid, title, ministry, catalog, header in con.execute(sql).fetchall():
        n_rows += 1
        sig = normalize_header_sig(header)
        if sig is None:
            n_no_header += 1
            continue
        base = normalize_title(title or "")
        buckets[(ministry, catalog, sig, base)].append((nid, title or ""))

    result: dict[int, tuple[int, str]] = {}
    sizes: list[int] = []
    # Sorted so the ids are stable across runs.
    for gid, (key, members) in enumerate(
        sorted((k, v) for k, v in buckets.items() if len(v) >= MIN_GROUP), start=1
    ):
        base = key[3]
        # Canonical name: the stripped title base, falling back to the
        # alphabetically first title when the base was blanked out. Names are
        # NOT unique — two catalogs can share a base — so the id is the real
        # group key and the name is for humans.
        name = base.strip() or sorted(t for _, t in members)[0]
        sizes.append(len(members))
        for nid, _title in members:
            result[nid] = (gid, name)

    print(f"rows scanned            : {n_rows}")
    print(f"  no usable header      : {n_no_header}")
    print(f"  distinct buckets      : {len(buckets)}")
    print(f"  groups (>= {MIN_GROUP} rows)   : {len(sizes)}")
    print(f"  rows in a group       : {len(result)}")
    if sizes:
        sizes.sort()
        print(f"  group size max/median : {sizes[-1]} / {sizes[len(sizes)// 2]}")
    return result


def write_csv(con, table: str, where: str | None, groups: dict[int, str], path: str) -> None:
    sql = f'SELECT nid, "Title", "Relation[Catalog Title]" FROM "{table}"'
    if where:
        sql += f" WHERE ({where})"
    counts: dict[int, int] = defaultdict(int)
    for gid, _name in groups.values():
        counts[gid] += 1

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nid", "Title", "catalog_title", "exact_merge_group_id",
                    "exact_merge_group_name", "n_in_group"])
        for nid, title, catalog in con.execute(sql).fetchall():
            hit = groups.get(nid)
            gid, name = hit if hit else ("", "")
            w.writerow([nid, title, catalog, gid, name,
                        counts.get(gid, "") if hit else ""])
    print(f"\nWrote {path}")


def apply(con, table: str, groups: dict[int, str]) -> None:
    existing = {
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ?", [table],
        ).fetchall()
    }
    if "exact_merge_group_name" not in existing:
        con.execute(f'ALTER TABLE "{table}" ADD COLUMN exact_merge_group_name VARCHAR')
        print("Added column: exact_merge_group_name")
    if "exact_merge_group_id" not in existing:
        con.execute(f'ALTER TABLE "{table}" ADD COLUMN exact_merge_group_id BIGINT')
        print("Added column: exact_merge_group_id")

    # nid is BIGINT on dublin_core_metadata but VARCHAR on dublin_core_remaining,
    # so carry it as text and cast on both sides of every comparison.
    con.execute("DROP TABLE IF EXISTS _tmp_exact")
    con.execute("CREATE TEMP TABLE _tmp_exact(nid VARCHAR, gid BIGINT, name VARCHAR)")
    con.executemany(
        "INSERT INTO _tmp_exact VALUES (?,?,?)",
        [(str(k), gid, name) for k, (gid, name) in groups.items()],
    )

    # Scoped to the rows this run actually grouped: clear then set, so a rerun
    # cannot leave a stale name on a row that dropped out of a group.
    con.execute(
        f'UPDATE "{table}" SET exact_merge_group_name = NULL, exact_merge_group_id = NULL '
        f'WHERE CAST(nid AS VARCHAR) IN (SELECT nid FROM _tmp_exact)'
    )
    con.execute(f"""
        UPDATE "{table}" AS d
        SET exact_merge_group_name = m.name, exact_merge_group_id = m.gid
        FROM _tmp_exact m
        WHERE CAST(d.nid AS VARCHAR) = m.nid
    """)
    con.execute("DROP TABLE IF EXISTS _tmp_exact")

    written = con.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE exact_merge_group_name IS NOT NULL'
    ).fetchone()[0]
    print(f"\nWritten. Rows with exact_merge_group_name: {written}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Group rows sharing an identical header set into exact merge groups."
    )
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--where", default=None, help="Extra SQL predicate.")
    ap.add_argument("--ministry", default=None,
                    help="Shorthand for --where on Publisher[ministry_department].")
    ap.add_argument("--output-csv", default=None, metavar="PATH",
                    help="Write results to CSV instead of the database (read-only).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report group counts without writing.")
    args = ap.parse_args()

    where = args.where
    if args.ministry:
        ministry = args.ministry.replace("'", "''").lower()
        clause = f"lower(\"Publisher[ministry_department]\") = '{ministry}'"
        where = f"{where} AND {clause}" if where else clause

    read_only = args.dry_run or args.output_csv is not None
    con = duckdb.connect(args.db, read_only=read_only)
    try:
        print(f"Source table            : {args.table}")
        if where:
            print(f"Filter                  : {where}")
        groups = build_groups(con, args.table, where)

        if args.output_csv:
            write_csv(con, args.table, where, groups, args.output_csv)
        elif args.dry_run:
            print("\n[dry-run] No changes written.")
        else:
            apply(con, args.table, groups)
    finally:
        con.close()


if __name__ == "__main__":
    main()
