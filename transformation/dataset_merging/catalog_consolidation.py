"""
Propose and apply catalog_title -> new_catalog_title consolidation.

Catalogs carry the same variable slots titles do — "Crime in India 2011",
"Crime in India 2012" are one family split across 67 catalogs. Running the
title normaliser over the catalog name collapses those.

Scope of what this does automatically: it merges catalogs that share a
normalised base WITHIN a ministry, and only when at least MIN_CATALOGS of them
agree. Everything else keeps its original catalog title.

Scope of what it does NOT do: batch 1 rolled 365 catalogs up to 14 curated
themes. That is a naming judgement (which families belong together, and what
the result should be called) and is left to the human review pass — this script
gets 5,962 catalogs down to roughly 5,700 groups, not to 14. The proposal CSV
exists so that roll-up can be done on top of a deduplicated starting point.
Family names here are the stripped base, which is a handle, not a final title:
"Crime in India 2011" reduces to "Crime".

Rajya Sabha is skipped — rajya_sabha.py already consolidates its 195 session
catalogs into one.

Usage:
  python catalog_consolidation.py --dry-run
  python catalog_consolidation.py --apply
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dataset_merge import normalize_title  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
SKIP_MINISTRY = "Rajya Sabha"
MIN_CATALOGS = 2


def build_map(con, table: str) -> dict[tuple[str, str], str]:
    """{(ministry, catalog_title): new_catalog_title} for consolidatable catalogs."""
    rows = con.execute(f"""
        SELECT "Publisher[ministry_department]", "Relation[Catalog Title]", COUNT(*)
        FROM "{table}"
        WHERE "Publisher[ministry_department]" IS DISTINCT FROM ?
          AND "Relation[Catalog Title]" IS NOT NULL
        GROUP BY 1, 2
    """, [SKIP_MINISTRY]).fetchall()

    families = defaultdict(list)
    for ministry, catalog, n in rows:
        base = normalize_title(catalog or "").strip() or catalog
        families[(ministry, base)].append((catalog, n))

    mapping: dict[tuple[str, str], str] = {}
    n_families = 0
    for (ministry, base), members in families.items():
        if len(members) < MIN_CATALOGS:
            continue
        n_families += 1
        for catalog, _n in members:
            mapping[(ministry, catalog)] = base

    print(f"catalogs (non-RS)      : {len(rows)}")
    print(f"families >= {MIN_CATALOGS} catalogs : {n_families}")
    print(f"catalogs consolidated  : {len(mapping)}")
    print(f"catalogs left as-is    : {len(rows) - len(mapping)}")
    return mapping


def write_proposal(mapping, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "catalog_consolidation.csv"
    grouped = defaultdict(list)
    for (ministry, catalog), new in mapping.items():
        grouped[(ministry, new)].append(catalog)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ministry", "proposed_new_catalog_title", "n_catalogs",
                    "original_catalog_titles"])
        for (ministry, new), cats in sorted(grouped.items(), key=lambda x: -len(x[1])):
            w.writerow([ministry, new, len(cats), " | ".join(sorted(cats)[:20])])
    print(f"\nWrote {path} ({len(grouped)} families)")


def apply(con, table: str, mapping) -> None:
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()}
    if "new_catalog_title" not in cols:
        con.execute(f'ALTER TABLE "{table}" ADD COLUMN new_catalog_title VARCHAR')
        print("Added column: new_catalog_title")

    con.execute("DROP TABLE IF EXISTS _tmp_cat")
    con.execute("CREATE TEMP TABLE _tmp_cat(ministry VARCHAR, catalog VARCHAR, new VARCHAR)")
    con.executemany("INSERT INTO _tmp_cat VALUES (?,?,?)",
                    [(m, c, n) for (m, c), n in mapping.items()])
    con.execute(f"""
        UPDATE "{table}" AS d
        SET new_catalog_title = m.new
        FROM _tmp_cat m
        WHERE d."Publisher[ministry_department]" IS NOT DISTINCT FROM m.ministry
          AND d."Relation[Catalog Title]" = m.catalog
    """)
    # Catalogs with no family keep their own title, so the column is complete.
    con.execute(f"""
        UPDATE "{table}"
        SET new_catalog_title = "Relation[Catalog Title]"
        WHERE new_catalog_title IS NULL AND "Relation[Catalog Title]" IS NOT NULL
    """)
    con.execute("DROP TABLE IF EXISTS _tmp_cat")

    n_before, n_after = con.execute(f"""
        SELECT COUNT(DISTINCT "Relation[Catalog Title]"), COUNT(DISTINCT new_catalog_title)
        FROM "{table}"
    """).fetchone()
    print(f"\nWritten. Distinct catalogs {n_before} -> {n_after}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Consolidate catalog titles.")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--out-dir", default=str(HERE / "reports"))
    ap.add_argument("--apply", action="store_true", help="Write new_catalog_title.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=not args.apply)
    try:
        mapping = build_map(con, args.table)
        write_proposal(mapping, Path(args.out_dir))
        if args.apply:
            apply(con, args.table, mapping)
        else:
            print("\n[no --apply] Proposal only; database not modified.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
