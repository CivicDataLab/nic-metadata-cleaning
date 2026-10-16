#!/usr/bin/env python3
"""
Put dublin_core_lot3.new_catalog_title on the catalog rows of remaining_catalog.

remaining_catalog holds the catalogs of lot 2 and lot 3. The lot 2 rows already
carry their new_catalog_title; the lot 3 rows are the ones left blank. A catalog
row gets the name its datasets have in dublin_core_lot3, matched on the catalog
title ("Relation[Catalog Title]" = remaining_catalog.title, whitespace
normalised, case kept).

  * A blank row takes the name of the lot 3 catalog with its title. Where one
    title has two names (the same title in two states), the state decides.
  * A row that already has a name is left alone, with one exception: the lot 2
    names were matched ignoring case, so a few lot 3 catalogs got the name of a
    lot 2 catalog that only shares their title ("Health Infrastructure" of
    Sikkim -> "Health Infrastructure : Pimpri Chinchwad"). Such a row is
    recognised by its owner -- a State row, or a Central row of the same
    ministry as the lot 3 catalog -- and gets the lot 3 name. Its
    generated_sector / generated_description were written for the other
    catalog, so they are cleared and llm_catalog_classifier_remaining.py will
    generate them again.

Rows of neither lot stay blank. No snapshot is written; the update is one
transaction with the counts checked before the commit. Idempotent.

Usage:
  python3 fill_remaining_catalog_from_lot3.py --dry-run
  python3 fill_remaining_catalog_from_lot3.py
"""

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "metadata.db"
CATALOGS = "remaining_catalog"
LOT3 = "dublin_core_lot3"


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def first(s, sep):
    return norm(re.split(sep, s or "")[0])


def plan(con):
    l3 = con.execute(f'''
        SELECT DISTINCT "Relation[Catalog Title]" AS cat, new_catalog_title AS name, Jurisdiction AS govt,
               "Publisher[ministry_department]" AS pub, "Publisher[state_department]" AS spub
        FROM {LOT3}''').df()
    l3["t"] = l3.cat.map(norm)
    # the ministry of a Central catalog, the state of a State one
    l3["top"] = [first(p, r"[,|]") if norm(p) else first(s, ",") for p, s in zip(l3.pub, l3.spub)]
    by_title = {t: g[["name", "govt", "top"]].drop_duplicates().to_dict("records") for t, g in l3.groupby("t")}

    rc = con.execute(f'''
        SELECT nid, title, new_catalog_title AS cur, field_ds_govt_type AS govt,
               "field_asset_jurisdiction:name" AS place, "field_ministry_department:name" AS ministry
        FROM {CATALOGS}''').df()
    rc["t"] = rc.title.map(norm)
    rc["cur"] = rc.cur.map(lambda x: norm(x) or None)

    fill, fix, undecided = [], [], []
    for r in rc.itertuples():
        cands = by_title.get(r.t)
        if not cands:
            continue
        if r.cur is None:
            names = {c["name"] for c in cands}
            if len(names) > 1:
                names = {c["name"] for c in cands if c["top"] == norm(r.place)}
            if len(names) == 1:
                fill.append((r.nid, names.pop()))
            else:
                undecided.append((r.nid, r.t))
            continue
        own = [c for c in cands if c["govt"] == r.govt
               and (r.govt == "State" or c["top"] == first(r.ministry, ";"))]
        names = {c["name"] for c in own}
        if len(names) == 1 and names != {r.cur}:
            fix.append((r.nid, names.pop(), r.cur))
    return rc, by_title, fill, fix, undecided


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=args.dry_run)
    rc, by_title, fill, fix, undecided = plan(con)

    blank = int(rc.cur.isna().sum())
    in_rc = set(rc.t)
    print(f"{CATALOGS}: {len(rc)} rows, {len(rc) - blank} named, {blank} blank")
    print(f"lot 3 catalog titles: {len(by_title)}; with no row in {CATALOGS}: "
          f"{sum(t not in in_rc for t in by_title)}")
    print(f"blank rows to fill: {len(fill)}  ({len({n for _, n in fill})} names)")
    print(f"named rows to correct: {len(fix)}")
    for nid, new, cur in fix:
        print(f"   nid {nid}: {cur!r} -> {new!r}")
    print(f"blank rows left blank: {blank - len(fill)}  (ambiguous title: {len(undecided)})")
    if args.dry_run or not (fill or fix):
        return

    upd = pd.DataFrame([(n, name, False) for n, name in fill] + [(n, name, True) for n, name, _ in fix],
                       columns=["nid", "name", "regen"])
    assert upd.nid.is_unique
    con.register("upd_df", upd)
    con.execute("CREATE TEMP TABLE upd AS SELECT * FROM upd_df")
    before = con.execute(f"""SELECT count(*), count(NULLIF(trim(new_catalog_title), '')),
                                    count(generated_description) FROM {CATALOGS}""").fetchone()
    con.execute("BEGIN")
    try:
        con.execute(f"""UPDATE {CATALOGS} c SET
                new_catalog_title = u.name,
                generated_sector = CASE WHEN u.regen THEN NULL ELSE c.generated_sector END,
                generated_description = CASE WHEN u.regen THEN NULL ELSE c.generated_description END
            FROM upd u WHERE c.nid = u.nid""")
        after = con.execute(f"""SELECT count(*), count(NULLIF(trim(new_catalog_title), '')),
                                       count(generated_description) FROM {CATALOGS}""").fetchone()
        wrong = con.execute(f"""SELECT count(*) FROM {CATALOGS} c JOIN upd u USING (nid)
                                WHERE c.new_catalog_title IS DISTINCT FROM u.name""").fetchone()[0]
        assert after[0] == before[0] and after[1] == before[1] + len(fill), (before, after)
        assert after[2] >= before[2] - len(fix) and wrong == 0, (before, after, wrong)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    con.close()
    print(f"updated {len(upd)} rows; named rows {before[1]} -> {after[1]}; "
          f"generated descriptions {before[2]} -> {after[2]}")


if __name__ == "__main__":
    main()
