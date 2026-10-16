"""
Lot 3 version of the sponsored-keyword check: which dublin_core_lot3 datasets do
NOT come up on data.gov.in search for fragments of their own title (and so would
need sponsored keywords)?

Lot 3 has no Subject[sponsored_keyword] column, so there is no per-keyword check
and no flag to extend; this is the title check only, and it is report-only - the
table is opened read-only. (Adding columns to lot 3 needs the user's say-so.)

  Collections (rows with a Collection value: change_in_header, curate, direct)
      --collection-sample members per collection are drawn at random (seeded) and
      title-searched, with the same queries and first-page rule as
      title_search_check.py. A collection is
          needs     none of the sampled members comes up
          ok        all of them come up
          mixed     some do
      Mixed collections are the ones to look at, or to re-sample with a bigger
      --collection-sample: lot 2 showed a sample of two can flip a collection.
  Non-mergeable (no collection, so each is on its own)
      --nonmerge-sample datasets are drawn at random and searched; 0 searches them
      all. The sample's share that does not come up estimates the rest - their
      titles are not similar, so the estimate is only a guide.

Searches are cached in title_search_cache.jsonl, shared with title_search_check.py
(same key: portal, query, top), so queries already run for lot 2 cost nothing.

Reports, in data/sponsored_keyword_search/:
    lot3_collection_report.csv     one row per collection
    lot3_sample_report.csv         one row per searched dataset
Usage:
  python lot3_title_check.py                       # 3 per collection, 500 non-mergeable
  python lot3_title_check.py --nonmerge-sample 0   # all non-mergeable
"""
import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sponsored_keyword_search_check import DB_PATH, OUT_DIR, SMARTCITIES, JsonlCache, run_pool  # noqa: E402
from title_search_check import first_page, title_queries  # noqa: E402

TABLE = "dublin_core_lot3"
TOP = 10


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--table", default=TABLE)
    parser.add_argument("--collection-sample", type=int, default=3)
    parser.add_argument("--nonmerge-sample", type=int, default=500, help="0 = all")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--workers", type=int, default=4, help="default 4; 8 got throttled on the lot 2 run")
    args = parser.parse_args()

    try:
        con = duckdb.connect(args.db, read_only=True)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {args.db} - close it in DBeaver and re-run: {str(e).splitlines()[0]}")
    rows = con.execute(f"""SELECT nid, Title, "Identifier[landing_page]", Collection, merge_method
                           FROM {args.table} WHERE nid IS NOT NULL ORDER BY nid""").fetchall()
    con.close()
    rng = random.Random(args.seed)
    members = defaultdict(list)
    nonmerge = []
    for nid, title, landing_page, collection, method in rows:
        item = (nid, title, "smartcities" if SMARTCITIES in (landing_page or "") else "main", method)
        if collection is not None:
            members[collection].append(item)
        elif method == "non-mergeable":
            nonmerge.append(item)
    sampled = [(c, rng.sample(m, min(args.collection_sample, len(m)))) for c, m in sorted(members.items())]
    if args.nonmerge_sample and args.nonmerge_sample < len(nonmerge):
        nonmerge = rng.sample(nonmerge, args.nonmerge_sample)
    todo = [(c, it) for c, ms in sampled for it in ms] + [("", it) for it in nonmerge]

    queries = {it[0]: title_queries(it[1]) for _, it in todo}
    wanted = {(it[2], q.lower()): q for _, it in todo for q in queries[it[0]]}
    print(f"{len(members)} collections ({sum(len(m) for m in members.values())} rows), sampled {sum(len(ms) for _, ms in sampled)}; "
          f"non-mergeable searched {len(nonmerge)}; {len(wanted)} distinct searches.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = JsonlCache(OUT_DIR / "title_search_cache.jsonl", False)
    tasks = [(k,) for k in wanted if k + (TOP,) not in cache.data]
    print(f"{len(tasks)} searches to fetch ({len(wanted) - len(tasks)} cached).")
    failed = run_pool("search", tasks,
                      lambda k: cache.put([(k + (TOP,), first_page(k[0], wanted[k], TOP))]), args.workers)[1]
    if failed:
        for t, e in failed[:5]:
            print(f"  failed: {t[0]} - {e}")
        raise SystemExit(f"{len(failed)} searches failed. Re-run to retry them (finished ones are cached).")

    detail, up_by = [], {}
    for collection, (nid, title, portal, method) in todo:
        best = min(((h[0], q) for q in queries[nid] if (h := cache.data[(portal, q.lower(), TOP)]["visible"].get(nid))),
                   default=None)
        up_by[nid] = best is not None
        detail.append([collection, method, nid, title, "yes" if best else "no", best[1] if best else "", best[0] if best else ""])
    with open(OUT_DIR / "lot3_sample_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["collection", "merge_method", "nid", "title", "comes_up", "best_query", "best_rank"])
        w.writerows(detail)

    verdicts = {}
    with open(OUT_DIR / "lot3_collection_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["collection", "merge_method", "rows", "sampled", "come_up", "verdict"])
        for collection, ms in sampled:
            up = sum(up_by[it[0]] for it in ms)
            verdicts[collection] = "needs" if up == 0 else "ok" if up == len(ms) else "mixed"
            w.writerow([collection, Counter(i[3] for i in members[collection]).most_common(1)[0][0],
                        len(members[collection]), len(ms), up, verdicts[collection]])

    print("\nCollections (verdict -> collections, rows):")
    for v in ("needs", "mixed", "ok"):
        cs = [c for c, x in verdicts.items() if x == v]
        print(f"  {v:<6} {len(cs):>5} collections {sum(len(members[c]) for c in cs):>7} rows")
    n_up = sum(up_by[it[0]] for _, it in todo if not _)
    if nonmerge:
        print(f"\nNon-mergeable: {len(nonmerge)} searched, {n_up} come up ({n_up / len(nonmerge):.1%}), "
              f"{len(nonmerge) - n_up} do not ({1 - n_up / len(nonmerge):.1%}).")
    print(f"Reports: {OUT_DIR / 'lot3_collection_report.csv'}, {OUT_DIR / 'lot3_sample_report.csv'}")


if __name__ == "__main__":
    main()
