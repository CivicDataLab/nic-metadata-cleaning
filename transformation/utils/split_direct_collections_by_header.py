"""
Bifurcate `merge_method='direct'` collections that contain more than one set of
headers, following the manual precedent the user set for
"Number of Schools by Availability of Infrastructure and Facilities, School
Management and School Category (UDISE plus)".

Rules (applied to the `direct` category only)
---------------------------------------------
1. Normalise `Conforms To` before counting variants: lower-case, strip
   non-alphanumerics, drop blank fields, dedupe, compare as a SET. This collapses
   trailing commas, case/underscore/spacing differences and repeated column
   names, which are extraction artefacts rather than real schema variants.
2. If the normalised variants differ only by renames/abbreviations of the same
   measures (Total -> Count, DATE -> TRDATE, ...), the collection stays ONE
   collection and keeps merge_method='direct'.
3. If 2-3 normalised variants differ by EXTRA or MISSING indicators, and each
   variant covers a disjoint run of periods, the collection is bifurcated into
   period-named sub-collections.
4. If there are more than 3 normalised variants, the collection is relabelled
   merge_method='change_in_header' (needs_review=true) and left as one collection.

Naming follows the manual precedent, with the period token taken from how the
member titles express time (financial year / calendar year / month):
    "<base> from financial year 2012-13 to 2018-19"
    "<base> in financial year 2019-20"
    "<base> from February 2013 to October 2014"

Rules 2-4 were decided per collection by inspecting the header diffs; the
verdicts live in DECISIONS below so the run is reproducible and auditable.

Usage
-----
    python transformation/utils/split_direct_collections_by_header.py --dry-run
    python transformation/utils/split_direct_collections_by_header.py --apply
"""

import argparse
import csv
import datetime as dt
import os
import re
import shutil
import sys
from collections import defaultdict

import duckdb

DB = os.path.join(os.path.dirname(__file__), "..", "metadata.db")
TABLE = "dublin_core_remaining"

SCHOOLS = ("Number of Schools by Availability of Infrastructure and Facilities, "
           "School Management and School Category (UDISE plus)")
ENROLMENT = ("Enrolment by Location, School Management, School Category and "
             "Social Category (UDISE plus)")
TEACHERS = ("Number of Teachers by Gender, Academic Qualification, Professional "
            "Qualification, Classes Taught, School Category and School Management "
            "(UDISE plus)")
CPI = "All India Consumer Price Index (Rural/Urban)"
AIR = "Location wise daily Ambient Air Quality"

# Per-collection verdicts. For 'split', each rule is
# (marker column present in that variant, suffix) -- the marker is a normalised
# column name that appears in exactly one variant, which is what makes the
# variants distinguishable in the first place.
DECISIONS = {
    SCHOOLS: {
        "verdict": "split",
        "why": "2 variants; 2019-20 adds Boundary_Wall/Single_Class_Room/"
               "Electricity/Boy_Toilet/Girl_Toilet/Toilet_Facility/WASH and drops "
               "School_Type. Manual precedent set by the user.",
        "rules": [("schooltype", "from financial year 2012-13 to 2018-19"),
                  ("boundarywall", "in financial year 2019-20")],
    },
    ENROLMENT: {
        "verdict": "split",
        "why": "3 variants; 2015-16 adds sch_category_id/category_name/"
               "sch_mgmt_id/sch_mgmt_name/loc_name, and 2019-20 adds tr_cat_name "
               "+ school_category on top of that.",
        "rules": [("trcatname", "in financial year 2019-20"),
                  ("categoryname", "from financial year 2015-16 to 2018-19"),
                  (None, "from financial year 2012-13 to 2014-15")],
    },
    TEACHERS: {
        "verdict": "split",
        "why": "2 variants; 2019-20 adds Block_Code/Block_Name.",
        "rules": [("blockcode", "in financial year 2019-20"),
                  (None, "from financial year 2015-16 to 2018-19")],
    },
    CPI: {
        "verdict": "split",
        "why": "2 variants after normalisation (the other 2 were trailing "
               "commas); the new basket adds Egg and drops Others - a real "
               "indicator change, not a rename.",
        "rules": [("egg", "from May 2018 to November 2025"),
                  (None, "from February 2013 to October 2014")],
    },
    AIR: {
        "verdict": "change_in_header",
        "why": "4 distinct variants (Stn Code/Agency added, Location of "
               "Monitoring Station dropped, SPM replaced by PM 2.5) - beyond the "
               "2-3 variant bifurcation rule.",
    },
    "Monthly Coal Statement of Thermal Power Stations (direct merge)": {
        "verdict": "keep",
        "why": "All 4 raw headers are the same 17-column schema. The 68-row "
               "header writes 'Station Name' twice where position 3 should read "
               "'State Name'; the rest differ only by case/underscores/spacing "
               "and DATE vs TRDATE.",
    },
    "Surat Birth Registration Data for Year": {
        "verdict": "keep",
        "why": "Only difference is the last column named Total vs Count - a "
               "rename of the same measure.",
    },
    "Surat Death Registration Data for Year": {
        "verdict": "keep",
        "why": "Only difference is the last column named Total vs Count - a "
               "rename of the same measure.",
    },
}

# Collection renames the user made by hand in dublin_core_remaining.xlsx that are
# not header splits, carried over to the DB unchanged.
MANUAL_RENAMES = {"Town Amenities": "Town Amenities by district 2011"}


def norm_cols(header):
    """Normalised, order-independent column set for a `Conforms To` string."""
    cols = (re.sub(r"[^a-z0-9]", "", c.lower()) for c in (header or "").split(","))
    return frozenset(c for c in cols if c)


def suffix_for(cols, rules):
    """First rule whose marker is in `cols`; a None marker is the fallback."""
    for marker, suffix in rules:
        if marker is None or marker in cols:
            return suffix
    return None


def plan(con):
    """Return (rows, summary) where rows are the nid-level changes to apply."""
    rows, summary = [], []
    for coll, decision in DECISIONS.items():
        members = con.execute(
            f'select nid, "Conforms To", Title from "{TABLE}" '
            'where "Collection" = ? and merge_method = \'direct\'', [coll]
        ).fetchall()
        if not members:
            summary.append((coll, decision["verdict"], 0, "NOT FOUND"))
            continue

        if decision["verdict"] == "keep":
            summary.append((coll, "keep", len(members), "no change"))
            continue

        if decision["verdict"] == "change_in_header":
            for nid, _, _ in members:
                rows.append({"nid": nid, "old_collection": coll,
                             "new_collection": coll, "new_merge_method":
                             "change_in_header", "needs_review": True})
            summary.append((coll, "change_in_header", len(members),
                            "merge_method relabelled, collection kept whole"))
            continue

        buckets = defaultdict(int)
        for nid, header, _ in members:
            suffix = suffix_for(norm_cols(header), decision["rules"])
            if suffix is None:
                raise SystemExit(f"no rule matched a member of {coll!r} (nid {nid})")
            new = f"{coll} {suffix}"
            buckets[new] += 1
            rows.append({"nid": nid, "old_collection": coll, "new_collection": new,
                         "new_merge_method": "direct", "needs_review": None})
        summary.append((coll, "split", len(members),
                        "; ".join(f"{n} -> ...{k[len(coll):]}"
                                  for k, n in sorted(buckets.items()))))

    for old, new in MANUAL_RENAMES.items():
        members = con.execute(
            f'select nid from "{TABLE}" where "Collection" = ? '
            "and merge_method = 'direct'", [old]).fetchall()
        for (nid,) in members:
            rows.append({"nid": nid, "old_collection": old, "new_collection": new,
                         "new_merge_method": "direct", "needs_review": None})
        summary.append((old, "manual rename", len(members), f"-> {new!r}"))

    return rows, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv", default=None, help="where to write the change log")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        ap.error("pass --dry-run or --apply")

    con = duckdb.connect(DB, read_only=not args.apply)
    rows, summary = plan(con)

    for coll, verdict, n, detail in summary:
        print(f"[{verdict:>16}] {n:>5} rows | {coll}")
        print(f"{'':>19} {detail}")
    print(f"\n{len(rows)} rows would change" if args.dry_run
          else f"\n{len(rows)} rows to update")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"change log -> {args.csv}")

    if not args.apply:
        return

    backup = f"{DB}.bak_{dt.datetime.now():%Y%m%d_%H%M%S}"
    con.close()
    shutil.copy2(DB, backup)
    print(f"backup -> {backup}")

    con = duckdb.connect(DB)
    con.execute("create or replace temp table _plan("
                "nid varchar, new_collection varchar, "
                "new_merge_method varchar, needs_review boolean)")
    con.executemany("insert into _plan values (?,?,?,?)",
                    [(r["nid"], r["new_collection"], r["new_merge_method"],
                      r["needs_review"]) for r in rows])
    con.execute(f'''update "{TABLE}" t set
        "Collection" = p.new_collection,
        merge_method = p.new_merge_method,
        needs_review = coalesce(p.needs_review, t.needs_review)
      from _plan p where p.nid = t.nid''')
    changed = con.execute("select count(*) from _plan").fetchone()[0]
    con.close()
    print(f"updated {changed} rows in {TABLE}")


if __name__ == "__main__":
    main()
