#!/usr/bin/env python3
"""
Apply the hand-filled collection_review workbook to dublin_core_remaining.

Input is the workbook detect_collection_defects.py wrote, with these columns
filled in by hand:

  action                 rename | rename+addcol | addcol | split | keep
                         (addcol keeps the name, only sets merge_add_columns)
                         A split destination written '!<merge_method>', e.g.
                         '!non-mergeable', takes those members out of every
                         collection and sets their merge_method.
                         --merge-method change_in_header reads
                         collection_review_change_in_header.xlsx instead.
  new_collection_name    the name every member should carry (rename*, split
                         uses it as the stem for the catch-all clause)
  new_merge_add_columns  comma list, in the pipeline's order
                         year,state,district,month,quarter then any categorical
                         dimension; blank clears the value
  split_rule             only for action=split -- ordered clauses
                             <regex> => <collection name> [| <merge_add_columns>]
                         separated by ';;', first match on the Title wins. A
                         clause whose pattern is '*' is the catch-all and must
                         come last. Members matching no clause are left alone
                         and reported as unmatched (the run then aborts unless
                         --allow-unmatched).
                         The optional '| <merge_add_columns>' overrides
                         new_merge_add_columns for that destination only, which
                         is what a split by census year needs: once the halves
                         are separated, year no longer varies inside either, and
                         the half whose headers were never extracted has to keep
                         a dimension the other half can drop as already-columnar.

Rows with action=keep, or with no action, are skipped.

Safety, in this order:
  1. Default is --dry-run: the DB is opened read_only=True and only the diff
     is printed. Writing requires --apply.
  2. Every Collection in the workbook must still exist with the same member
     count, else the run aborts -- guards against applying a stale workbook
     after someone else has rewritten collections.
  3. The workbook must be newer than collection_decisions.csv. The workbook is a
     generated artifact -- editing a decision and applying without re-running
     detect_collection_defects.py would silently apply the previous decision.
  4. A logical CSV snapshot of the touched columns goes to
     data/backups/ before any write (the repo convention -- see
     refine_direct_merge_method.py:351). Not a full .bak copy of the 3.4GB DB:
     the drive this lives on runs at ~98%.
  5. The write is one UPDATE ... FROM a bound temp table, not per-row UPDATEs
     (the pattern fill_headers_remaining.py adopted after bulk single-row
     UPDATEs corrupted this database twice).
  6. Post-write invariants are asserted and printed; any failure is reported
     with the snapshot path to revert from.

needs_review is deliberately left alone. In this pipeline it means "headers
still differ after time tokens are stripped", not "a human touched this row";
overloading it would mislead the scripts downstream that read it.

Usage:
  python3 apply_collection_review.py                      # dry-run diff
  python3 apply_collection_review.py --apply
  python3 apply_collection_review.py --only-ministry "Jal Shakti" --apply
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
DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_remaining"
DATA_DIR = HERE.parent.parent / "data"
REVIEW = HERE.parent / "collection_review.xlsx"
DIM_ORDER = ["year", "state", "district", "month", "quarter"]
VALID_ACTIONS = {"rename", "rename+addcol", "addcol", "split", "keep", ""}


def load_review(path: Path) -> list[dict]:
    """Read the filled workbook; .xlsx if openpyxl is there, else the .csv."""
    if path.suffix == ".xlsx" and path.exists():
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        cols = [str(c or "") for c in next(it)]
        out = [dict(zip(cols, ["" if v is None else str(v).strip() for v in row]))
               for row in it]
        wb.close()
        return [r for r in out if r.get("Collection")]
    csv_path = path.with_suffix(".csv")
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("Collection")]


def parse_split_rule(rule: str) -> list[tuple[str, str, str | None]]:
    """'<regex> => <name> [| <mac>] ;; ...' -> ordered [(pattern, name, mac)]."""
    clauses = []
    for raw in rule.split(";;"):
        raw = raw.strip()
        if not raw:
            continue
        if "=>" not in raw:
            raise ValueError(f"split clause missing '=>': {raw!r}")
        pat, rest = raw.split("=>", 1)
        mac = None
        if "|" in rest:
            rest, mac = rest.split("|", 1)
            mac = mac.strip()
        clauses.append((pat.strip(), rest.strip(), mac))
    if not clauses:
        raise ValueError("empty split_rule")
    for pat, _, _ in clauses[:-1]:
        if pat == "*":
            raise ValueError("catch-all '*' clause must come last")
    return clauses


def normalise_mac(value: str) -> str | None:
    """Pipeline order first, then any categorical dimension, alphabetical."""
    dims = [d.strip() for d in (value or "").split(",") if d.strip()]
    if not dims:
        return None
    known = [d for d in DIM_ORDER if d in dims]
    extra = sorted(d for d in dims if d not in DIM_ORDER)
    return ",".join(known + extra)


def build_changes(con, table, review, only_ministry, allow_unmatched,
                  merge_method="curate"):
    """-> (changes {nid: (collection, mac, new merge_method|None)}, report, problems)"""
    wanted = [r for r in review
              if r.get("action", "").strip() in VALID_ACTIONS - {"keep", ""}]
    if only_ministry:
        wanted = [r for r in wanted if only_ministry.lower() in r.get("ministry", "").lower()]

    problems, report, changes = [], [], {}
    for r in wanted:
        coll = r["Collection"]
        action = r["action"].strip()
        members = con.execute(
            f'SELECT nid, "Title", merge_add_columns FROM {table} '
            f'WHERE "Collection" = ? AND merge_method = ?',
            [coll, merge_method],
        ).fetchall()

        if not members:
            problems.append(f"{coll!r}: no longer present with merge_method={merge_method}")
            continue
        expected = int(r.get("n_members") or 0)
        if expected and len(members) != expected:
            problems.append(
                f"{coll!r}: workbook says {expected} members, DB has {len(members)} "
                f"-- workbook is stale, re-run detect_collection_defects.py")
            continue

        mac = normalise_mac(r.get("new_merge_add_columns", ""))

        if action in ("rename", "rename+addcol", "addcol"):
            new_name = coll if action == "addcol" else r.get("new_collection_name", "").strip()
            if not new_name:
                problems.append(f"{coll!r}: action={action} but new_collection_name is blank")
                continue
            for nid, _, _ in members:
                changes[nid] = (new_name, mac, None)
            report.append((coll, action, len(members), {new_name: len(members)}, mac))

        elif action == "split":
            try:
                clauses = parse_split_rule(r.get("split_rule", ""))
            except ValueError as exc:
                problems.append(f"{coll!r}: {exc}")
                continue
            compiled = [(None if p == "*" else re.compile(p, re.I), n, m)
                        for p, n, m in clauses]
            dest = Counter()
            dest_mac = {}
            unmatched = []
            for nid, title, _ in members:
                for pat, name, clause_mac in compiled:
                    if pat is None or pat.search(title or ""):
                        this_mac = normalise_mac(clause_mac) if clause_mac is not None else mac
                        if name.startswith("!"):
                            # "!non-mergeable": the member leaves collections
                            # altogether (error page, unrelated subject)
                            changes[nid] = (None, None, name[1:].strip())
                        else:
                            changes[nid] = (name, this_mac, None)
                        dest[name] += 1
                        dest_mac[name] = this_mac
                        break
                else:
                    unmatched.append(title)
            if unmatched and not allow_unmatched:
                problems.append(
                    f"{coll!r}: {len(unmatched)} member(s) matched no split clause, "
                    f"e.g. {unmatched[0][:90]!r}")
                continue
            shown = ", ".join(sorted({str(m) for m in dest_mac.values()})) or str(mac)
            report.append((coll, action, len(members), dict(dest), shown))

    return changes, report, problems


def snapshot(con, table, path):
    """CSV of the columns this script rewrites, so the change can be reverted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT nid, merge_method, "Collection", merge_add_columns, needs_review
            FROM {table}
        ) TO '{path}' (HEADER, DELIMITER ',')
    """)


def check_invariants(con, table, before, merge_method="curate", demoted=0):
    """Only explicit '!<method>' destinations may move rows. Returns failures."""
    fails = []
    total, in_method, null_coll = con.execute(
        f'''SELECT count(*),
                   count(*) FILTER (WHERE merge_method = ?),
                   count(*) FILTER (WHERE merge_method = ? AND "Collection" IS NULL)
            FROM {table}''', [merge_method, merge_method]
    ).fetchone()
    if total != before["total"]:
        fails.append(f"row count changed: {before['total']} -> {total}")
    expected = before["in_method"] - demoted
    if in_method != expected:
        fails.append(f"{merge_method} row count: expected {expected}, found {in_method}")
    if null_coll > before["null_coll"]:
        fails.append(f"{null_coll - before['null_coll']} {merge_method} rows "
                     f"lost their Collection")

    # change_in_header collections hold several signatures by design
    if merge_method == "curate":
        multi = con.execute(
            f'''SELECT count(*) FROM (
                  SELECT "Collection" FROM {table}
                  WHERE merge_method = 'curate' AND "Conforms To" IS NOT NULL
                  GROUP BY 1 HAVING count(DISTINCT "Conforms To") > 1)'''
        ).fetchone()[0]
        if multi:
            fails.append(f"{multi} collection(s) now hold more than one header signature")

    spread = con.execute(
        f'''SELECT count(*) FROM (
              SELECT "Collection" FROM {table} WHERE merge_method = ?
              GROUP BY 1 HAVING count(DISTINCT coalesce(merge_add_columns,'')) > 1)''',
        [merge_method]
    ).fetchone()[0]
    if spread:
        fails.append(f"{spread} collection(s) carry more than one merge_add_columns value")
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--merge-method", default="curate")
    ap.add_argument("--review", default=None,
                    help="default: collection_review.xlsx for curate, "
                         "collection_review_<merge_method>.xlsx otherwise")
    ap.add_argument("--apply", action="store_true", help="write (default is dry-run)")
    ap.add_argument("--only-ministry", default=None,
                    help="restrict to collections whose ministry contains this")
    ap.add_argument("--allow-unmatched", action="store_true",
                    help="let split members that match no clause keep their collection")
    args = ap.parse_args()

    suffix = "" if args.merge_method == "curate" else f"_{args.merge_method}"
    review_path = Path(args.review) if args.review else \
        HERE.parent / f"collection_review{suffix}.xlsx"
    decisions = HERE.parent / f"collection_decisions{suffix}.csv"
    if decisions.exists() and review_path.exists():
        if decisions.stat().st_mtime > review_path.stat().st_mtime:
            sys.exit(f"{decisions.name} is newer than {review_path.name}.\n"
                     f"The workbook is generated: re-run detect_collection_defects.py "
                     f"first, or the decisions you just edited will not be applied.")
    review = load_review(review_path)
    print(f"review rows : {len(review)}  ({review_path})")

    con = duckdb.connect(args.db, read_only=not args.apply)
    try:
        changes, report, problems = build_changes(
            con, args.table, review, args.only_ministry, args.allow_unmatched,
            args.merge_method)

        if problems:
            print(f"\n{len(problems)} problem(s) -- nothing will be written:")
            for p in problems:
                print(f"  ! {p}")

        acted = Counter(a for _, a, _, _, _ in report)
        print(f"\ncollections to change : {len(report)}  "
              f"({', '.join(f'{k}={v}' for k, v in sorted(acted.items())) or 'none'})")
        print(f"rows to change        : {len(changes)}")

        for coll, action, n, dest, mac in sorted(report, key=lambda x: -x[2]):
            print(f"\n  [{n:4d}] {action}  mac={mac!r}")
            print(f"         FROM {coll[:110]}")
            for name, cnt in sorted(dest.items(), key=lambda x: -x[1]):
                print(f"         ->   [{cnt:4d}] {name[:104]}")

        if problems:
            sys.exit(1)
        if not changes:
            print("\nNothing to do.")
            return
        if not args.apply:
            print("\n[dry-run] No changes written. Re-run with --apply.")
            return

        before = dict(zip(("total", "in_method", "null_coll"), con.execute(
            f'''SELECT count(*), count(*) FILTER (WHERE merge_method = ?),
                       count(*) FILTER (WHERE merge_method = ? AND "Collection" IS NULL)
                FROM {args.table}''', [args.merge_method, args.merge_method]).fetchone()))
        demoted = sum(1 for _, _, mm in changes.values() if mm)

        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        snap = DATA_DIR / "backups" / f"{args.table}_collection_fix_{ts}.csv"
        snapshot(con, args.table, snap)
        print(f"\nPre-update snapshot : {snap}")

        con.execute("DROP TABLE IF EXISTS _tmp_collfix")
        con.execute("CREATE TEMP TABLE _tmp_collfix("
                    "nid VARCHAR, coll VARCHAR, add_cols VARCHAR, mm VARCHAR)")
        con.executemany("INSERT INTO _tmp_collfix VALUES (?, ?, ?, ?)",
                        [(nid, c, m, mm) for nid, (c, m, mm) in changes.items()])
        con.execute(f'''
            UPDATE {args.table} AS d
               SET "Collection" = t.coll,
                   merge_add_columns = t.add_cols,
                   merge_method = coalesce(t.mm, d.merge_method)
              FROM _tmp_collfix AS t
             WHERE d.nid = t.nid
        ''')
        con.execute("DROP TABLE IF EXISTS _tmp_collfix")
        print(f"Updated {len(changes)} rows.")

        fails = check_invariants(con, args.table, before, args.merge_method, demoted)
        if fails:
            print("\nINVARIANT FAILURES:")
            for f in fails:
                print(f"  ! {f}")
            print(f"\nRevert from: {snap}")
            sys.exit(2)
        print("\nAll invariants hold.")

        audit = DATA_DIR / "backups" / f"{args.table}_collection_fix_{ts}_audit.csv"
        with open(audit, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["old_collection", "action", "n_members",
                        "new_collection", "n_moved", "merge_add_columns"])
            for coll, action, n, dest, mac in report:
                for name, cnt in sorted(dest.items()):
                    w.writerow([coll, action, n, name, cnt, mac or ""])
        print(f"Audit : {audit}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
