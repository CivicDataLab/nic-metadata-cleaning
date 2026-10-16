"""
Check whether a dataset comes up on data.gov.in search for its own sponsored
keywords, and mark the result on dublin_core_remaining.sponsored_keyword_search.

Every dataset with a "Subject[sponsored_keyword]" value is checked against the
portal's search API, once per keyword:

    https://www.data.gov.in/backend/dmspublic/v1/search?query=<keyword>
        &filters[type]=resources&filters[domain_visibility]=4&sort[_score]=desc
        &notfilters[domain]=smartcities.data.gov.in

How a result is matched to a table row: on nid. Each result row carries nid,
uuid and title, and all three agree with the table (nid <-> nid,
uuid <-> "Identifier[UUID]", title <-> Title once the <em> highlight tags are
stripped), so nid is used and the uuid is cross-checked and reported.

Things the API does that shape the check:
  * Results are collapsed. A result row is the best hit of a group and lists at
    most five of the group's datasets under collapse_data; `total` counts the
    datasets, not the rows. A dataset can therefore match a keyword without
    being listed anywhere, so paging alone cannot tell "not found".
  * filters[nid][]=... restricts a search to given datasets without changing
    their scores. That gives a definite found / not found per dataset, and the
    score says how far down the open ranking the dataset can be.
  * offset is a row offset, the order is stable, and offset + limit may not
    pass 10,000.
  * The URL above leaves smartcities.data.gov.in out, so datasets whose landing
    page is on that portal are searched with filters[domain] set to it instead.

So the run has two passes, both on a thread pool:
  1. match  - per keyword, ask in batches of nids which datasets the search
              returns at all, and with what score.
  2. rank   - per keyword with at least one such dataset, page the open search
              until every one of them is placed (or --max-rank is reached).

A dataset's rank for a keyword is the position of the result row it appears in.
rank_type in the report says how it was placed:
    result   it is the listed result itself
    grouped  it is listed inside another result's group
    hidden   it matches but is folded out of sight; rank is the lowest position
             its group can have (an upper bound)
    beyond   it matches, deeper than --max-rank

sponsored_keyword_search, per dataset, best keyword wins:
    first      it is the top result for one of its keywords
    top 10     it is on the first page (rank 2-10, or grouped under rank 1)
    found      the search returns it, below the first page
    not found  the search does not return it for any of its keywords
Rows without sponsored keywords stay NULL.

Outputs, under data/sponsored_keyword_search/:
    sponsored_keyword_search_report.csv   one row per dataset x keyword
    match_cache.jsonl, rank_cache.jsonl   finished searches, so a re-run only
                                          does what is missing (--refresh redoes all)

The column is created if missing and recomputed for every row in one
transaction. Nothing is written if any search failed; re-run to retry those.

Usage:
  python sponsored_keyword_search_check.py --limit 200     # try it, no write
  python sponsored_keyword_search_check.py --no-write      # full check, report only
  python sponsored_keyword_search_check.py
"""
import argparse
import csv
import html
import json
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(ROOT / "transformation" / "metadata.db")
OUT_DIR = ROOT / "data" / "sponsored_keyword_search"
TABLE = "dublin_core_remaining"
KEYWORD_COLUMN = "Subject[sponsored_keyword]"
STATUS_COLUMN = "sponsored_keyword_search"

SEARCH_URL = "https://www.data.gov.in/backend/dmspublic/v1/search"
BASE_PARAMS = [("filters[type]", "resources"), ("filters[domain_visibility]", 4), ("sort[_score]", "desc")]
SMARTCITIES = "smartcities.data.gov.in"
PORTAL_PARAMS = {
    "main": [("notfilters[domain]", SMARTCITIES)],
    "smartcities": [("filters[domain]", SMARTCITIES)],
}
FIRST_PAGE = 10          # results on the portal's first page
RESULT_WINDOW = 10000    # the API rejects offset + limit beyond this
NID_BATCH = 40           # datasets per filters[nid][] request
TIMEOUT = 120
RETRIES = 5

_local = threading.local()


def _session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
        _local.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    return _local.session


def search(portal, query, limit, offset=0, nids=()):
    """One search call -> (total, rows). Errors come back as HTTP 200 with their own statusCode in the body."""
    params = PORTAL_PARAMS[portal] + BASE_PARAMS + [("query", query), ("limit", limit), ("offset", offset)]
    params += [("filters[nid][]", nid) for nid in nids]
    error = None
    for attempt in range(RETRIES):
        try:
            body = _session().get(SEARCH_URL, params=params, timeout=TIMEOUT).json()
            if body.get("statusCode") == 200:
                return body.get("total", 0), (body.get("data") or {}).get("rows", [])
            error = f"statusCode {body.get('statusCode')}"
        except (requests.RequestException, ValueError) as e:
            error = repr(e)
        time.sleep(2 ** attempt)
    raise RuntimeError(f"search for {query!r} ({portal}) failed: {error}")


def clean_title(row):
    return html.unescape(re.sub(r"</?em[^>]*>", "", row["title"][0])).strip()


class JsonlCache:
    """Append-only jsonl of finished searches; the last line for a key wins."""

    def __init__(self, path, refresh):
        self.data = {}
        self.lock = threading.Lock()
        if path.exists() and not refresh:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        key, value = json.loads(line)
                    except ValueError:
                        continue  # torn last line of an interrupted run
                    self.data[tuple(key)] = value
        self.file = open(path, "w" if refresh else "a", encoding="utf-8")

    def put(self, items):
        with self.lock:
            for key, value in items:
                self.data[key] = value
                self.file.write(json.dumps([key, value], ensure_ascii=False) + "\n")
            self.file.flush()


def split_keywords(cell):
    """Split a keyword cell the way import_keyword_files.py does: on ';' if it has one, else ','."""
    keywords = []
    for keyword in cell.split(";" if ";" in cell else ","):
        keyword = keyword.strip()
        if keyword and keyword.lower() not in [k.lower() for k in keywords]:
            keywords.append(keyword)
    return keywords


def load_datasets(db, limit):
    con = duckdb.connect(db, read_only=True)
    rows = con.execute(f"""
        SELECT nid, "Identifier[UUID]", Title, "{KEYWORD_COLUMN}", "Identifier[landing_page]"
        FROM {TABLE}
        WHERE trim(coalesce("{KEYWORD_COLUMN}", '')) <> ''
        ORDER BY nid
    """).fetchall()
    con.close()
    datasets = [
        {"nid": nid, "uuid": uuid, "title": title, "keywords": split_keywords(cell),
         "portal": "smartcities" if SMARTCITIES in (landing_page or "") else "main"}
        for nid, uuid, title, cell, landing_page in rows
    ]
    return datasets[:limit] if limit else datasets


def match_batch(portal, keyword, nids):
    """Which of these datasets does a search for `keyword` return? -> {nid: score, or None when it is not returned}"""
    total, rows = search(portal, keyword, limit=len(nids), nids=nids)
    scores = {str(row["nid"][0]): row["_score"] for row in rows}
    # Datasets folded under a listed result carry no score, and only five per group are listed: ask for those one by one.
    for nid in nids:
        if len(scores) >= total:
            break
        if nid not in scores:
            found, row = search(portal, keyword, limit=1, nids=[nid])
            if found:
                scores[nid] = row[0]["_score"]
    return {nid: scores.get(nid) for nid in nids}


def rank_keyword(portal, keyword, scores, page_size, max_rank):
    """Place the datasets known to match `keyword` ({nid: score}) in the open search for it."""
    if not scores:
        total, rows = search(portal, keyword, limit=1)
        return {"total": total, "top": [str(rows[0]["nid"][0]), clean_title(rows[0])] if rows else None,
                "max_rank": max_rank, "ranks": {}}
    ranks, positions = {}, []  # positions[i] = score of result i + 1
    total = top = None
    exhausted = False
    while len(positions) < max_rank and not exhausted:
        limit = min(page_size, max_rank - len(positions))
        found, rows = search(portal, keyword, limit=limit, offset=len(positions))
        if total is None:
            total, top = found, [str(rows[0]["nid"][0]), clean_title(rows[0])] if rows else None
        for row in rows:
            positions.append(row["_score"])
            # the result itself first, so it is not taken for a member of its own group
            for member in [row] + list((row.get("collapse_data") or {}).get("rows", [])):
                nid = str(member["nid"][0])
                if nid in scores and nid not in ranks:
                    ranks[nid] = [len(positions), "result" if member is row else "grouped", member["uuid"][0]]
        exhausted = len(rows) < limit
        unplaced = [score for nid, score in scores.items() if nid not in ranks]
        # results come best first: once the page ends below every unplaced score, none of them is further down
        if not unplaced or (positions and min(unplaced) > positions[-1]):
            break
    for nid, score in scores.items():
        if nid in ranks:
            continue
        if exhausted or (positions and score > positions[-1]):
            # folded out of sight: its group is led by a result scoring at least as high
            ranks[nid] = [max(1, sum(1 for s in positions if s >= score)), "hidden", None]
        else:
            ranks[nid] = [None, "beyond", None]
    return {"total": total, "top": top, "max_rank": max_rank, "ranks": ranks}


def run_pool(label, tasks, fn, workers):
    """Run fn(*task) for every task on a thread pool -> ([(task, result)], failures)."""
    done, failed = [], []
    started = last = time.time()
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fn, *task): task for task in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            task = futures[future]
            try:
                done.append((task, future.result()))
            except Exception as e:
                failed.append((task, e))
            if time.time() - last > 15 or i == len(futures):
                last = time.time()
                print(f"  {label}: {i}/{len(futures)} in {last - started:.0f}s, {len(failed)} failed", flush=True)
    return done, failed


def dataset_status(results):
    """results: one (score, rank, rank_type) per keyword; score is None when the search does not return the dataset."""
    if any(rank == 1 and rank_type == "result" for _, rank, rank_type in results):
        return "first"
    if any(rank is not None and rank <= FIRST_PAGE for _, rank, _ in results):
        return "top 10"
    if any(score is not None for score, _, _ in results):
        return "found"
    return "not found"


def write_status(db, status):
    try:
        con = duckdb.connect(db)
    except duckdb.IOException as e:
        raise SystemExit(f"Could not open {db} for writing (is it open in DBeaver?): {e}")
    rows, nids = con.execute(f"SELECT count(*), count(DISTINCT nid) FROM {TABLE}").fetchone()
    assert rows == nids, f"{TABLE}.nid is not unique ({rows} rows, {nids} nids)"
    con.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {STATUS_COLUMN} VARCHAR")
    con.register("_status", pd.DataFrame(list(status.items()), columns=["nid", "status"]))
    con.execute("BEGIN")
    con.execute(f"UPDATE {TABLE} AS t SET {STATUS_COLUMN} = (SELECT status FROM _status s WHERE s.nid = t.nid)")
    written, total = con.execute(f"SELECT count({STATUS_COLUMN}), count(*) FROM {TABLE}").fetchone()
    if written != len(status) or total != rows:
        con.execute("ROLLBACK")
        raise SystemExit(f"Rolled back: {written} rows marked for {len(status)} datasets, {total} rows (was {rows}).")
    con.execute("COMMIT")
    con.close()
    print(f"Wrote {TABLE}.{STATUS_COLUMN} on {written} rows ({total - written} left NULL).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--workers", type=int, default=8, help="parallel searches (default 8)")
    parser.add_argument("--page-size", type=int, default=250, help="results per request when ranking (default 250)")
    parser.add_argument("--max-rank", type=int, default=1000,
                        help=f"how deep to look for a dataset's rank (default 1000, at most {RESULT_WINDOW})")
    parser.add_argument("--limit", type=int, help="check only the first N datasets; implies --no-write")
    parser.add_argument("--no-write", action="store_true", help="search and report, leave the table alone")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached searches and redo them")
    args = parser.parse_args()
    max_rank = min(args.max_rank, RESULT_WINDOW)

    datasets = load_datasets(args.db, args.limit)
    # one search per portal and keyword, whatever its case: the search is case-insensitive
    wanted = defaultdict(dict)  # (portal, keyword.lower()) -> {nid: None}, in table order
    spelling = {}
    for d in datasets:
        for keyword in d["keywords"]:
            key = (d["portal"], keyword.lower())
            wanted[key][d["nid"]] = None
            spelling.setdefault(key, keyword)
    pairs = sum(len(nids) for nids in wanted.values())
    print(f"{len(datasets)} datasets with sponsored keywords "
          f"({sum(d['portal'] == 'smartcities' for d in datasets)} on {SMARTCITIES}), "
          f"{len(wanted)} keyword searches, {pairs} dataset x keyword checks.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matches = JsonlCache(OUT_DIR / "match_cache.jsonl", args.refresh)  # (portal, keyword, nid) -> score or None
    ranked = JsonlCache(OUT_DIR / "rank_cache.jsonl", args.refresh)    # (portal, keyword) -> rank_keyword()

    tasks = []
    for key, nids in wanted.items():
        todo = [nid for nid in nids if key + (nid,) not in matches.data]
        tasks += [(key, todo[i:i + NID_BATCH]) for i in range(0, len(todo), NID_BATCH)]

    def match_task(key, nids):
        scores = match_batch(key[0], spelling[key], nids)
        matches.put([(key + (nid,), score) for nid, score in scores.items()])

    print(f"Pass 1 (match): {len(tasks)} batches to fetch.")
    _, failed = run_pool("match", tasks, match_task, args.workers)

    tasks = []
    for key, nids in wanted.items():
        if any(key + (nid,) not in matches.data for nid in nids):
            continue  # a batch failed; ranking it now would cache a partial answer
        scores = {nid: matches.data[key + (nid,)] for nid in nids if matches.data[key + (nid,)] is not None}
        cached = ranked.data.get(key)
        if not cached or cached["max_rank"] < max_rank or not set(scores) <= set(cached["ranks"]):
            tasks.append((key, scores))

    def rank_task(key, scores):
        ranked.put([(key, rank_keyword(key[0], spelling[key], scores, args.page_size, max_rank))])

    print(f"Pass 2 (rank): {len(tasks)} keyword searches to fetch.")
    failed += run_pool("rank", tasks, rank_task, args.workers)[1]

    if failed:
        for task, error in failed[:10]:
            print(f"  failed: {task[0]} - {error}")
        raise SystemExit(f"{len(failed)} searches failed; nothing written. Re-run to retry them (finished ones are cached).")

    status, report = {}, []
    rank_types, uuid_mismatch = Counter(), 0
    for d in datasets:
        results = []
        for keyword in d["keywords"]:
            key = (d["portal"], keyword.lower())
            score = matches.data[key + (d["nid"],)]
            rank, rank_type, uuid = ranked.data[key]["ranks"].get(d["nid"], [None, "", None])
            if uuid and uuid != d["uuid"]:
                uuid_mismatch += 1
            results.append((score, rank, rank_type))
            rank_types[rank_type or "not found"] += 1
        status[d["nid"]] = dataset_status(results)
        for keyword, (score, rank, rank_type) in zip(d["keywords"], results):
            hit = ranked.data[(d["portal"], keyword.lower())]
            report.append([d["nid"], d["uuid"], d["title"], d["portal"], status[d["nid"]], keyword, hit["total"],
                           "yes" if score is not None else "no", rank, rank_type, score,
                           *(hit["top"] or ["", ""])])

    report_path = OUT_DIR / "sponsored_keyword_search_report.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["nid", "uuid", "title", "portal", STATUS_COLUMN, "keyword", "keyword_total_results",
                         "found", "rank", "rank_type", "score", "top_result_nid", "top_result_title"])
        writer.writerows(report)

    counts = Counter(status.values())
    print(f"\n{STATUS_COLUMN} over {len(datasets)} datasets:")
    for value in ("first", "top 10", "found", "not found"):
        print(f"  {value:<10} {counts[value]:>6}  {counts[value] / len(datasets):6.1%}")
    print(f"Per dataset x keyword ({len(report)}): " + ", ".join(f"{k} {v}" for k, v in rank_types.most_common()))
    empty = [spelling[key] + (" (smartcities)" if key[0] == "smartcities" else "")
             for key in wanted if not ranked.data[key]["total"]]
    print(f"{len(empty)} keyword searches return no results at all: "
          f"{', '.join(sorted(empty)[:20])}{' ...' if len(empty) > 20 else ''}")
    print(f"uuid disagreements on nid matches: {uuid_mismatch}")
    print(f"Report: {report_path}")

    if args.no_write or args.limit:
        print("No write (--no-write / --limit).")
        return
    write_status(args.db, status)


if __name__ == "__main__":
    main()
