#!/usr/bin/env python3
"""
A work table for collection fixes, so dublin_core_remaining is only written once
the whole set of decisions has been reviewed.

collection_worktable holds, per nid, the editable collection columns
(merge_method, Collection, merge_add_columns, Remark) next to their values at
creation time (orig_*), plus provenance: locked (hand-edited by the user --
batches may not touch it), decided_by, batch, confidence, rationale.

Subcommands
  create        CREATE TABLE collection_worktable AS SELECT ... from
                dublin_core_remaining (refuses to overwrite unless --replace).
                Seed the user's hand edits afterwards with
                  import_edited_export.py FILE.xlsx --table collection_worktable
                      --columns merge_method,Collection,merge_add_columns,Remark
  lock-user     mark every row that differs from orig_* (or carries a Remark)
                as locked, decided_by='user'.
  diff          summary of how the work table differs from dublin_core_remaining.
  load CSV      validate a batch of decisions and (with --apply) write it.
  export-review write the review workbook for the user.
  apply         write the work table's decisions to dublin_core_remaining.

Decision CSV (one row per decision group):
  source_collection  the collection the members come from, as it was when the
                     pack was built; '<outside>' for rows pulled in from
                     elsewhere; ignored for nid: specs
  members            all | rest | G<n>[,G<m>...] | nid:<a>;<b>;...
                     all/rest/G need --pack (the batch's pack .json)
  merge_method       change_in_header | non-mergeable | to be removed
                     (--allow-methods widens it for cleanup batches)
  Collection         required for change_in_header, must be blank otherwise
  merge_add_columns  comma list of tokens; blank = NULL
  Remark             header-normalisation note for the merge step; blank keeps
                     the row's existing Remark
  confidence         high | medium | low
  rationale          free text

Every write: CSV snapshot to data/backups/ first, one UPDATE ... FROM a temp
table (never per-row UPDATEs -- they corrupted this DB twice), read-back check.
"""

import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))     # dataset_merge
sys.path.insert(0, str(HERE))            # sibling utils (takes precedence)

from apply_collection_review import normalise_mac                  # noqa: E402
from detect_collection_defects import augment_header_dims          # noqa: E402
from refine_direct_merge_method import header_dims                 # noqa: E402

DB_PATH = str(HERE.parent / "metadata.db")
MAIN = "dublin_core_remaining"
WORK = "collection_worktable"
DATA_DIR = HERE.parent.parent / "data"
EDIT_COLS = ["merge_method", "Collection", "merge_add_columns", "Remark"]
METHODS = {"change_in_header", "non-mergeable", "to be removed"}
ALL_METHODS = METHODS | {"curate", "direct", "no header", "unverified", "failed to download"}
CONFIDENCE = {"high", "medium", "low"}
# Tokens already in use in the table or agreed with the user. Anything else is
# reported (not refused): a genuinely new category may need a new token.
VOCAB = {
    "year", "state", "district", "month", "quarter", "airline", "service_scope",
    "carrier_class", "jail_type", "victim_group", "offence", "property_type",
    "registration_type", "price_basis", "product_measure", "school_level", "area",
    "scheme_type", "storage_type", "use_status", "well_type", "temperature_measure",
    "social_group", "sex", "inmate_group", "mi_census", "law", "casualty_type",
    "base_year", "region", "urban_rural",
}
SCHEMA_N = re.compile(r"\(schema \d+\)", re.I)
SPAN = re.compile(r"\bfrom\b.+\bto\b", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def q(c):
    return f'"{c}"'


# ── create / lock / diff ─────────────────────────────────────────────────────

def cmd_create(con, args):
    exists = con.execute("SELECT count(*) FROM information_schema.tables "
                         "WHERE table_name = ?", [WORK]).fetchone()[0]
    if exists and not args.replace:
        sys.exit(f"{WORK} already exists; pass --replace to rebuild it (drops all decisions)")
    con.execute(f"DROP TABLE IF EXISTS {WORK}")
    con.execute(f"""
        CREATE TABLE {WORK} AS
        SELECT CAST(nid AS VARCHAR)                  AS nid,
               "Title"                               AS Title,
               trim("Publisher[ministry_department]") AS ministry,
               merge_method, "Collection", merge_add_columns,
               CAST(NULL AS VARCHAR)                 AS Remark,
               merge_method                          AS orig_merge_method,
               "Collection"                          AS orig_Collection,
               merge_add_columns                     AS orig_merge_add_columns,
               FALSE                                 AS locked,
               CAST(NULL AS VARCHAR)                 AS decided_by,
               CAST(NULL AS VARCHAR)                 AS batch,
               CAST(NULL AS VARCHAR)                 AS confidence,
               CAST(NULL AS VARCHAR)                 AS rationale,
               CAST(NULL AS TIMESTAMP)               AS updated_at
        FROM {MAIN}""")
    n = con.execute(f"SELECT count(*) FROM {WORK}").fetchone()[0]
    m = con.execute(f"SELECT count(*) FROM {MAIN}").fetchone()[0]
    print(f"created {WORK}: {n} rows ({MAIN} has {m})")
    if n != m:
        sys.exit("row counts differ")


def cmd_lock_user(con, args):
    cond = ("merge_method IS DISTINCT FROM orig_merge_method OR "
            '"Collection" IS DISTINCT FROM orig_Collection OR '
            "merge_add_columns IS DISTINCT FROM orig_merge_add_columns OR "
            "Remark IS NOT NULL")
    n = con.execute(f"SELECT count(*) FROM {WORK} WHERE ({cond}) AND NOT locked").fetchone()[0]
    print(f"rows edited by the user and not yet locked: {n}")
    if not args.apply:
        print("[dry-run] re-run with --apply")
        return
    con.execute(f"UPDATE {WORK} SET locked = TRUE, decided_by = 'user', batch = 'user_xlsx', "
                f"updated_at = now() WHERE ({cond}) AND NOT locked")
    print(f"locked {n} rows")


def cmd_diff(con, args):
    rows = con.execute(f"""
        SELECT w.nid, w.decided_by, w.batch,
               d.merge_method, w.merge_method, d."Collection", w."Collection",
               d.merge_add_columns, w.merge_add_columns
        FROM {WORK} w JOIN {MAIN} d ON CAST(d.nid AS VARCHAR) = w.nid""").fetchall()
    per_col, by_who, trans = Counter(), Counter(), Counter()
    changed = 0
    for nid, who, batch, m0, m1, c0, c1, a0, a1 in rows:
        diff = [n for n, a, b in (("merge_method", m0, m1), ("Collection", c0, c1),
                                  ("merge_add_columns", a0, a1)) if a != b]
        if not diff:
            continue
        changed += 1
        per_col.update(diff)
        by_who[(who or "?", batch or "?")] += 1
        if m0 != m1:
            trans[(m0, m1)] += 1
    remarks = con.execute(f"SELECT count(*) FROM {WORK} WHERE Remark IS NOT NULL").fetchone()[0]
    print(f"rows that differ from {MAIN}: {changed}   (rows with a Remark: {remarks})")
    for c in ("merge_method", "Collection", "merge_add_columns"):
        print(f"  {c:<18} {per_col[c]:>6}")
    print("\nby decided_by / batch:")
    for (who, b), k in sorted(by_who.items(), key=lambda x: -x[1]):
        print(f"  {k:6d}  {who:<16} {b}")
    print("\nmerge_method transitions:")
    for (a, b), k in trans.most_common():
        print(f"  {k:6d}  {a} -> {b}")


# ── load ─────────────────────────────────────────────────────────────────────

def read_decisions(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    need = {"source_collection", "members", "merge_method", "Collection",
            "merge_add_columns", "Remark", "confidence", "rationale"}
    missing = need - set(rows[0].keys() if rows else need)
    if missing:
        sys.exit(f"{path}: missing columns {sorted(missing)}")
    out = []
    for r in rows:
        d = {k: (v or "").strip() for k, v in r.items() if k}
        if r.get(None):       # unquoted commas in the last column spill into extra fields
            d["rationale"] = ",".join([d.get("rationale", "")] + [x or "" for x in r[None]])
        # tolerate the separators agents actually write: 'G1;G2', 'year;sex', '-'
        if re.fullmatch(r"G\d+(\s*[;,]\s*G\d+)*", d["members"]):
            d["members"] = re.sub(r"\s*[;,]\s*", ",", d["members"])
        mac = re.sub(r"\s*[;,]\s*", ",", d["merge_add_columns"])
        d["merge_add_columns"] = "" if mac in ("-", "none", "None", "NULL") else mac
        for k in ("Collection", "Remark"):
            if d.get(k) in ("-",):
                d[k] = ""
        out.append(d)
    return out


def expand(decisions, pack):
    """-> ({nid: decision index}, [errors]). Enforces exactly-once coverage."""
    errors, owner = [], {}
    colls = (pack or {}).get("collections", {})
    groups = {}
    for c, info in colls.items():
        for g, nids in info.get("groups", {}).items():
            groups[g] = (c, nids)

    def claim(nid, i):
        if nid in owner and owner[nid] != i:
            errors.append(f"nid {nid} claimed by decision rows {owner[nid] + 2} and {i + 2}")
        owner[nid] = i

    # agents may name a source collection by its pack heading id (C1, C2 ...);
    # the pack json keeps collections in heading order
    order = list(colls)
    for d in decisions:
        m = re.fullmatch(r"C(\d+)", d["source_collection"])
        if m and d["source_collection"] not in colls and 0 < int(m.group(1)) <= len(order):
            d["source_collection"] = order[int(m.group(1)) - 1]

    rest_rows = []
    for i, d in enumerate(decisions):
        spec, src = d["members"], d["source_collection"]
        if spec.startswith("nid:"):
            for nid in re.split(r"[;,\s]+", spec[4:]):
                if nid:
                    claim(nid, i)
        elif spec == "all":
            if src not in colls:
                errors.append(f"row {i + 2}: 'all' but {src!r} is not in the pack")
                continue
            for nid in colls[src]["nids"]:
                claim(nid, i)
        elif spec == "rest":
            rest_rows.append(i)
        elif re.fullmatch(r"G\d+(\s*,\s*G\d+)*", spec):
            for g in re.split(r"\s*,\s*", spec):
                if g not in groups:
                    errors.append(f"row {i + 2}: unknown group {g}")
                    continue
                gc, nids = groups[g]
                if src and src != gc:
                    errors.append(f"row {i + 2}: {g} belongs to {gc!r}, not {src!r}")
                for nid in nids:
                    claim(nid, i)
        else:
            errors.append(f"row {i + 2}: bad members spec {spec!r}")
    for i in rest_rows:
        src = decisions[i]["source_collection"]
        if src not in colls:
            errors.append(f"row {i + 2}: 'rest' but {src!r} is not in the pack")
            continue
        for nid in colls[src]["nids"]:
            if nid not in owner:
                owner[nid] = i
    # coverage: every member of every pack collection exactly once
    for c, info in colls.items():
        miss = [n for n in info["nids"] if n not in owner]
        if miss:
            errors.append(f"{len(miss)} member(s) of {c[:80]!r} have no decision, e.g. {miss[:5]}")
    return owner, errors


def cmd_load(con, args):
    decisions = read_decisions(args.csv)
    pack = json.loads(Path(args.pack).read_text()) if args.pack else None
    allowed = ALL_METHODS if args.allow_methods == "all" else METHODS
    owner, errors = expand(decisions, pack)
    warnings = []

    for i, d in enumerate(decisions):
        r = i + 2
        mm, coll = d["merge_method"], d["Collection"]
        if mm not in allowed:
            errors.append(f"row {r}: merge_method {mm!r} not allowed")
        if mm in ("change_in_header", "curate", "direct") and not coll:
            errors.append(f"row {r}: {mm} needs a Collection")
        if mm in ("non-mergeable", "to be removed") and coll:
            errors.append(f"row {r}: {mm} must have a blank Collection")
        if coll and SCHEMA_N.search(coll):
            errors.append(f"row {r}: '(schema N)' in name {coll!r}")
        if d["confidence"] and d["confidence"] not in CONFIDENCE:
            errors.append(f"row {r}: confidence {d['confidence']!r}")
        mac = d["merge_add_columns"]
        if mac:
            toks = [t.strip() for t in mac.split(",")]
            bad = [t for t in toks if not re.fullmatch(r"[a-z][a-z0-9_]*", t)]
            if bad:
                errors.append(f"row {r}: mac tokens must be snake_case: {bad}")
            if "review" in toks:
                errors.append(f"row {r}: 'review' in merge_add_columns")
            new = [t for t in toks if t not in VOCAB and t not in bad]
            if new:
                warnings.append(f"row {r}: new mac token(s) {new}")
            if mm in ("non-mergeable", "to be removed"):
                errors.append(f"row {r}: {mm} rows take no merge_add_columns")

    nids = sorted(owner)
    cur = {}
    if nids:
        con.execute("CREATE OR REPLACE TEMP TABLE _nids(nid VARCHAR)")
        con.executemany("INSERT INTO _nids VALUES (?)", [(n,) for n in nids])
        for row in con.execute(f"""
                SELECT w.nid, w.merge_method, w."Collection", w.merge_add_columns, w.Remark,
                       w.locked, w.Title, w.batch, d."Conforms To"
                FROM {WORK} w JOIN _nids USING (nid)
                LEFT JOIN {MAIN} d ON CAST(d.nid AS VARCHAR) = w.nid""").fetchall():
            cur[row[0]] = row
    unknown = [n for n in nids if n not in cur]
    if unknown:
        errors.append(f"{len(unknown)} nid(s) not in {WORK}: {unknown[:5]}")
    locked = [n for n in nids if n in cur and cur[n][5]]
    if locked and not args.allow_locked:
        errors.append(f"{len(locked)} locked (user-edited) row(s) touched: {locked[:5]}")
    other_batch = [n for n in nids if n in cur and cur[n][7] and cur[n][7] not in
                   (args.batch, "user_xlsx") and not args.allow_locked]
    if other_batch:
        errors.append(f"{len(other_batch)} row(s) already decided by another batch: "
                      f"{sorted({cur[n][7] for n in other_batch})} e.g. {other_batch[:5]}")

    # mac against header columns, name span
    by_dec = defaultdict(list)
    for nid, i in owner.items():
        by_dec[i].append(nid)
    for i, members in by_dec.items():
        d = decisions[i]
        toks = {t.strip() for t in d["merge_add_columns"].split(",") if t.strip()}
        if toks:
            hd = set()
            for n in members:
                h = cur.get(n, [None] * 9)[8]
                if h:
                    hd |= header_dims(h) | augment_header_dims(h)
            clash = toks & hd
            if clash:
                warnings.append(f"row {i + 2}: mac {sorted(clash)} already a header column")
        if d["Collection"]:
            years = {y for n in members for y in YEAR.findall(cur.get(n, [None] * 7)[6] or "")}
            if len(years) > 1 and not SPAN.search(d["Collection"]) and len(members) > 1:
                warnings.append(f"row {i + 2}: members span {min(years)}-{max(years)} but the "
                                f"name has no 'from ... to ...': {d['Collection'][:70]!r}")

    # state after this batch, for collection-level checks
    after = {n: (decisions[i]["merge_method"], decisions[i]["Collection"] or None)
             for n, i in owner.items()}
    names = {c for _, c in after.values() if c}
    if names:
        con.execute("CREATE OR REPLACE TEMP TABLE _names(c VARCHAR)")
        con.executemany("INSERT INTO _names VALUES (?)", [(c,) for c in names])
        existing = con.execute(f"""
            SELECT w.nid, w.merge_method, w."Collection" FROM {WORK} w
            JOIN _names ON lower(w."Collection") = lower(_names.c)""").fetchall()
        size = Counter(c for _, c in after.values() if c)
        mms = defaultdict(set)
        for mm, c in after.values():
            if c:
                mms[c].add(mm)
        lower_names = defaultdict(set)
        for nid, mm, c in existing:
            if nid in after:
                continue          # being moved by this batch
            lower_names[c.lower()].add(c)
            for n in names:
                if n.lower() == c.lower():
                    size[n] += 1
                    mms[n].add(mm)
                    if n != c:
                        errors.append(f"name differs only in case from existing {c!r}: {n!r}")
        for n in names:
            joined = sum(1 for nid, mm, c in existing if c.lower() == n.lower() and nid not in after)
            if joined:
                warnings.append(f"{n[:80]!r} joins an existing collection ({joined} other rows)")
            if size[n] < 2:
                errors.append(f"collection would have 1 member: {n[:90]!r}")
            if len(mms[n]) > 1:
                errors.append(f"collection spans merge_methods {sorted(mms[n])}: {n[:80]!r}")
        # members left behind in collections this batch is emptying
        left = con.execute(f"""
            SELECT w."Collection", count(*) FROM {WORK} w
            WHERE w."Collection" IN (SELECT DISTINCT orig FROM (
                  SELECT w2."Collection" AS orig FROM {WORK} w2 JOIN _nids USING (nid)))
              AND w.nid NOT IN (SELECT nid FROM _nids)
            GROUP BY 1""").fetchall()
        for c, k in left:
            if k == 1:
                warnings.append(f"1 row left alone in {c[:80]!r}")

    tr = Counter((cur[n][1], after[n][0]) for n in nids if n in cur)
    conf = Counter(decisions[i]["confidence"] or "?" for i in owner.values())
    print(f"decision rows: {len(decisions)}   nids: {len(nids)}   "
          f"new/joined collections: {len(names)}")
    print("merge_method transitions: " + ", ".join(f"{a}->{b}: {k}" for (a, b), k in tr.most_common()))
    print("confidence (rows): " + ", ".join(f"{k}={v}" for k, v in conf.most_common()))
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if errors:
        sys.exit(f"{len(errors)} error(s); nothing written")
    if not args.apply:
        print("[dry-run] valid; re-run with --apply to write")
        return

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = DATA_DIR / "backups" / f"{WORK}_{args.batch}_{ts}.csv"
    snap.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT * FROM {WORK} WHERE nid IN (SELECT nid FROM _nids)) "
                f"TO '{snap}' (HEADER, DELIMITER ',')")
    con.execute("CREATE OR REPLACE TEMP TABLE _dec(nid VARCHAR, mm VARCHAR, coll VARCHAR, "
                "mac VARCHAR, remark VARCHAR, conf VARCHAR, why VARCHAR)")
    con.executemany("INSERT INTO _dec VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (n, decisions[i]["merge_method"], decisions[i]["Collection"] or None,
         normalise_mac(decisions[i]["merge_add_columns"]), decisions[i]["Remark"] or None,
         decisions[i]["confidence"] or None, decisions[i]["rationale"] or None)
        for n, i in owner.items()])
    who = args.decided_by
    con.execute(f"""
        UPDATE {WORK} AS w SET merge_method = t.mm, "Collection" = t.coll,
               merge_add_columns = t.mac,
               -- a merge instruction means nothing on a row that is no longer merged
               Remark = CASE WHEN t.mm IN ('non-mergeable', 'to be removed') THEN t.remark
                             ELSE coalesce(t.remark, w.Remark) END,
               confidence = t.conf, rationale = t.why, batch = ?,
               decided_by = CASE WHEN w.locked THEN w.decided_by || '+{who}' ELSE '{who}' END,
               updated_at = now()
        FROM _dec AS t WHERE w.nid = t.nid""", [args.batch])
    bad = con.execute(f"""SELECT count(*) FROM {WORK} w JOIN _dec t USING (nid)
                          WHERE w.merge_method IS DISTINCT FROM t.mm
                             OR w."Collection" IS DISTINCT FROM t.coll
                             OR w.merge_add_columns IS DISTINCT FROM t.mac""").fetchone()[0]
    print(f"wrote {len(owner)} rows (batch {args.batch}); snapshot {snap}")
    if bad:
        sys.exit(f"{bad} rows do not read back; revert from {snap}")


# ── review workbook ──────────────────────────────────────────────────────────

REVIEW_ROW_COLS = ["nid", "Title", "ministry", "orig_merge_method", "orig_Collection",
                   "orig_merge_add_columns", "merge_method", "Collection",
                   "merge_add_columns", "Remark", "confidence", "decided_by", "batch",
                   "rationale"]


def cmd_export_review(con, args):
    """
    Sheet 1 'rows' (active, edit here: merge_method / Collection /
    merge_add_columns / Remark, then import it back with import_edited_export.py
    --table collection_worktable); sheet 2 'collections' (one line per resulting
    collection, low confidence first); sheet 3 'flags' (--flags csv, optional).
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    rows = con.execute(f"""
        SELECT {", ".join(q(c) for c in REVIEW_ROW_COLS)} FROM {WORK}
        WHERE batch IS NOT NULL {"AND batch <> 'user_xlsx'" if args.skip_user else ""}
        ORDER BY "Collection" NULLS LAST, merge_method, Title""").fetchall()
    rank = {"low": 0, "medium": 1, "high": 2}
    coll = defaultdict(list)
    for r in rows:
        key = r[7] or f"({r[6]})"
        coll[key].append(r)

    def span(rs):
        ys = sorted({int(y) for r in rs for y in YEAR.findall(r[1] or "")})
        return f"{ys[0]}-{ys[-1]}" if len(ys) > 1 else (str(ys[0]) if ys else "")

    summary = []
    for name, rs in coll.items():
        confs = [r[10] for r in rs if r[10]]
        worst = min(confs, key=lambda c: rank.get(c, 3)) if confs else ""
        summary.append([
            worst, name, Counter(r[6] for r in rs).most_common(1)[0][0], len(rs),
            "; ".join(f"[{k}] {c}" for c, k in Counter(r[4] or f"({r[3]})" for r in rs).most_common(6)),
            span(rs), ", ".join(sorted({r[8] or "-" for r in rs})),
            ", ".join(sorted({r[12] or "" for r in rs})), ", ".join(sorted({r[11] or "" for r in rs})),
            " || ".join(sorted({r[13] for r in rs if r[13]}))[:1500],
            " || ".join(sorted({r[1] for r in rs})[:4]),
        ])
    summary.sort(key=lambda s: (rank.get(s[0], 3), s[1]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "rows"
    ws.append(REVIEW_ROW_COLS)
    for r in rows:
        ws.append(list(r))
    ws2 = wb.create_sheet("collections")
    ws2.append(["worst_confidence", "Collection (or merge_method)", "merge_method", "n_rows",
                "came from (orig collection)", "years in titles", "merge_add_columns",
                "batches", "decided_by", "rationale", "sample titles"])
    for s in summary:
        ws2.append(s)
    if args.flags and Path(args.flags).exists():
        ws3 = wb.create_sheet("flags")
        with open(args.flags, newline="", encoding="utf-8") as fh:
            for rec in csv.reader(fh):
                ws3.append(rec)
    fill = PatternFill("solid", fgColor="DDEBF7")
    for sh, widths in ((ws, {"B": 70, "E": 50, "H": 50, "N": 60}),
                       (ws2, {"B": 70, "E": 60, "J": 80, "K": 80})):
        for c in sh[1]:
            c.font = Font(bold=True)
            c.fill = fill
        sh.freeze_panes = "A2"
        sh.auto_filter.ref = sh.dimensions
        for col, w in widths.items():
            sh.column_dimensions[col].width = w
    for row in ws2.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=False, vertical="top")
    wb.save(args.out)
    print(f"wrote {args.out}: {len(rows)} rows, {len(summary)} collections/groups")


# ── apply to dublin_core_remaining ───────────────────────────────────────────

def cmd_apply(con, args):
    cols = ["merge_method", "Collection", "merge_add_columns"]
    has_remark = con.execute("SELECT count(*) FROM information_schema.columns WHERE "
                             "table_name = ? AND column_name = 'Remark'", [MAIN]).fetchone()[0]
    rows = con.execute(f"""
        SELECT w.nid, w.merge_method, w."Collection", w.merge_add_columns, w.Remark,
               d.merge_method, d."Collection", d.merge_add_columns,
               {'d.Remark' if has_remark else 'NULL'}
        FROM {WORK} w JOIN {MAIN} d ON CAST(d.nid AS VARCHAR) = w.nid""").fetchall()
    changes = [r for r in rows if r[1:5] != r[5:9]]
    trans = Counter((r[5], r[1]) for r in changes if r[1] != r[5])
    print(f"rows to write: {len(changes)}  (Remark column in {MAIN}: {'yes' if has_remark else 'will be added'})")
    for c, i in zip(cols + ["Remark"], range(1, 5)):
        print(f"  {c:<18} {sum(1 for r in changes if r[i] != r[i + 4]):>6}")
    for (a, b), k in trans.most_common():
        print(f"  {k:6d}  {a} -> {b}")

    # invariants on the work table as it would land
    problems = []
    for mm in ("non-mergeable", "to be removed"):
        n = sum(1 for r in changes if r[1] == mm and (r[2] or r[3]))
        if n:
            problems.append(f"{n} {mm} rows carry a Collection or mac")
    n = sum(1 for r in changes if r[2] and SCHEMA_N.search(r[2]))
    if n:
        problems.append(f"{n} rows keep a '(schema N)' name")
    touched = {r[2] for r in changes if r[2]}
    if touched:
        con.execute("CREATE OR REPLACE TEMP TABLE _tc(c VARCHAR)")
        con.executemany("INSERT INTO _tc VALUES (?)", [(c,) for c in touched])
        for c, k, mms in con.execute(f"""
                SELECT "Collection", count(*), list(DISTINCT merge_method) FROM {WORK}
                WHERE "Collection" IN (SELECT c FROM _tc) GROUP BY 1""").fetchall():
            if k < 2:
                problems.append(f"1-member collection: {c[:90]!r}")
            if len(mms) > 1:
                problems.append(f"collection spans {sorted(mms)}: {c[:80]!r}")
    review_left = con.execute(f"""SELECT count(*) FROM {WORK} WHERE merge_method='change_in_header'
                                  AND merge_add_columns='review'""").fetchone()[0]
    print(f"change_in_header rows still with mac 'review' (undecided): {review_left}")
    for p in problems:
        print(f"  PROBLEM {p}")
    if problems and not args.force:
        sys.exit(f"{len(problems)} problem(s); fix them in the work table first (or --force)")
    if not args.apply:
        print("[dry-run] re-run with --apply to write dublin_core_remaining")
        return

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = DATA_DIR / "backups" / f"{MAIN}_worktable_apply_{ts}.csv"
    snap.parent.mkdir(parents=True, exist_ok=True)
    rcol = ", Remark" if has_remark else ""
    con.execute(f'COPY (SELECT nid, merge_method, "Collection", merge_add_columns{rcol} FROM {MAIN}) '
                f"TO '{snap}' (HEADER, DELIMITER ',')")
    print(f"snapshot: {snap}")
    before = con.execute(f"SELECT count(*) FROM {MAIN}").fetchone()[0]
    if not has_remark:
        con.execute(f"ALTER TABLE {MAIN} ADD COLUMN Remark VARCHAR")
    con.execute("CREATE OR REPLACE TEMP TABLE _apply(nid VARCHAR, mm VARCHAR, coll VARCHAR, "
                "mac VARCHAR, remark VARCHAR)")
    con.executemany("INSERT INTO _apply VALUES (?, ?, ?, ?, ?)", [r[:5] for r in changes])
    con.execute(f"""UPDATE {MAIN} AS d SET merge_method = t.mm, "Collection" = t.coll,
                    merge_add_columns = t.mac, Remark = t.remark
                    FROM _apply AS t WHERE CAST(d.nid AS VARCHAR) = t.nid""")
    after = con.execute(f"SELECT count(*) FROM {MAIN}").fetchone()[0]
    bad = con.execute(f"""SELECT count(*) FROM {MAIN} d JOIN _apply t ON CAST(d.nid AS VARCHAR) = t.nid
                          WHERE d.merge_method IS DISTINCT FROM t.mm OR d."Collection" IS DISTINCT FROM t.coll
                             OR d.merge_add_columns IS DISTINCT FROM t.mac
                             OR d.Remark IS DISTINCT FROM t.remark""").fetchone()[0]
    print(f"wrote {len(changes)} rows to {MAIN}")
    if after != before or bad:
        sys.exit(f"INVARIANT FAILURE: rows {before}->{after}, {bad} rows do not read back; "
                 f"revert from {snap}")
    print("row count unchanged, every row reads back.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("lock-user")
    p.add_argument("--apply", action="store_true")
    sub.add_parser("diff")
    p = sub.add_parser("load")
    p.add_argument("csv")
    p.add_argument("--batch", required=True)
    p.add_argument("--pack", default=None, help="the batch's pack .json (for all/rest/G specs)")
    p.add_argument("--decided-by", default="agent")
    p.add_argument("--allow-locked", action="store_true", help="cleanup batches only")
    p.add_argument("--allow-methods", default="cih", choices=["cih", "all"])
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("export-review")
    p.add_argument("--out", default=str(HERE.parent / "collection_worktable_review.xlsx"))
    p.add_argument("--flags", default=None, help="csv of items for the user (sheet 3)")
    p.add_argument("--skip-user", action="store_true", help="leave out rows only the user decided")
    p = sub.add_parser("apply")
    p.add_argument("--force", action="store_true", help="write despite reported problems")
    p.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    writes = args.cmd in ("create",) or getattr(args, "apply", False)
    con = duckdb.connect(args.db, read_only=not writes)
    try:
        {"create": cmd_create, "lock-user": cmd_lock_user, "diff": cmd_diff,
         "load": cmd_load, "export-review": cmd_export_review,
         "apply": cmd_apply}[args.cmd](con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
