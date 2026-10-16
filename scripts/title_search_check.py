"""
Check whether a dataset comes up on data.gov.in search for fragments of its own
title, and so whether its sponsored keywords are needed at all.

For every dataset with a "Subject[sponsored_keyword]" value, queries are built
from its title, e.g. "Real time Air Quality Index from various locations" gives
    air quality | quality index | air quality index | real time air quality index
    aqi (acronym of a 3-4 word fragment) | various locations | ...
and each is searched on the portal's search API (same parameters as
sponsored_keyword_search_check.py; smartcities.data.gov.in datasets are searched
on that portal). A dataset "comes up" for a query when it is on the first page:
the listed result itself, or a dataset listed inside a result's group
(collapse_data). See sponsored_keyword_search_check.py for how the API collapses
results; nid is the match key here too.

Query building (title_queries):
  * acronyms in brackets, "(PMFME)", kept as they are - two or more capitals;
  * everything else comes from the title with brackets, years, dates and
    "as on ..." removed and cut into runs of content words at stop / boilerplate
    words (of, in, state/UT, wise, details, number, year, ...);
  * per run: the whole run (up to 6 words), every 2 and 3 word fragment, and the
    initials of every 3-4 word fragment (3+ letters) - "air quality index" -> aqi.
  Single words are not searched: they are too generic to say anything.

A search is made once per distinct (portal, query) however many datasets produce
it, and cached in title_search_cache.jsonl, so a re-run only fetches new queries.

Columns written to dublin_core_remaining (rows with sponsored keywords only):
    title_search               first      top result of one of its title queries
                               top 10     on the first page of one
                               not found  on none of them
    sponsored_keyword_needed   no  - it comes up from its title, keywords not needed
                               yes - it does not, keep the sponsored keywords
Limit: a result group lists at most five datasets, so one folded out of a bigger
group is not seen and counts as not found - the count of "yes" errs on the high side.

Report: data/sponsored_keyword_search/title_search_report.csv (one row per dataset,
with the query that placed it best and how the sponsored-keyword check went).

Usage:
  python title_search_check.py --limit 200      # try it, no write
  python title_search_check.py --no-write
  python title_search_check.py                   # needs metadata.db closed in DBeaver
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sponsored_keyword_search_check import (  # noqa: E402
    DB_PATH, KEYWORD_COLUMN, OUT_DIR, SMARTCITIES, TABLE, FIRST_PAGE, JsonlCache, run_pool, search,
)

STATUS_COLUMN = "title_search"
NEEDED_COLUMN = "sponsored_keyword_needed"
SPONSORED_REPORT = OUT_DIR / "sponsored_keyword_search_report.csv"

STOPWORDS = set("""a an the of in on at by for to from and or with without under against as per into over via vs
state ut uts states union territory territories wise year years details detail number numbers no total during
upto up till last reply unstarred starred question questions lok sabha rajya ministry india all level levels
data dataset report reports statement table tables item items category categories type types whether given
sl s""".split())
BRACKET_ACRONYM = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9&.\-]{1,11})\s*\)")
DATE = re.compile(r"\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b|\b\d{4}(?:[-–]\d{2,4})?\b|\bas on\b.*", re.I)


def title_queries(title):
    queries = [a for a in BRACKET_ACRONYM.findall(title or "")
               if len(re.findall(r"[A-Z]", a)) >= 2 and a.lower() not in STOPWORDS]
    text = DATE.sub(" ", re.sub(r"\([^)]*\)", " ", title or ""))
    runs, run = [], []
    for word in re.findall(r"[A-Za-z0-9]+(?:&[A-Za-z0-9]+)*", text):
        if word.lower() in STOPWORDS or word.isdigit():
            if run:
                runs.append(run)
            run = []
        else:
            run.append(word)
    if run:
        runs.append(run)
    for run in runs:
        if len(run) < 2:
            continue
        if len(run) <= 6:
            queries.append(" ".join(run))
        for size in (2, 3, 4):
            for i in range(len(run) - size + 1):
                fragment = run[i:i + size]
                if size <= 3:
                    queries.append(" ".join(fragment))
                if size >= 3 and len(run) >= 3:
                    queries.append("".join(w[0] for w in fragment).lower())
    seen, unique = set(), []
    for q in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique.append(q)
    return unique


def load_datasets(db, limit):
    """Datasets with sponsored keywords; falls back to the last sponsored-keyword report while DBeaver holds the DB."""
    try:
        con = duckdb.connect(db, read_only=True)
        have = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{TABLE}'").fetchall()}
        sponsored = "sponsored_keyword_search" if "sponsored_keyword_search" in have else "NULL"
        rows = con.execute(f"""
            SELECT nid, Title, "Identifier[landing_page]", {sponsored} FROM {TABLE}
            WHERE trim(coalesce("{KEYWORD_COLUMN}", '')) <> '' ORDER BY nid""").fetchall()
        con.close()
        datasets = [{"nid": n, "title": t, "portal": "smartcities" if SMARTCITIES in (lp or "") else "main", "sponsored": s}
                    for n, t, lp, s in rows]
    except duckdb.IOException as e:
        print(f"Could not read {db} ({str(e).splitlines()[0]}); using {SPONSORED_REPORT.name} for the dataset list.")
        seen = {}
        with open(SPONSORED_REPORT, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.setdefault(r["nid"], {"nid": r["nid"], "title": r["title"], "portal": r["portal"],
                                           "sponsored": r["sponsored_keyword_search"]})
        datasets = sorted(seen.values(), key=lambda d: d["nid"])
    return datasets[:limit] if limit else datasets


def first_page(portal, query, top):
    """-> {nid: [rank, 'result' | 'grouped']} for the datasets visible on the first `top` results."""
    total, rows = search(portal, query, limit=top)
    visible = {}
    for rank, row in enumerate(rows, 1):
        for member in [row] + list((row.get("collapse_data") or {}).get("rows", [])):
            visible.setdefault(str(member["nid"][0]), [rank, "result" if member is row else "grouped"])
    return {"total": total, "visible": visible}


def write_columns(db, status, needed):
    try:
        con = duckdb.connect(db)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {db} for writing - close it in DBeaver and re-run (the searches are cached): "
                         f"{str(e).splitlines()[0]}")
    rows, nids = con.execute(f"SELECT count(*), count(DISTINCT nid) FROM {TABLE}").fetchone()
    assert rows == nids, f"{TABLE}.nid is not unique ({rows} rows, {nids} nids)"
    for column in (STATUS_COLUMN, NEEDED_COLUMN):
        con.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {column} VARCHAR")
    con.register("_title", pd.DataFrame([(n, status[n], needed[n]) for n in status], columns=["nid", "s", "n"]))
    con.execute("BEGIN")
    con.execute(f"""UPDATE {TABLE} AS t SET {STATUS_COLUMN} = x.s, {NEEDED_COLUMN} = x.n
                    FROM _title x WHERE x.nid = t.nid""")
    written, total = con.execute(f"SELECT count({STATUS_COLUMN}), count(*) FROM {TABLE}").fetchone()
    if written != len(status) or total != rows:
        con.execute("ROLLBACK")
        raise SystemExit(f"Rolled back: {written} rows marked for {len(status)} datasets, {total} rows (was {rows}).")
    con.execute("COMMIT")
    con.close()
    print(f"Wrote {TABLE}.{STATUS_COLUMN} and .{NEEDED_COLUMN} on {written} rows ({total - written} left as they were).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--workers", type=int, default=8, help="parallel searches (default 8)")
    parser.add_argument("--top", type=int, default=FIRST_PAGE, help="results counted as coming up (default 10)")
    parser.add_argument("--limit", type=int, help="check only the first N datasets; implies --no-write")
    parser.add_argument("--no-write", action="store_true", help="search and report, leave the table alone")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached searches and redo them")
    args = parser.parse_args()

    datasets = load_datasets(args.db, args.limit)
    queries = {d["nid"]: title_queries(d["title"]) for d in datasets}
    wanted = {(d["portal"], q.lower()): q for d in datasets for q in queries[d["nid"]]}
    print(f"{len(datasets)} datasets, {sum(map(len, queries.values()))} title queries "
          f"({len(wanted)} distinct searches); {sum(not q for q in queries.values())} titles give no query.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = JsonlCache(OUT_DIR / "title_search_cache.jsonl", args.refresh)  # (portal, query, top) -> first_page()
    tasks = [(key,) for key in wanted if key + (args.top,) not in cache.data]

    def task(key):
        cache.put([(key + (args.top,), first_page(key[0], wanted[key], args.top))])

    print(f"{len(tasks)} searches to fetch.")
    failed = run_pool("search", tasks, task, args.workers)[1]
    if failed:
        for t, error in failed[:10]:
            print(f"  failed: {t[0]} - {error}")
        raise SystemExit(f"{len(failed)} searches failed; nothing written. Re-run to retry them (finished ones are cached).")

    status, needed, report = {}, {}, []
    for d in datasets:
        best = None  # (rank, kind-order, query)
        for q in queries[d["nid"]]:
            hit = cache.data[(d["portal"], q.lower(), args.top)]["visible"].get(d["nid"])
            if hit and (best is None or (hit[0], hit[1] != "result") < (best[0], best[1] != "result")):
                best = (hit[0], hit[1], q)
        status[d["nid"]] = ("first" if best[0] == 1 and best[1] == "result" else "top 10") if best else "not found"
        needed[d["nid"]] = "no" if best else "yes"
        report.append([d["nid"], d["title"], d["portal"], status[d["nid"]], needed[d["nid"]], *([best[2], best[0]] if best else ["", ""]),
                       len(queries[d["nid"]]), d["sponsored"] or ""])

    report_path = OUT_DIR / "title_search_report.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["nid", "title", "portal", STATUS_COLUMN, NEEDED_COLUMN, "best_query", "best_rank",
                         "queries_tried", "sponsored_keyword_search"])
        writer.writerows(report)

    counts = Counter(status.values())
    print(f"\n{STATUS_COLUMN} over {len(datasets)} datasets (first page = top {args.top}):")
    for value in ("first", "top 10", "not found"):
        print(f"  {value:<10} {counts[value]:>6}  {counts[value] / len(datasets):6.1%}")
    cross = Counter((d["sponsored"] or "-", status[d["nid"]]) for d in datasets)
    print("\nsponsored_keyword_search (rows) vs title_search (columns):")
    print(f"  {'':<10}" + "".join(f"{v:>11}" for v in ("first", "top 10", "not found")))
    for s in ("first", "top 10", "found", "not found"):
        print(f"  {s:<10}" + "".join(f"{cross[(s, v)]:>11}" for v in ("first", "top 10", "not found")))
    print(f"Report: {report_path}")

    if args.no_write or args.limit:
        print("No write (--no-write / --limit).")
        return
    write_columns(args.db, status, needed)


if __name__ == "__main__":
    main()
