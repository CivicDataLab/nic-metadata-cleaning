#!/usr/bin/env python3
"""
Fill new_unmerged_dataset_description on dublin_core_metadata (lot 1).

Description is written per collection: every member of a collection carries
the same text, with the collection's span of financial years. This column is
the same text made to describe the one dataset.

data/dataset_description_templates.csv holds one template per (Collection,
Description) pair, with one slot:

  {period}  item-wise HMIS collections, whose members differ only by month and
            financial year. Filled from the dataset's own title:
              "... for January-2018-19"  ->  January 2019 (FY 2018-19)
              "... upto February-2018-19" ->  April 2018 to February 2019 (FY 2018-19)
  {title}   every other collection (members differ by state, district,
            indicator and period). Filled with new_unmerged_dataset_title.

A dataset whose (Collection, Description) pair has no template keeps its
Description as it is: those are the datasets in no collection, whose
description was already written for them alone.

Description and every other column are left untouched. The column is added if
the table does not have it yet. Re-running rewrites it from the CSV. The table
is filled in one transaction and checked before the commit. No snapshot is
written.

Usage:
  python3 fill_new_unmerged_dataset_description.py --dry-run
  python3 fill_new_unmerged_dataset_description.py
"""

import argparse
import os
import re
import sys

import duckdb
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(REPO, "transformation", "metadata.db")
TEMPLATES = os.path.join(REPO, "data", "dataset_description_templates.csv")
TABLE = "dublin_core_metadata"
COL = "new_unmerged_dataset_description"

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
TITLE_PERIOD = re.compile(
    r"\b(for|upto|up to)\s+([A-Za-z]{3,9})\s*[-,]?\s*((?:19|20)\d{2})\s?[-–]\s?(\d{2}|\d{4})\s*$", re.I)


def period_from_title(title: str) -> str | None:
    """The period an item-wise title names, in words; None if it names none."""
    m = TITLE_PERIOD.search(title or "")
    if not m:
        return None
    month = next((i for i, name in enumerate(MONTHS) if name.lower().startswith(m.group(2).lower()[:3])), None)
    start = int(m.group(3))
    if month is None or int(m.group(4)[-2:]) != (start + 1) % 100:
        return None
    fy = f"FY {start}-{str(start + 1)[2:]}"
    year = start if month >= 3 else start + 1          # the financial year runs April to March
    if m.group(1).lower() == "for":
        return f"{MONTHS[month]} {year} ({fy})"
    if month == 3:
        return f"April {start} ({fy})"
    return f"April {start} to {MONTHS[month]} {year} ({fy})"


def build(rows: pd.DataFrame, templates: pd.DataFrame) -> pd.DataFrame:
    """rows + the new description and how it was made (rule / haiku / fix / as is)."""
    rows = rows.assign(Collection=rows["Collection"].fillna(""))
    out = rows.merge(templates, on=["Collection", "Description"], how="left", validate="many_to_one")
    title = out["title"].str.strip().str.rstrip(".")
    period = title.map(period_from_title)

    new, problems = [], []
    for nid, desc, tpl, slot, t, p in zip(out["nid"], out["Description"], out["template"], out["slot"], title, period):
        if pd.isna(tpl):
            new.append(desc)
        elif slot == "period":
            if p is None:
                problems.append(f"nid {nid}: no period in title {t!r}")
            new.append(tpl.replace("{period}", p or ""))
        else:
            new.append(tpl.replace("{title}", t))
    out[COL] = new
    out["method"] = out["method"].fillna("as is")
    for text, nid in zip(out[COL], out["nid"]):
        if not isinstance(text, str) or not text.strip() or "{" in text or "}" in text:
            problems.append(f"nid {nid}: empty or unfilled description")
    if problems:
        sys.exit(f"{len(problems)} rows cannot be filled, nothing written:\n  " + "\n  ".join(problems[:15]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--templates", default=TEMPLATES)
    ap.add_argument("--dry-run", action="store_true", help="build and check the descriptions, write nothing")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="print N filled rows (old and new)")
    args = ap.parse_args()

    templates = pd.read_csv(args.templates, dtype=str, keep_default_na=False)
    bad = templates[~templates.apply(lambda r: r["template"].count("{" + r["slot"] + "}") == 1
                                     and len(re.findall(r"[{}]", r["template"])) == 2, axis=1)]
    dupes = int(templates.duplicated(["Collection", "Description"]).sum())
    print(f"{os.path.basename(args.templates)}: {len(templates)} templates -",
          templates.groupby(["slot", "method"]).size().to_dict())
    if len(bad) or dupes:
        sys.exit(f"{len(bad)} templates without exactly one slot, {dupes} (Collection, Description) pairs listed twice - nothing written")

    con = duckdb.connect(args.db, read_only=args.dry_run)
    cols = [r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()]
    rows = con.execute(f"""SELECT nid, coalesce(new_unmerged_dataset_title, "Title") AS title,
                                  "Collection", "Description" FROM {TABLE}""").fetchdf()
    n = len(rows)
    filled = build(rows, templates)
    assert len(filled) == n and filled["nid"].is_unique, "nid is not unique"
    unused = len(templates) - filled.dropna(subset=["template"]).drop_duplicates(["Collection", "Description"]).shape[0]
    changed = int((filled[COL] != filled["Description"]).sum())
    words = filled[COL].str.split().str.len()
    print(f"{TABLE}: {n} rows; by method {filled['method'].value_counts().to_dict()}")
    print(f"  {changed} descriptions differ from Description, {n - changed} kept as they are; "
          f"{unused} templates match no row; words mean {words.mean():.1f}, min {words.min()}, max {words.max()}")
    if args.sample:
        for r in filled.sample(args.sample, random_state=7).itertuples():
            print(f"\n  [{r.nid} | {r.method}] {r.title}\n    OLD: {r.Description}\n    NEW: {getattr(r, COL)}")
    if args.dry_run:
        return

    if COL not in cols:
        # DuckDB cannot UPDATE a table altered in the same transaction: add, then fill.
        con.execute(f"ALTER TABLE {TABLE} ADD COLUMN {COL} VARCHAR")
        print(f"  column {COL} added")
    before = con.execute(f"SELECT bit_xor(hash(t)) FROM (SELECT * EXCLUDE ({COL}) FROM {TABLE}) t").fetchone()[0]
    new = filled[["nid", COL]].rename(columns={COL: "new_description"})
    con.register("new", new)
    con.execute("BEGIN")
    try:
        con.execute(f"UPDATE {TABLE} t SET {COL} = new.new_description FROM new WHERE new.nid = t.nid")
        got, wrong = con.execute(f"""
            SELECT count(t.{COL}), count(*) FILTER (WHERE t.{COL} IS DISTINCT FROM new.new_description)
            FROM {TABLE} t LEFT JOIN new ON new.nid = t.nid""").fetchone()
        after = con.execute(f"SELECT bit_xor(hash(t)) FROM (SELECT * EXCLUDE ({COL}) FROM {TABLE}) t").fetchone()[0]
        assert got == n and wrong == 0, (got, wrong, n)
        assert after == before, "another column changed"
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("CHECKPOINT")
    con.close()
    print(f"  {COL}: {got} rows filled; other columns unchanged")


if __name__ == "__main__":
    main()
