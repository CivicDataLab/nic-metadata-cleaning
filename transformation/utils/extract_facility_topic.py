"""
Tag every "Performance of Public Facilities" dataset with the topic its
performance ranges are reported for, in a new column  `facility`.

Why this exists
    These datasets were grouped into collections by reporting grain (annual /
    monthly / quarterly, state vs district) and the collection titles club
    several *specifications* together — e.g.

        "... Performance of Public Facilities for Operation Major and Minor ..."
        "... Performance of Public Facilities for Deliveries and C-Section ..."
        "... Performance of Public Facilities for IPD, Allopathic and Ayush Attendance ..."

    A single collection therefore mixes 2-6 different measures, and once the
    members are merged the only surviving trace of which measure a row came from
    is the dataset Title. `facility` lifts that measure out of the title into its
    own column so it can become a real dimension of the merged table.

What lands in the column
    One of eight canonical labels:

        Operation Major                   <- "Operation major (General and spinal anaesthesia)"
        Operation Minor                   <- "Operation minor (No or local anaesthesia)"
        IPD Attendance                    <- "IPD Attendance"
        OPD Attendance (All)              <- "OPD attendance (All)"
        Allopathic Outpatient Attendance  <- "Allopathic - / Allopathic- / AllopathiC-Outpatient attendance"
        Ayush Outpatient Attendance       <- "Ayush - Outpatient attendance"
        Deliveries Conducted              <- "Deliveries conducted at facility"
        C-Section Deliveries              <- "C-Section / C - Section deliveries at facility"

    The 17 raw title spellings collapse onto those 8 labels; the spelling
    variants ("C - Section", "AllopathiC-Outpatient") are source noise, not
    different measures.

How the topic is found
    The title is "<grain> Range-wise Performance of Public Facilities for
    <TOPIC>[ of <State>] for <period>". We strip the trailing period expression,
    then a trailing state/UT, and whatever follows "Public Facilities for" is the
    topic. Note "at facility" is part of the topic phrase ("Deliveries conducted
    at facility"), not a location, so state stripping is anchored to a known
    state list rather than to the word "of".

Rows with no recognisable topic are left NULL and reported, never guessed at.

Usage:
    python extract_facility_topic.py --dry-run          # report only, no write
    python extract_facility_topic.py --report out.csv   # + per-row CSV
    python extract_facility_topic.py                    # back up DB, then write
    python extract_facility_topic.py --all-merge-methods
"""

import argparse
import csv
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
TABLE = "dublin_core_metadata"
NEW_COL = "facility"
TITLE_MATCH = "%Performance of Public Facilities%"

# ── title dissection ────────────────────────────────────────────────────────
# States/UTs as they appear in these titles, plus the "Andhra Pradesh Old"
# legacy spelling used for pre-bifurcation rows.
STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh Old", "Andhra Pradesh",
    "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Dadra and Nagar Haveli",
    "Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
    "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh",
    "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal",
]
# longest-first so "Andhra Pradesh Old" wins over "Andhra Pradesh"
_STATE_ALT = "|".join(re.escape(s) for s in sorted(STATES, key=len, reverse=True))
STATE_RE = re.compile(rf"\s+(?:of|for)\s+(?:{_STATE_ALT})\s*$", re.I)

# Trailing period expressions, most specific first.
PERIOD_RES = [re.compile(p, re.I) for p in (
    r"\s+for\s+Quarter\s*\d\s*:\s*\w+\s+\d{4}\s+to\s+\w+\s+\d{4}\s*$",  # Quarter 1: Apr 2012 to Jun 2012
    r"\s+for\s+\w+\s+\d{4}\s+to\s+\w+\s+\d{4}\s*$",                     # Apr 2019 to Jun 2019
    r"\s+for\s+[A-Za-z]+[-\s]\d{4}-\d{2}\s*$",                          # April 2012-13
    r"\s+for\s+[A-Za-z]+[-\s]\d{4}\s*$",                                # April-2019
    r"\s+for\s+\d{4}-\d{2}\s*$",                                        # 2012-13
)]

ANCHOR_RE = re.compile(r"Performance of Public Facilities\s+(?:for\s+)?", re.I)

# ── topic -> canonical label ────────────────────────────────────────────────
# Rule-based rather than an exact-match table, so a new spelling variant of a
# known measure still classifies. Order matters: C-Section is checked before the
# generic delivery rule, Ayush before Allopathic.
def _has(s, *words):
    return all(w in s for w in words)


def canonical_facility(topic):
    """Map a raw title topic onto one of the eight canonical labels."""
    t = topic.lower()
    if _has(t, "operation", "major"):
        return "Operation Major"
    if _has(t, "operation", "minor"):
        return "Operation Minor"
    if re.search(r"\bc\s*-?\s*section\b", t):
        return "C-Section Deliveries"
    if "deliveries conducted" in t or "deliveries" in t:
        return "Deliveries Conducted"
    if "ipd" in t:
        return "IPD Attendance"
    if "opd attendance" in t:
        return "OPD Attendance (All)"
    if "ayush" in t:
        return "Ayush Outpatient Attendance"
    if "allopathi" in t:
        return "Allopathic Outpatient Attendance"
    return None


def extract_topic(title):
    """Return the raw topic segment of a title, or None if the shape is unknown."""
    s = (title or "").strip()
    for rx in PERIOD_RES:
        stripped = rx.sub("", s)
        if stripped != s:
            s = stripped
            break
    s = STATE_RE.sub("", s)
    m = ANCHOR_RE.search(s)
    if not m:
        return None
    topic = s[m.end():].strip(" ,")
    return topic or None


def classify(title):
    """title -> (canonical facility label or None, raw topic or None)"""
    topic = extract_topic(title)
    if topic is None:
        return None, None
    return canonical_facility(topic), topic


# ── db plumbing ─────────────────────────────────────────────────────────────
def backup_db(db_path):
    dst = f"{db_path}.pre_facility_{time.strftime('%Y%m%d_%H%M%S')}.bak"
    shutil.copy2(db_path, dst)
    # a backup nobody can open is not a backup
    probe = duckdb.connect(dst, read_only=True)
    probe.execute(f'SELECT count(*) FROM "{TABLE}"').fetchone()
    probe.close()
    print(f"backup: {dst}")
    return dst


def fetch_rows(con, all_merge_methods):
    where = f'"Title" ILIKE ?'
    params = [TITLE_MATCH]
    if not all_merge_methods:
        where += " AND merge_method = ?"
        params.append("curate")
    return con.execute(
        f'SELECT nid, "Title", "Collection" FROM "{TABLE}" WHERE {where}', params
    ).fetchall()


def fetch_rows_from_csv(path):
    """Read nid/title/Collection from a curate export instead of the DB.

    The 3.4 GB metadata.db is often locked by another process; the export
    produced by curate_collection_row_count.py carries the same three columns
    for exactly the curate scope, so the classification is identical.
    """
    con = duckdb.connect()
    con.execute("set enable_progress_bar=false")
    rows = con.execute(
        """SELECT nid, title, "Collection"
           FROM read_csv_auto(?, header=true, all_varchar=true)
           WHERE title ILIKE ?""",
        [path, TITLE_MATCH],
    ).fetchall()
    con.close()
    return rows


def report(records):
    """Print the facility spread and, per collection, which topics are clubbed."""
    labels = Counter(r[3] for r in records if r[3])
    unmatched = [r for r in records if not r[3]]
    raw_by_label = defaultdict(set)
    by_coll = defaultdict(Counter)
    for _nid, _title, coll, label, raw in records:
        if label:
            raw_by_label[label].add(raw)
        by_coll[coll][label or "<unclassified>"] += 1

    print(f"rows matched          : {len(records)}")
    print(f"facility assigned     : {sum(labels.values())}")
    print(f"unclassified          : {len(unmatched)}")

    print("\n=== facility distribution ===")
    for label, n in labels.most_common():
        variants = sorted(raw_by_label[label])
        print(f"{n:7d}  {label}")
        for v in variants:
            print(f"           <- {v}")

    print("\n=== topics clubbed per collection ===")
    for coll, ctr in sorted(by_coll.items()):
        print(f"\n[{len(ctr)} topics] {coll}")
        for label, n in ctr.most_common():
            print(f"    {n:7d}  {label}")

    if unmatched:
        print("\n=== unclassified sample ===")
        for nid, title, _c, _l, raw in unmatched[:25]:
            print(f"  {nid} | raw={raw!r} | {title}")


def write_report_csv(records, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nid", "Title", "Collection", "facility", "raw_topic"])
        w.writerows(records)
    print(f"\nper-row report: {path}")


def write_update_csv(records, path):
    """Just nid + facility — the shape you merge back onto the table."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nid", NEW_COL])
        w.writerows((nid, label) for nid, _t, _c, label, _r in records if label)
    print(f"merge-ready CSV: {path}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db-path", default=DB_PATH, help="override DB (e.g. a copy)")
    ap.add_argument("--dry-run", action="store_true", help="report only, no write")
    ap.add_argument("--report", metavar="CSV", help="also write a per-row CSV")
    ap.add_argument("--all-merge-methods", action="store_true",
                    help="process every merge_method, not just 'curate'")
    ap.add_argument("--source-csv", metavar="CSV",
                    help="classify from a curate export instead of the DB "
                         "(implies no DB write; pair with --update-csv)")
    ap.add_argument("--update-csv", metavar="CSV",
                    help="write a lean nid,facility CSV for merging back later")
    args = ap.parse_args()

    if args.source_csv:
        rows = fetch_rows_from_csv(args.source_csv)
        con = None
    else:
        con = duckdb.connect(args.db_path, read_only=args.dry_run)
        rows = fetch_rows(con, args.all_merge_methods)
    if not rows:
        print("no matching rows — nothing to do")
        if con:
            con.close()
        return

    records = []
    for nid, title, coll in rows:
        label, raw = classify(title)
        records.append((nid, title, coll, label, raw))

    report(records)
    if args.report:
        write_report_csv(records, args.report)
    if args.update_csv:
        write_update_csv(records, args.update_csv)

    if args.source_csv:
        print("\nclassified from CSV — DB untouched")
        return

    if args.dry_run:
        print("\ndry run — no changes written")
        con.close()
        return

    con.close()
    backup_db(args.db_path)

    con = duckdb.connect(args.db_path)
    con.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN IF NOT EXISTS "{NEW_COL}" VARCHAR')

    import pandas as pd
    upd = pd.DataFrame(
        [(nid, label) for nid, _t, _c, label, _r in records if label],
        columns=["nid", NEW_COL],
    )
    con.register("facility_updates", upd)
    con.execute(f"""
        UPDATE "{TABLE}" AS d
        SET "{NEW_COL}" = u."{NEW_COL}"
        FROM facility_updates AS u
        WHERE d.nid = u.nid
    """)
    con.unregister("facility_updates")
    written = con.execute(
        f'SELECT count(*) FROM "{TABLE}" WHERE "{NEW_COL}" IS NOT NULL'
    ).fetchone()[0]
    con.close()
    print(f"\nwrote {NEW_COL} for {len(upd)} rows "
          f"({written} non-null in table overall)")


if __name__ == "__main__":
    main()
