"""
Fold orphan collections back into the collection they belong to, when the only
thing that separated them was a change in the header.

dublin_core_remaining holds ~9,000 collections whose names carry a " (schema N)"
suffix: one dataset series split into a separate collection per distinct header
signature. Most of those splits are cosmetic -- "S.No. Col. 1" vs "S. No Col.1",
"charge sheets" vs "chargesheets", "January_2016Peak Demand MW" vs "Peak Demand
MW" -- so a series that should be ONE collection is scattered over dozens, and
many of the pieces never even got a merge_method (they sit alone, unclassified).

This script reunites those pieces and marks them merge_method='change_in_header':
same series, mergeable only after the headers are reconciled.

Grain -- the *title key*, not the collection name:
    _normalize_key(normalize_title(Title))       (dataset_merge's own functions)
The collection names in this table come from dataset_merge's fuzzy pass
(token_sort_ratio >= 92), which fuses genuinely different series -- Block-wise
with District-wise, Deep Tubewells with Shallow Tubewells. The title key keeps
those apart, so it is what "the same dataset series" means here.

Method, per title key that currently spans more than one Collection:
  1. main    = the Collection holding the most rows (tie: the one without a
               "(schema N)" suffix, then by name) -- "the main collection".
  2. compare = every other Collection's canonical column set against main's.
               Canonicalisation drops index columns, punctuation, case, word
               order, digits and year tokens (even glued ones like
               "2015peak demand mw"), so only real column differences survive.
  3. fold    = variants with Jaccard >= --threshold OR at most --max-symdiff
               canonical columns of difference (small headers are punished by
               Jaccard: two 3-column headers differing by one column score
               0.5, which is still a slight difference).
  4. Variants below both bars stay where they are and are listed in the audit
     CSV as major-header-change candidates.

Writes on every row of a folded set (main included -- a Collection must not span
two merge_methods, which catalog_merge_method_stats.py relies on):
  merge_method      -> 'change_in_header'
  Collection        -> the series name (modal normalize_title base of the rows)
  merge_add_columns -> union of the values the folded rows already carried
  needs_review      -> TRUE (headers differ within the collection by definition)

Only rows with merge_method IS NULL or 'curate' take part. 'direct' rows were
verified to carry every title key in their headers (refine_direct_merge_method.py)
and 'non-mergeable' is an explicit earlier classification; neither is touched.

Already-folded rows stay in the population, so each run's main collection has a
larger column vocabulary than the last and attracts a few more variants: the
first pass over dublin_core_remaining folded 5,999 rows, then 6,077, then 6,081,
then nothing. Run it until it reports no folds. Once converged it is a true
no-op. The fold itself is one-way (the old split cannot be reconstructed), so a
pre-update snapshot of the affected columns goes to data/backups/ first, and
data/<table>_header_fold_composition.csv records new <- old collection.

PIPELINE ORDER: refine_direct_merge_method.py skips 'change_in_header' rows, so
the two can be re-run in either order.

Usage:
  python fold_header_variant_collections.py --dry-run
  python fold_header_variant_collections.py --threshold 0.8
  python fold_header_variant_collections.py
"""

import argparse
import csv
import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # split_collections_by_header_group
sys.path.insert(0, str(HERE.parent))     # dataset_merge
from dataset_merge import normalize_title, _normalize_key                 # noqa: E402
from split_collections_by_header_group import cols_of, norm_name, _INDEX  # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
DATA_DIR = HERE.parent.parent / "data"
LABEL = "change_in_header"
# merge_add_columns is written in this order elsewhere in the pipeline
# (detect_merge_add_columns.py, refine_direct_merge_method.py); keep it so a
# collection's value compares equal across scripts.
DIM_ORDER = ["year", "state", "district", "month", "quarter"]

SCHEMA_SUFFIX = re.compile(r" \(schema \d+\)$")
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december", "jan", "feb", "mar", "apr",
          "jun", "jul", "aug", "sept", "sep", "oct", "nov", "dec"}
# Words that carry no schema information: they appear or vanish between header
# eras without the data changing ("cases which trials were completed" vs
# "cases in which trials completed").
STOP = {"of", "the", "a", "an", "and", "in", "on", "at", "to", "for", "by", "as",
        "is", "are", "was", "were", "which", "from", "with", "during", "no", "nos",
        "number", "note", "col", "cols", "total"} | MONTHS


def canon(col: str) -> str:
    """
    Order-, spacing-, case-, digit- and year-insensitive form of one column.

    The final step sorts the *characters* of the de-spaced string, so a column
    survives being word-reordered and being split or joined at a space:
    "Charge Sheeted Female Persons" == "Chargesheeted Female Persons". Sorting
    whole tokens instead misses the second case (the joined word lands in a
    different alphabetical slot). Fuzzy string similarity would catch both but
    also scores "persons arrested male" vs "persons arrested female" at 95 --
    exactly the distinction that must not be blurred -- whereas a character
    multiset keeps them apart.
    """
    n = norm_name(col)                       # lower-case, punctuation -> space
    n = re.sub(r"(?:19|20)\d{2}", " ", n)    # years, glued ones included
    n = re.sub(r"\d+", " ", n)               # column numbers, bucket bounds
    toks = [t for t in n.split() if t and t not in STOP]
    return "".join(sorted("".join(toks)))


def header_map(sig: str) -> dict:
    """{canonical form: a readable original column name} for one signature."""
    out = {}
    for c in cols_of(sig or ""):
        if _INDEX.match(c.strip()):
            continue
        k = canon(c)
        if k:
            out.setdefault(k, c.strip())
    return out


def title_base(title: str) -> str:
    """dataset_merge's collection base name for one title."""
    b = normalize_title(title or "")
    return b if len(b.split()) >= 2 and len(b) >= 8 else (title or "")


def analyse(con, table, threshold, max_symdiff):
    rows = con.execute(f"""
        SELECT nid, "Title", "Collection", merge_method, "Conforms To",
               merge_add_columns, exact_merge_group_id
        FROM {table}
        WHERE merge_method IS NULL OR merge_method IN ('curate', '{LABEL}')
    """).fetchall()

    by_key = defaultdict(list)
    for r in rows:
        by_key[_normalize_key(title_base(r[1]))].append(r)

    folds, audit = [], []
    for key, members in by_key.items():
        variants = defaultdict(list)
        for m in members:
            variants[m[2]].append(m)
        if len(variants) < 2:
            continue

        main = max(variants, key=lambda c: (len(variants[c]),
                                            0 if c and not SCHEMA_SUFFIX.search(c) else -1,
                                            c or ""))
        main_map = {}
        for m in variants[main]:
            main_map.update(header_map(m[4]))
        main_set = set(main_map)

        kept = [main]
        for coll, rws in variants.items():
            if coll == main:
                continue
            vmap = {}
            for m in rws:
                vmap.update(header_map(m[4]))
            vset = set(vmap)
            union = main_set | vset
            jac = len(main_set & vset) / len(union) if union else 0.0
            sym = len(main_set ^ vset)
            fold = jac >= threshold or sym <= max_symdiff
            if fold:
                kept.append(coll)
            audit.append({
                "title_key": key, "main_collection": main, "variant_collection": coll,
                "main_rows": len(variants[main]), "variant_rows": len(rws),
                "main_cols": len(main_set), "variant_cols": len(vset),
                "jaccard": round(jac, 3), "symmetric_diff": sym,
                "decision": "fold" if fold else "keep separate",
                "only_in_variant": " | ".join(vmap[k] for k in sorted(vset - main_set)[:5]),
                "only_in_main": " | ".join(main_map[k] for k in sorted(main_set - vset)[:5]),
                "sample_variant_title": rws[0][1],
            })

        if len(kept) < 2:
            continue
        folded = [m for c in kept for m in variants[c]]
        # Name the reunited collection after the series itself: the fuzzy
        # collection name can belong to a different series (an "Alliance Air"
        # row sitting in an "Air Asia" collection), the title base cannot.
        base = Counter(title_base(m[1]) for m in folded).most_common()
        name = base[0][0]
        if len(name.split()) < 2 or len(name) < 8:
            name = SCHEMA_SUFFIX.sub("", main or "") or name
        folds.append({
            "key": key, "name": name, "collections": kept,
            "members": folded, "rows": len(folded),
            "exact_group_rows": sum(1 for m in folded if m[6] is not None),
        })

    # Absorb stragglers: a row can already carry a united name while belonging
    # to a different title key (the fuzzy collection names overlap). Leaving it
    # behind would make one Collection span two merge_methods, so it joins.
    target_names = {f["name"] for f in folds}
    target_names |= {r[2] for r in rows if r[3] == LABEL and r[2]}
    claimed = {m[0] for f in folds for m in f["members"]}
    by_name = defaultdict(list)
    for f in folds:
        by_name[f["name"]].append(f)
    absorbed = 0
    for r in rows:
        if r[2] in target_names and r[0] not in claimed and r[3] != LABEL:
            fs = by_name.get(r[2])
            if fs:
                fs[0]["members"].append(r)
            else:                       # collection folded by an earlier run
                folds.append({"key": None, "name": r[2], "collections": [r[2]],
                              "members": [r], "rows": 0, "exact_group_rows": 0})
                by_name[r[2]].append(folds[-1])
            absorbed += 1

    for f in folds:
        f["rows"] = len(f["members"])
        f["from_unclassified"] = sum(1 for m in f["members"] if m[3] is None)
        f["from_curate"] = sum(1 for m in f["members"] if m[3] == "curate")
        f["nids"] = [m[0] for m in f["members"]]
        vals = {v for m in f["members"] if m[5] for v in m[5].split(",") if v}
        f["add_cols"] = ",".join(d for d in DIM_ORDER if d in vals) or None
    for a in audit:
        a["united_name"] = next((f["name"] for f in folds if f["key"] == a["title_key"]), "")
    return folds, audit, absorbed


def write_audit(audit, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["title_key", "decision", "united_name", "main_collection", "variant_collection",
            "main_rows", "variant_rows", "main_cols", "variant_cols", "jaccard",
            "symmetric_diff", "only_in_variant", "only_in_main", "sample_variant_title"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for a in sorted(audit, key=lambda x: (x["decision"], -x["jaccard"])):
            w.writerow(a)


def write_composition(folds, path):
    """Which old collections each reunited collection was assembled from.

    The per-variant audit reflects the table as it stands now, so once a fold is
    written its comparison disappears from it; this file is the record of what
    actually moved. Only written when there is something to write, so a no-op
    re-run does not blank it.
    """
    counts = defaultdict(lambda: [0, None, None])
    for f in folds:
        for m in f["members"]:
            row = counts[(f["name"], m[2], m[3] or "(unclassified)")]
            row[0] += 1
            if row[1] is None:
                row[1] = m[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["new_collection", "old_collection", "old_merge_method",
                    "n_rows", "sample_title"])
        for (new, old, mm), (n, title, _) in sorted(counts.items(), key=lambda x: (x[0][0], -x[1][0])):
            w.writerow([new, old, mm, n, title])


def snapshot(con, table, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (SELECT nid, merge_method, "Collection", merge_add_columns, needs_review
              FROM {table}) TO '{path}' (HEADER, DELIMITER ',')
    """)


def main(dry_run, db_path, table, threshold, max_symdiff, audit_path):
    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        folds, audit, absorbed = analyse(con, table, threshold, max_symdiff)
        rows = sum(f["rows"] for f in folds)
        colls_in = sum(len(f["collections"]) for f in folds)
        print(f"title keys spanning >1 collection : {len({a['title_key'] for a in audit})}")
        print(f"variants compared to their main   : {len(audit)}")
        print(f"  folded                          : {sum(1 for a in audit if a['decision'] == 'fold')}")
        print(f"  kept separate (major change)    : {sum(1 for a in audit if a['decision'] != 'fold')}\n")
        print(f"series reunited                   : {len(folds)}")
        print(f"  collections collapsed           : {colls_in} -> {len(folds)}")
        print(f"  rows relabelled '{LABEL}' : {rows}")
        print(f"    previously unclassified (NULL): {sum(f['from_unclassified'] for f in folds)}")
        print(f"    previously curate             : {sum(f['from_curate'] for f in folds)}")
        print(f"    of which exact-merge-group    : {sum(f['exact_group_rows'] for f in folds)}")
        print(f"  stragglers absorbed by name       : {absorbed}")

        # Rows left behind in a collection that is losing members.
        touched = {c for f in folds for c in f["collections"]}
        moved = {n for f in folds for n in f["nids"]}
        left = con.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE "Collection" IN (SELECT UNNEST(?)) AND nid NOT IN (SELECT UNNEST(?))
        """, [list(touched), list(moved)]).fetchone()[0] if touched else 0
        print(f"  rows of other series left behind in those collections : {left}")

        write_audit(audit, audit_path)
        print(f"\nPer-variant audit written: {audit_path}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        if not folds:
            print("\nNothing to fold; table already converged.")
            return

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        snap = DATA_DIR / "backups" / f"{table}_fold_header_{ts}.csv"
        snapshot(con, table, snap)
        print(f"Pre-update snapshot      : {snap}")
        comp = DATA_DIR / f"{table}_header_fold_composition.csv"
        write_composition(folds, comp)
        print(f"Fold composition written : {comp}")

        con.execute("DROP TABLE IF EXISTS _tmp_fold")
        con.execute("CREATE TEMP TABLE _tmp_fold(nid VARCHAR, coll VARCHAR, add_cols VARCHAR)")
        con.executemany("INSERT INTO _tmp_fold VALUES (?,?,?)",
                        [(n, f["name"], f["add_cols"]) for f in folds for n in f["nids"]])
        con.execute(f"""
            UPDATE {table} AS t
            SET merge_method = '{LABEL}',
                "Collection" = f.coll,
                merge_add_columns = f.add_cols,
                needs_review = TRUE
            FROM _tmp_fold f
            WHERE t.nid = f.nid
        """)
        con.execute("DROP TABLE IF EXISTS _tmp_fold")

        # One value per collection, whatever the run history: a collection
        # assembled over several runs can otherwise carry a mix of the unions
        # each run computed.
        cur = con.execute(f"""
            SELECT "Collection", merge_add_columns FROM {table}
            WHERE merge_method = '{LABEL}'
        """).fetchall()
        union = defaultdict(set)
        for coll, ac in cur:
            if ac:
                union[coll] |= {v for v in ac.split(",") if v}
        harmonised = [(c, ",".join(d for d in DIM_ORDER if d in v) or None)
                      for c, v in union.items()]
        con.execute("DROP TABLE IF EXISTS _tmp_harm")
        con.execute("CREATE TEMP TABLE _tmp_harm(coll VARCHAR, add_cols VARCHAR)")
        if harmonised:
            con.executemany("INSERT INTO _tmp_harm VALUES (?,?)", harmonised)
        fixed = con.execute(f"""
            SELECT COUNT(*) FROM {table} t JOIN _tmp_harm h ON t."Collection" = h.coll
            WHERE t.merge_method = '{LABEL}'
              AND t.merge_add_columns IS DISTINCT FROM h.add_cols
        """).fetchone()[0]
        con.execute(f"""
            UPDATE {table} AS t SET merge_add_columns = h.add_cols
            FROM _tmp_harm h
            WHERE t."Collection" = h.coll AND t.merge_method = '{LABEL}'
        """)
        con.execute("DROP TABLE IF EXISTS _tmp_harm")
        print(f"merge_add_columns harmonised across collections : {fixed} rows")

        print("\nWritten. Verification:")
        for method, n in con.execute(f"""
            SELECT COALESCE(merge_method, '(null)'), COUNT(*) FROM {table}
            GROUP BY 1 ORDER BY 2 DESC
        """).fetchall():
            print(f"  merge_method={method:<18} : {n:>8}")
        mixed = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT "Collection" FROM {table}
                WHERE "Collection" IS NOT NULL AND merge_method IS NOT NULL
                GROUP BY 1
                HAVING COUNT(DISTINCT merge_method) > 1
                    OR COUNT(DISTINCT COALESCE(merge_add_columns, '~')) > 1)
        """).fetchone()[0]
        print(f"  collections with mixed merge_method/add_columns (must be 0) : {mixed}")
        no_coll = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE merge_method='{LABEL}' "
            f'AND "Collection" IS NULL').fetchone()[0]
        print(f"  '{LABEL}' rows without a Collection (must be 0) : {no_coll}")
        n_coll = con.execute(
            f'SELECT COUNT(DISTINCT "Collection") FROM {table} '
            f"WHERE merge_method='{LABEL}'").fetchone()[0]
        print(f"  distinct '{LABEL}' collections : {n_coll}")
        left_schema = con.execute(
            f'SELECT COUNT(DISTINCT "Collection") FROM {table} '
            f"WHERE \"Collection\" LIKE '%(schema %)'").fetchone()[0]
        print(f"  collections still carrying a (schema N) suffix : {left_schema}")
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Reunite collections split apart by header changes.")
    p.add_argument("--dry-run", action="store_true", help="Preview + audit CSV only.")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--table", default=TABLE)
    p.add_argument("--threshold", type=float, default=0.7,
                   help="Min Jaccard of canonical column sets to fold (default 0.7).")
    p.add_argument("--max-symdiff", type=int, default=2,
                   help="Fold anyway when at most this many canonical columns differ.")
    p.add_argument("--audit-csv", default=None)
    a = p.parse_args()
    audit = Path(a.audit_csv) if a.audit_csv else DATA_DIR / f"{a.table}_header_fold_audit.csv"
    main(a.dry_run, a.db, a.table, a.threshold, a.max_symdiff, audit)
