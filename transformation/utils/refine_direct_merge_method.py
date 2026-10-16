"""
Demote exact-merge ('direct') groups whose headers do not carry the dimension
keys their titles carry.

A 'direct' row is one that sits in an exact merge group (identical normalized
title + header signature), so its members can simply be stacked. But stacking is
only lossless if every dimension the TITLE names -- state / district / year or
financial year / month / quarter -- also exists as a COLUMN in the headers
("Conforms To"). If a title says "Ground water quality in Andhra Pradesh - 2014"
and the headers have a STATE column but no year column, the 2014 lives only in
the title and is lost the moment that file is merged with its 2013 sibling.
Those datasets need a dimension column added first, i.e. they are 'curate'.

Rule (per dataset, applied per exact merge group):
  title_dims  = dimensions named in the Title
  header_dims = dimensions present as a column in "Conforms To"
  missing     = title_dims - header_dims
  If ANY member of a group has a missing dimension, the WHOLE group is demoted
  (a group is one merge unit, so one incomplete member spoils the merge).

Writes on demoted rows:
  merge_method      'direct' -> 'curate'
  Collection        = exact_merge_group_name  (keeps the invariant
                      curate <=> Collection IS NOT NULL that the rest of the
                      pipeline relies on; the group is the collection)
  merge_add_columns = comma list of missing dims, ordered
                      year,state,district,month,quarter
  needs_review      TRUE when the collection's members still differ in headers
                    after year/month tokens are stripped (adding the column
                    alone will not align them), else FALSE

A demoted group's name can already exist as a Collection carrying earlier
curate rows (same normalized title, different merge path). Those rows are part
of the same family, so merge_add_columns / needs_review are recomputed over the
WHOLE collection -- demoted plus pre-existing curate rows -- otherwise one
Collection would carry several different merge_add_columns values and the
per-collection exports downstream would be incoherent. Pre-existing rows keep
their merge_method and Collection; only the two derived columns are rewritten.

Groups that keep all their keys stay 'direct' and take their exact merge group's
name as Collection (the group IS the collection); merge_add_columns and
needs_review stay NULL. A name already used by a classified collection of another
merge_method gets a ' (direct merge)' suffix, so no Collection spans two
merge_methods. The script is fully idempotent and self-correcting: if headers are later filled in
(fill_headers_remaining.py) and a group becomes complete, a re-run restores it.
The recompute keys off exact_merge_group_id, not merge_method, for the same
reason. exact_merge_group_id / _name are always left intact.

PIPELINE ORDER: run AFTER set_merge_method.py -- that script derives
merge_method purely from exact_merge_group_name / Collection, so re-running it
on this table would undo every demotion made here. Rows already folded into a
reunited series by fold_header_variant_collections.py (merge_method
'change_in_header') and rows released by dissolve_small_collections.py
(merge_method 'non-mergeable') are skipped by both UPDATEs below, so these
scripts can be re-run in any order.

Usage:
  python refine_direct_merge_method.py --dry-run
  python refine_direct_merge_method.py
  python refine_direct_merge_method.py --table dublin_core_metadata
"""

import argparse
import csv
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # title_components
sys.path.insert(0, str(HERE.parent))     # dataset_merge
from dataset_merge import STATE_ALT                      # noqa: E402
from title_components import parse_title_components      # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
DATA_DIR = HERE.parent.parent / "data"
DIM_ORDER = ["year", "state", "district", "month", "quarter"]


# ── title side ───────────────────────────────────────────────────────────────
# STATE_ALT is a closed list but also carries national / ministry aliases; those
# are coverage statements, not a state key.
NON_STATE = {"india", "all india", "m/o railways", "m/o defence"}
STATE_RE = re.compile(rf"\b(?:{STATE_ALT})\b", re.I)

MONTHS = (r"(?:january|february|march|april|may|june|july|august|september"
          r"|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)")
# A month token counts only when it sits next to a number ("Jan 2019",
# "1st April 2009", "30 September, 2013"); bare "May"/"March" are ordinary words.
MONTH_RE = re.compile(rf"(?:\d[\w,]*\s*)?\b({MONTHS})\b(?:\s*,?\s*\d)?", re.I)
# "as on / as at / as of <MONTH>" is a snapshot convention (the year is the key,
# the month is part of the measure definition), so it is not a month dimension.
AS_ON_RE = re.compile(rf"\bas\s+(?:on|at|of)\b[^,;:]{{0,25}}?\b{MONTHS}\b", re.I)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:\d{4}|\d{2}))?\b|\b(?:19|20)\d{4}\b")
QUARTER_RE = re.compile(r"\bq[1-4]\b|\bquarter\b", re.I)
# "<Name> District" as a fallback when the anchored title parser misses.
DIST_RE = re.compile(r"\b([A-Z][\w.'&-]*(?:\s+[A-Z][\w.'&-]*)?)\s+[Dd]istrict\b")


def _months_in(text: str) -> list[str]:
    skip = [m.span() for m in AS_ON_RE.finditer(text)]
    out = []
    for m in MONTH_RE.finditer(text):
        s, e = m.span(1)
        if any(a <= s and e <= b for a, b in skip):
            continue
        if not re.search(r"\d", m.group(0)):     # needs an adjacent number
            continue
        out.append(m.group(1).lower()[:3])
    return out


def title_dims(title: str) -> set[str]:
    """Dimensions the title names (and therefore the data must carry)."""
    t = title or ""
    dims = set()

    if any(m.group(0).lower() not in NON_STATE for m in STATE_RE.finditer(t)):
        dims.add("state")

    comp = parse_title_components(t)
    district, state = comp.get("district"), (comp.get("state") or "")
    # The anchored parser needs a real state to anchor on; when it anchored on
    # "All India" (or captured a date) the district capture is spurious.
    if (district and state.lower() not in NON_STATE
            and not re.search(MONTHS, district, re.I)
            and not YEAR_RE.search(district)):
        dims.add("district")
    else:
        m = DIST_RE.search(t)
        if m and not re.search(MONTHS, m.group(1), re.I):
            dims.add("district")

    if YEAR_RE.search(t):
        dims.add("year")
    if _months_in(t):
        dims.add("month")
    if QUARTER_RE.search(t):
        dims.add("quarter")
    return dims


# ── header side ──────────────────────────────────────────────────────────────
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Columns that count something ("No. of Districts", "Total Years of Service")
# mention a dimension without being one.
_COUNT_COL = re.compile(r"^(?:no|nos|number|total|count|percentage|percent|share|avg|average)\b")

STATE_TOK = {"state", "states", "ut", "uts"}
DIST_TOK = {"district", "districts", "distt", "dist", "zila", "zilla", "subdistrict"}
# Singular only: "Years" almost always belongs to an age bucket ("Under 3 Years").
YEAR_TOK = {"year", "yr", "fy", "date", "period"}
MONTH_TOK = {"month", "mon", "date", "period"}
QUARTER_TOK = {"quarter", "qtr"}
# A time column is a pure time label -- "Year", "Financial Year", "MON_YR",
# "Sampling Date". The same word inside a measure name is not a time key
# ("1st Year Enrolment  Male", "Cases reported during the year", "Less than 1
# year"), so every token of the column must be either a time word or a
# qualifier; one content word disqualifies it.
TIME_QUALIFIERS = {
    "academic", "ac", "financial", "fin", "fiscal", "calendar", "reference",
    "ref", "survey", "census", "crop", "reporting", "report", "sampling",
    "sample", "data", "transaction", "trans", "start", "end", "from", "to",
    "of", "the", "in", "wise", "and", "name", "code", "col", "no", "sl", "s",
}
# All-caps headers do not split on camel case, so "TRDATE" arrives as one token.
_DATE_LIKE = re.compile(r"^(?!update$)[a-z]{0,5}date$")
_MONTHYEAR_LIKE = re.compile(r"^(?:mon|month)(?:yr|year)$")


def _tokens(col: str) -> list[str]:
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", _CAMEL.sub(" ", col)) if w]


def _time_tokens(toks: list[str]) -> set[str]:
    """Time words in a column that is *only* time words + qualifiers, else empty."""
    found = set()
    for t in toks:
        if t.isdigit() or t in TIME_QUALIFIERS:
            continue
        if t in YEAR_TOK or _DATE_LIKE.match(t) or _MONTHYEAR_LIKE.match(t):
            found.add("year")
        if t in MONTH_TOK or _DATE_LIKE.match(t) or _MONTHYEAR_LIKE.match(t):
            found.add("month")
        if t in QUARTER_TOK:
            found.add("quarter")
        elif t not in YEAR_TOK and t not in MONTH_TOK and not _DATE_LIKE.match(t) \
                and not _MONTHYEAR_LIKE.match(t):
            return set()          # a content word -> this is a measure, not a key
    return found


def header_dims(conforms_to: str) -> set[str]:
    """Dimensions present as an actual column in the header signature."""
    dims = set()
    for raw in (conforms_to or "").split(","):
        col = raw.strip()
        if not col:
            continue
        toks = _tokens(col)
        if not toks or _COUNT_COL.match(" ".join(toks)):
            continue
        tset = set(toks)
        if tset & STATE_TOK:
            dims.add("state")
        if tset & DIST_TOK:
            dims.add("district")
        dims |= _time_tokens(toks)
    return dims


# ── needs_review (same shape as detect_merge_add_columns.py) ─────────────────
_YEAR_TOKEN = re.compile(r"\b(?:19|20)\d{2}(?:[-/]\d{2,4})?\b|\b(?:19|20)\d{4}\b")
_MONTH_NUM = re.compile(rf"({MONTHS}[a-z]*)\s*\d{{2,6}}", re.I)


def _strip_time(name: str) -> str:
    s = _MONTH_NUM.sub(r"\1", name)
    s = _YEAR_TOKEN.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _signature_varies(sigs) -> bool:
    """True when headers still differ after year/month tokens are stripped."""
    stripped = {
        tuple(sorted(_strip_time(c.strip()) for c in (s or "").split(",") if c.strip()))
        for s in sigs
    }
    return len(stripped) > 1


# ── analysis ─────────────────────────────────────────────────────────────────
def analyse(con, table):
    rows = con.execute(f"""
        SELECT exact_merge_group_id, exact_merge_group_name, "Title", "Conforms To"
        FROM {table}
        WHERE exact_merge_group_id IS NOT NULL
    """).fetchall()

    groups = defaultdict(list)
    for gid, name, title, sig in rows:
        groups[gid].append((name, title or "", sig or ""))

    decisions = {}
    for gid, members in groups.items():
        missing, t_dims, h_dims = set(), set(), set()
        for _, title, sig in members:
            td = title_dims(title)
            hd = header_dims(sig)
            t_dims |= td
            h_dims |= hd
            missing |= (td - hd)
        name = members[0][0]
        decisions[gid] = {
            "group_name": name,
            "n": len(members),
            "title_dims": sorted(t_dims),
            "header_dims": sorted(h_dims),
            "missing": [d for d in DIM_ORDER if d in missing],
            "sigs": {s for _, _, s in members},
            "sample_title": members[0][1],
            "sample_headers": members[0][2],
        }

    # merge_add_columns / needs_review are properties of the resulting Collection
    # (= group name), not of the group: two groups can share a name, and the name
    # can already exist as a Collection holding earlier curate rows. Pool all of
    # them so one Collection carries one value.
    demoted_names = {d["group_name"] for d in decisions.values() if d["missing"]}
    pool = {n: {"missing": set(), "sigs": set()} for n in demoted_names}
    for d in decisions.values():
        if d["missing"]:
            p = pool[d["group_name"]]
            p["missing"] |= set(d["missing"])
            p["sigs"] |= d["sigs"]

    existing = []
    if demoted_names:
        placeholders = ",".join("?" * len(demoted_names))
        existing = con.execute(f"""
            SELECT "Collection", "Title", "Conforms To" FROM {table}
            WHERE exact_merge_group_id IS NULL AND merge_method = 'curate'
              AND "Collection" IN ({placeholders})
        """, list(demoted_names)).fetchall()
    for coll, title, sig in existing:
        p = pool[coll]
        p["missing"] |= (title_dims(title or "") - header_dims(sig or ""))
        p["sigs"].add(sig or "")

    collections = {
        name: {
            "add_cols": ",".join(d for d in DIM_ORDER if d in p["missing"]),
            "needs_review": _signature_varies(p["sigs"]),
            "n_existing": sum(1 for c, _, _ in existing if c == name),
        }
        for name, p in pool.items()
    }
    # Groups that stay 'direct' are a collection too -- the exact merge group IS
    # the collection -- so they carry its name rather than a NULL Collection.
    # A name already used by a *classified* collection of another merge_method
    # gets a suffix: a Collection must not span two merge_methods
    # (catalog_merge_method_stats.py totals depend on that). Rows whose
    # merge_method is still NULL are unclassified, not another method, so
    # sharing a name with them is fine.
    kept_names = {d["group_name"] for d in decisions.values() if not d["missing"]}
    taken = set()
    if kept_names:
        placeholders = ",".join("?" * len(kept_names))
        taken = {r[0] for r in con.execute(f"""
            SELECT DISTINCT "Collection" FROM {table}
            WHERE "Collection" IN ({placeholders})
              AND merge_method IS NOT NULL AND merge_method <> 'direct'
        """, list(kept_names)).fetchall()}

    for d in decisions.values():
        if d["missing"]:
            d["needs_review"] = collections[d["group_name"]]["needs_review"]
            d["collection_add_columns"] = collections[d["group_name"]]["add_cols"]
            d["collection"] = d["group_name"]
        else:
            d["needs_review"] = False
            d["collection_add_columns"] = ""
            d["collection"] = (f"{d['group_name']} (direct merge)"
                               if d["group_name"] in taken else d["group_name"])
    return decisions, collections, sorted(taken)


def write_audit(decisions, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["exact_merge_group_id", "exact_merge_group_name", "n_datasets",
                    "decision", "title_dims", "header_dims", "missing_dims",
                    "collection_add_columns", "needs_review", "n_header_signatures",
                    "sample_title", "sample_headers"])
        for gid in sorted(decisions):
            d = decisions[gid]
            w.writerow([gid, d["group_name"], d["n"],
                        "curate" if d["missing"] else "direct",
                        ",".join(d["title_dims"]), ",".join(d["header_dims"]),
                        ",".join(d["missing"]), d["collection_add_columns"],
                        d["needs_review"], len(d["sigs"]),
                        d["sample_title"], d["sample_headers"]])


def snapshot(con, table, path):
    """CSV of the columns this script rewrites, so the change can be reverted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT nid, exact_merge_group_id, merge_method, "Collection",
                   merge_add_columns, needs_review
            FROM {table}
        ) TO '{path}' (HEADER, DELIMITER ',')
    """)


def main(dry_run, db_path, table, audit_path):
    con = duckdb.connect(db_path, read_only=dry_run)
    try:
        decisions, collections, taken_names = analyse(con, table)
        demoted = {g: d for g, d in decisions.items() if d["missing"]}
        kept = len(decisions) - len(demoted)
        rows_dem = sum(d["n"] for d in demoted.values())
        rows_all = sum(d["n"] for d in decisions.values())

        print(f"exact merge groups analysed : {len(decisions)}  ({rows_all} rows)")
        print(f"  stay 'direct'             : {kept}  ({rows_all - rows_dem} rows)")
        print(f"  demoted to 'curate'       : {len(demoted)}  ({rows_dem} rows)\n")

        by_missing = defaultdict(lambda: [0, 0])
        for d in demoted.values():
            k = d["collection_add_columns"]
            by_missing[k][0] += 1
            by_missing[k][1] += d["n"]
        print(f"  {'merge_add_columns':<24} {'#groups':>8} {'#rows':>8}")
        for k, (c, n) in sorted(by_missing.items(), key=lambda x: -x[1][1]):
            print(f"  {k:<24} {c:>8} {n:>8}")
        nr = sum(d["n"] for d in demoted.values() if d["needs_review"])
        print(f"\n  needs_review=TRUE         : {nr} rows")
        n_exist = sum(c["n_existing"] for c in collections.values())
        print(f"  pre-existing curate rows pooled into these collections : {n_exist}")
        suffixed = [d for d in decisions.values()
                    if not d["missing"] and d["collection"] != d["group_name"]]
        print(f"\nkept 'direct' groups                : {len(decisions) - len(demoted)}")
        print(f"  distinct collection names         : "
              f"{len({d['collection'] for d in decisions.values() if not d['missing']})}")
        print(f"  names suffixed '(direct merge)' to avoid a clash : {len(suffixed)}")
        for d in suffixed:
            print(f"    {d['collection']}  [{d['n']} rows]")

        write_audit(decisions, audit_path)
        print(f"\nPer-group audit written: {audit_path}")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        snap = DATA_DIR / "backups" / f"{table}_merge_method_{ts}.csv"
        snapshot(con, table, snap)
        print(f"Pre-update snapshot     : {snap}")

        cols = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
        ).fetchall()}
        for name, typ in (("merge_method", "VARCHAR"), ("merge_add_columns", "VARCHAR"),
                          ("needs_review", "BOOLEAN"), ("Collection", "VARCHAR")):
            if name not in cols:
                con.execute(f'ALTER TABLE {table} ADD COLUMN "{name}" {typ}')
                print(f"Added column: {name}")

        con.execute("DROP TABLE IF EXISTS _tmp_demote")
        con.execute("CREATE TEMP TABLE _tmp_demote("
                    "gid BIGINT, coll VARCHAR, add_cols VARCHAR, review BOOLEAN)")
        con.executemany(
            "INSERT INTO _tmp_demote VALUES (?,?,?,?)",
            [(gid, d["collection"], d["collection_add_columns"], d["needs_review"])
             for gid, d in demoted.items()],
        )
        # Rows a later stage reclassified are left alone: 'change_in_header'
        # was reunited with its series by fold_header_variant_collections.py and
        # 'non-mergeable' was released by dissolve_small_collections.py. Keying
        # off exact_merge_group_id would otherwise pull both back into their old
        # group collection.
        con.execute(f"""
            UPDATE {table} AS t
            SET merge_method = 'curate',
                "Collection" = m.coll,
                merge_add_columns = m.add_cols,
                needs_review = m.review
            FROM _tmp_demote m
            WHERE t.exact_merge_group_id = m.gid
              AND t.merge_method NOT IN ('change_in_header', 'non-mergeable')
        """)

        # Groups that keep every key go back to 'direct', named after their
        # exact merge group; a re-run after headers improve un-demotes them.
        con.execute("DROP TABLE IF EXISTS _tmp_keep")
        con.execute("CREATE TEMP TABLE _tmp_keep(gid BIGINT, coll VARCHAR)")
        con.executemany("INSERT INTO _tmp_keep VALUES (?,?)",
                        [(gid, d["collection"]) for gid, d in decisions.items()
                         if not d["missing"]])
        restored = con.execute(f"""
            SELECT COUNT(*) FROM {table} t JOIN _tmp_keep k ON t.exact_merge_group_id = k.gid
            WHERE t.merge_method NOT IN ('change_in_header', 'non-mergeable')
              AND (t.merge_method IS DISTINCT FROM 'direct'
                   OR t."Collection" IS DISTINCT FROM k.coll
                   OR t.merge_add_columns IS NOT NULL OR t.needs_review IS NOT NULL)
        """).fetchone()[0]
        con.execute(f"""
            UPDATE {table} AS t
            SET merge_method = 'direct', "Collection" = k.coll,
                merge_add_columns = NULL, needs_review = NULL
            FROM _tmp_keep k
            WHERE t.exact_merge_group_id = k.gid
              AND t.merge_method NOT IN ('change_in_header', 'non-mergeable')
        """)

        # Pre-existing curate rows that share a Collection with a demoted group
        # take the pooled value, so one Collection carries one merge_add_columns.
        con.execute("DROP TABLE IF EXISTS _tmp_coll")
        con.execute("CREATE TEMP TABLE _tmp_coll(coll VARCHAR, add_cols VARCHAR, review BOOLEAN)")
        con.executemany(
            "INSERT INTO _tmp_coll VALUES (?,?,?)",
            [(name, c["add_cols"], c["needs_review"])
             for name, c in collections.items() if c["n_existing"]],
        )
        con.execute(f"""
            UPDATE {table} AS t
            SET merge_add_columns = c.add_cols, needs_review = c.review
            FROM _tmp_coll c
            WHERE t.exact_merge_group_id IS NULL
              AND t.merge_method = 'curate' AND t."Collection" = c.coll
        """)
        for tmp in ("_tmp_demote", "_tmp_keep", "_tmp_coll"):
            con.execute(f"DROP TABLE IF EXISTS {tmp}")
        print(f"Groups restored to 'direct' by this run : {restored} rows")

        print("\nWritten. Verification (rows with an exact merge group):")
        for method, n in con.execute(f"""
            SELECT merge_method, COUNT(*) FROM {table}
            WHERE exact_merge_group_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
        """).fetchall():
            print(f"  merge_method={str(method):<10} : {n:>8}")
        bad = con.execute(
            f'SELECT COUNT(*) FROM {table} '
            f"WHERE merge_method='curate' AND \"Collection\" IS NULL"
        ).fetchone()[0]
        print(f"  curate rows without a Collection (must be 0) : {bad}")
        still = con.execute(
            f'SELECT COUNT(*) FROM {table} '
            f"WHERE merge_method='direct' AND \"Collection\" IS NULL"
        ).fetchone()[0]
        print(f"  direct rows without a Collection (must be 0) : {still}")
        ndc = con.execute(
            f'SELECT COUNT(DISTINCT "Collection") FROM {table} '
            f"WHERE merge_method='direct'").fetchone()[0]
        print(f"  distinct 'direct' collections : {ndc}")
        mixed = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT "Collection" FROM {table}
                WHERE "Collection" IS NOT NULL AND merge_method IS NOT NULL
                GROUP BY 1
                HAVING COUNT(DISTINCT merge_method) > 1
                    OR COUNT(DISTINCT COALESCE(merge_add_columns, '~')) > 1)
        """).fetchone()[0]
        print(f"  collections with mixed merge_method/add_columns (must be 0) : {mixed}")
        # Rows that never had a merge_method keep NULL; a demoted group can land
        # in a collection that holds some of them. They are left for whatever
        # assigns merge_method to the unclassified rows.
        unclassified = con.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE merge_method IS NULL AND "Collection" IN (
                SELECT "Collection" FROM {table}
                WHERE exact_merge_group_id IS NOT NULL AND "Collection" IS NOT NULL)
        """).fetchone()[0]
        print(f"  unclassified (merge_method NULL) rows in demoted collections : {unclassified}")
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Demote exact-merge groups whose headers lack the title's dimension keys.")
    p.add_argument("--dry-run", action="store_true", help="Preview + audit CSV only.")
    p.add_argument("--db", default=DB_PATH, help="DuckDB path.")
    p.add_argument("--table", default=TABLE, help="Table to process.")
    p.add_argument("--audit-csv", default=None, help="Per-group audit CSV path.")
    a = p.parse_args()
    audit = Path(a.audit_csv) if a.audit_csv else DATA_DIR / f"{a.table}_direct_key_audit.csv"
    main(a.dry_run, a.db, a.table, audit)
