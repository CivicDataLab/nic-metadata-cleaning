"""
Extend title_search_check.py's sponsored_keyword_needed result to whole collections.

Datasets in a collection have near-identical titles, so one that does not come up
from its title fragments tells us about its siblings. For every collection with at
least one sponsored_keyword_needed = 'yes' dataset:
  1. SAMPLES members (--sample per collection, seeded) that were not themselves
     checked - mostly datasets with no sponsored keywords - and title-searches them
     with the same queries and first-page rule as title_search_check.py;
  2. marks the collection as needing sponsored keywords only when every tested
     dataset fails to come up: all its checked datasets are 'yes' and no sampled
     member comes up. Collections where the evidence is mixed are left unmarked
     and listed in the report.

Column written to dublin_core_remaining:
    collection_sponsored_keyword_needed   'yes' on every member of a marked collection,
                                          NULL elsewhere (recomputed on every run)
sponsored_keyword_needed and Subject[sponsored_keyword] are not touched; members
without sponsored keywords are flagged, not given any.

Report: data/sponsored_keyword_search/collection_sample_report.csv (one row per sampled dataset).

Usage:
  python collection_sponsored_keyword_needed.py --no-write
  python collection_sponsored_keyword_needed.py
"""
import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sponsored_keyword_search_check import DB_PATH, OUT_DIR, SMARTCITIES, TABLE  # noqa: E402
from title_search_check import first_page, title_queries  # noqa: E402

COLUMN = "collection_sponsored_keyword_needed"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--sample", type=int, default=2, help="members sampled per collection (default 2)")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    rows = con.execute(f"""SELECT Collection, nid, Title, "Identifier[landing_page]", sponsored_keyword_needed
                           FROM {TABLE} WHERE Collection IS NOT NULL ORDER BY nid""").fetchall()
    con.close()
    members = defaultdict(list)
    for collection, nid, title, landing_page, needed in rows:
        members[collection].append((nid, title, "smartcities" if SMARTCITIES in (landing_page or "") else "main", needed))
    targets = {c: m for c, m in members.items() if any(x[3] == "yes" for x in m)}

    rng = random.Random(args.seed)
    sampled = {}
    for collection, m in sorted(targets.items()):
        pool = [x for x in m if x[3] is None] or [x for x in m if x[3] == "no"]
        sampled[collection] = rng.sample(pool, min(args.sample, len(pool)))

    searches = {(p, q) for ms in sampled.values() for _, t, p, _ in ms for q in title_queries(t)}
    page = {}
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(lambda k: page.__setitem__(k, first_page(k[0], k[1], 10)), searches))

    marked, report, mixed = [], [], []
    for collection, ms in sampled.items():
        up = 0
        for nid, title, portal, _ in ms:
            best = min(((h[0], q) for q in title_queries(title)
                        if (h := page[(portal, q)]["visible"].get(nid))), default=None)
            up += best is not None
            report.append([collection, nid, title, "yes" if best else "no", best[1] if best else "", best[0] if best else ""])
        m = targets[collection]
        clear = up == 0 and not any(x[3] == "no" for x in m)
        (marked if clear else mixed).append(collection)

    report_path = OUT_DIR / "collection_sample_report.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["collection", "nid", "title", "comes_up", "best_query", "best_rank"])
        w.writerows(report)
    size = lambda cs: sum(len(targets[c]) for c in cs)
    print(f"{len(targets)} collections with a 'yes' dataset, {len(report)} members sampled "
          f"({sum(r[3] == 'yes' for r in report)} come up).")
    print(f"Marked: {len(marked)} collections, {size(marked)} rows. Left unmarked (mixed evidence): {len(mixed)} collections, {size(mixed)} rows.")
    print(f"Report: {report_path}")
    if args.no_write:
        return

    try:
        con = duckdb.connect(args.db)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {args.db} for writing - close it in DBeaver and re-run: {str(e).splitlines()[0]}")
    con.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {COLUMN} VARCHAR")
    con.register("_marked", __import__("pandas").DataFrame({"c": marked}))
    con.execute("BEGIN")
    con.execute(f"UPDATE {TABLE} SET {COLUMN} = NULL")
    con.execute(f"UPDATE {TABLE} SET {COLUMN} = 'yes' WHERE Collection IN (SELECT c FROM _marked)")
    written, total = con.execute(f"SELECT count({COLUMN}), count(*) FROM {TABLE}").fetchone()
    if written != size(marked):
        con.execute("ROLLBACK")
        raise SystemExit(f"Rolled back: {written} rows marked, expected {size(marked)}.")
    con.execute("COMMIT")
    con.close()
    print(f"Wrote {TABLE}.{COLUMN} = 'yes' on {written} of {total} rows.")


if __name__ == "__main__":
    main()
