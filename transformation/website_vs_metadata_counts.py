"""
Compare dataset counts per ministry_department / state_department:
  - website_count  : from the OGDP API response.json -> data.aggregations
  - metadata_count : rows in metadata.db tables "remaining-raw-datasets" + "lot3_raw"

The metadata columns hold the whole org hierarchy in one string, e.g.
  "Ministry of Home Affairs, Department of Home, Registrar General and Census Commissioner, India"
  "Punjab,Planning Department, Punjab,Department of Economic and Statistical Organization, Punjab"
Names can contain commas themselves, so the string is split by matching the
longest run of comma-separated pieces against the website's bucket names.
A row counts once for every org in its hierarchy - same way the website
aggregation counts it.

Usage (from the project root, with the project venv active):
    python transformation/website_vs_metadata_counts.py
    python transformation/website_vs_metadata_counts.py --json ~/Downloads/response.json --out counts.csv
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_DB = HERE / "metadata.db"
DEFAULT_JSON = Path.home() / "Downloads" / "response.json"
DEFAULT_OUT = HERE / "website_vs_metadata_counts.csv"

# table label -> accepted table names in metadata.db (first one found is used)
TABLES = {
    "remaining-raw-datasets": ["remaining-raw-datasets", "remaining_raw_datasets"],
    "lot3_raw": ["lot3_raw"],
}
CATEGORIES = ["ministry_department", "state_department"]


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def split_hierarchy(value, keys):
    """Split one hierarchy string into org names.

    keys: {normalised website name: website spelling}
    Returns [(name, found_on_website), ...]. Consecutive pieces that match no
    website name are kept together as one name.
    """
    if value is None or value != value:  # NULL / NaN
        return []
    atoms = [a.strip() for a in str(value).split(",") if a.strip()]
    out, pending = [], []
    i, n = 0, len(atoms)
    while i < n:
        hit = None
        for j in range(n, i, -1):
            cand = norm(", ".join(atoms[i:j]))
            if cand in keys:
                hit = (j, keys[cand])
                break
        if hit:
            if pending:
                out.append((", ".join(pending), False))
                pending = []
            out.append((hit[1], True))
            i = hit[0]
        else:
            pending.append(atoms[i])
            i += 1
    if pending:
        out.append((", ".join(pending), False))
    return out


def load_website(json_path):
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    aggs = data["data"]["aggregations"]
    website = {}
    for cat in CATEGORIES:
        website[cat] = {b["key"]: int(b["doc_count"]) for b in aggs[cat]["buckets"]}
        other = aggs[cat].get("sum_other_doc_count", 0)
        if other:
            print(f"WARNING: {cat} has sum_other_doc_count={other} - some buckets were cut off in the API response")
    return website, data.get("total")


def load_metadata_rows(db_path):
    """Return {table label: [(nid, ministry_department, state_department), ...]}."""
    import duckdb

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"Could not open {db_path}: {e}\n"
            "If it says the file is locked, close DBeaver / any other open connection to metadata.db and rerun."
        )
    try:
        present = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
        rows = {}
        for label, candidates in TABLES.items():
            table = next((t for t in candidates if t in present), None)
            if table is None:
                sys.exit(f"Table {label!r} not found in {db_path}. Tables there: {sorted(present)}")
            cols = {
                r[0].lower(): r[0]
                for r in con.execute(
                    "SELECT column_name FROM duckdb_columns() WHERE table_name = ?", [table]
                ).fetchall()
            }
            missing = [c for c in CATEGORIES if c not in cols]
            if missing:
                sys.exit(f"Table {table!r} has no column(s) {missing}. Columns: {sorted(cols.values())}")
            nid = f'"{cols["nid"]}"' if "nid" in cols else "NULL"
            q = (
                f'SELECT {nid}, "{cols["ministry_department"]}", "{cols["state_department"]}" '
                f'FROM "{table}"'
            )
            rows[label] = con.execute(q).fetchall()
        return rows
    finally:
        con.close()


def build(rows_by_table, website):
    """Count metadata rows per org name and join with the website counts."""
    keys = {cat: {norm(k): k for k in website[cat]} for cat in CATEGORIES}
    meta = {cat: Counter() for cat in CATEGORIES}
    unmatched = {cat: Counter() for cat in CATEGORIES}
    stats = {}

    for label, rows in rows_by_table.items():
        no_org = 0
        for _nid, ministry, state in rows:
            found_any = False
            for cat, value in zip(CATEGORIES, (ministry, state)):
                names = split_hierarchy(value, keys[cat])
                for name, ok in names:
                    if not ok:
                        unmatched[cat][name] += 1
                # a row counts once per org, even if the name repeats in its hierarchy
                for name in {n for n, _ in names}:
                    meta[cat][name] += 1
                found_any = found_any or bool(names)
            no_org += not found_any
        stats[label] = {"rows": len(rows), "rows_without_org": no_org}

    out = []
    for cat in CATEGORIES:
        for name in set(website[cat]) | set(meta[cat]):
            w = website[cat].get(name, 0)
            m = meta[cat].get(name, 0)
            out.append(
                {
                    "category": cat,
                    "name": name,
                    "website_count": w,
                    "metadata_count": m,
                    "difference": w - m,
                    "note": "" if name in website[cat] else "not in website aggregations",
                }
            )
    order = {c: i for i, c in enumerate(CATEGORIES)}
    out.sort(key=lambda r: (order[r["category"]], -r["website_count"], -r["metadata_count"], r["name"].lower()))
    return out, stats, unmatched


def nid_checks(rows_by_table):
    dup_within, labels = Counter(), {}
    for label, rows in rows_by_table.items():
        ids = [r[0] for r in rows if r[0] not in (None, "")]
        c = Counter(ids)
        dup_within[label] = sum(v - 1 for v in c.values() if v > 1)
        labels[label] = set(c)
    names = list(labels)
    overlap = len(labels[names[0]] & labels[names[1]]) if len(names) == 2 else 0
    return dup_within, overlap


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    website, total = load_website(Path(args.json).expanduser())
    rows_by_table = load_metadata_rows(Path(args.db).expanduser())
    result, stats, unmatched = build(rows_by_table, website)

    out_path = Path(args.out).expanduser()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["category", "name", "website_count", "metadata_count", "difference", "note"]
        )
        w.writeheader()
        w.writerows(result)

    print(f"Website total (API 'total'): {total}")
    for label, s in stats.items():
        print(f"{label}: {s['rows']} rows ({s['rows_without_org']} with no ministry/state value)")
    dup_within, overlap = nid_checks(rows_by_table)
    print(f"Duplicate nids within tables: {dict(dup_within)} | nids in both tables: {overlap}")
    for cat in CATEGORIES:
        rows = [r for r in result if r["category"] == cat]
        with_meta = sum(1 for r in rows if r["metadata_count"])
        print(f"{cat}: {len(rows)} names, {with_meta} with metadata")
        if unmatched[cat]:
            print(f"  {len(unmatched[cat])} metadata name(s) not found on the website:")
            for name, c in unmatched[cat].most_common(20):
                print(f"    {c:7d}  {name}")
    print(f"\nWrote {len(result)} rows -> {out_path}")


if __name__ == "__main__":
    main()
