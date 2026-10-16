"""Put new_title of lot 1 (dublin_core_metadata) right.

A collection member carries its collection's name in new_title, as on lots 2
and 3. 30,805 members still held the name of the collection they were in
before the collections were regrouped ("Range-wise Performance of Public
Facilities for IPD Attendance" for annual, monthly and quarterly collections
alike) or a mistyped or cut one; they are set to Collection.

The 1,821 rows with no Collection (non-mergeable, to be removed) carried an LLM
rewrite of an LLM rewrite of the title, and it had drifted: dates and states
dropped, "Number of" removed, "as on" turned into "upto", 41 names shared by
different datasets. For these rows new_title is the raw title
(raw_metadata.Title) with its wording kept and only the form cleaned:
  - Title Case, small words lower, acronyms as written (PHCs, UTs, ANM)
  - spacing around brackets, slashes, commas and dashes
  - "State/UT wise" -> "State/UT-wise"
  - the misspellings listed in TYPO
Nothing is reworded, reordered, expanded or dropped.

Source of truth: data/lot1_new_title_changes.csv
(nid, UUID, merge_method, raw_title, old_new_title, new_title). To change or
revert a title, edit the CSV and re-run, then rebuild the copies with both
export_all_lots.py runs. --build writes the CSV again from the raw titles and
overwrites hand edits. Title is fix_lot1_title.py's business.

Usage: python fix_lot1_new_title.py [--build] [--dry-run]
"""
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB_PATH = str(HERE.parent / "metadata.db")
CHANGES = HERE.parent.parent / "data" / "lot1_new_title_changes.csv"
TABLE = "dublin_core_metadata"
BUILD, DRY = "--build" in sys.argv, "--dry-run" in sys.argv

SMALL = set("a an the and or nor of in on at by to for as per with from vs into than upto till during under among "
            "between within without against through over after before below above about".split())
# acronyms the raw titles also write in lower or mixed case
ACRONYM = {a.lower(): a for a in "AIDS ANM ANMs CHC CHCs GDMOs LHV MBBS PHC PHCs UT UTs HW ANC DLHS NFHS RHS".split()}
PREFIX = set("sub neo peri ante bio non co post mid pre anti inter intra multi semi".split())
MONTH = ("jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august "
         "september october november december").split()
TYPO = [  # (pattern, replacement), case-insensitive, applied before casing
    (r"\bat\s?least\b", "at least"), (r"\balongwith\b", "along with"), (r"\bsuplimentation\b", "supplementation"),
    (r"\bmarriedmage\b", "married age"), (r"\bsurvay\b", "survey"), (r"\bsuffereing\b", "suffering"),
    (r"\bimmuniztion\b", "immunization"), (r"\btreatement\b", "treatment"), (r"\bRubells\b", "Rubella"),
    (r"\bContracetivesand\b", "Contraceptives and"), (r"\bAaasay\b", "Assay"), (r"\bnucliec\b", "nucleic"),
    (r"\btwelth\b", "twelfth"), (r"\bwsie\b", "wise"), (r"\bMrach\b", "March"), (r"\bBuiliding\b", "Building"),
    (r"\bCHCand\b", "CHC and"), (r"\bUTt\b", "UT"), (r"\b(State|District)wise\b", r"\1-wise"),
    (r"Public_Sector", "Public Sector"), (r"\bClassification of\s+According\b", "Classification According"),
    (r"\bCalmette-Gurin\b", "Calmette-Guerin"), (r"\b(DLHS|NFHS|AHS)\s+-\s*(\d)", r"\1-\2"),
    (r"\bUnder\s+-\s*five\b", "Under-five"), (r"\bbreak-\s+up\b", "break-up"), (r"(\d)age\)", r"\1 age)"),
    (r"h\.w\.\[\(F\)", "H.W. (F)"), (r"\(ANM\)s\b", "(ANMs)"), (r"\bplans\s*-\s*(till|upto)\b", r"plans - \1"),
    (r"\bFom\b", "from"), (r"\bCasts/Tribes\b", "Castes/Tribes"), (r"\bPharmacistas\s+-", "Pharmacist -"),
    (r"\(CDR - SRS\b", "(CDR) - SRS"), (r"2007-08-Total\b", "2007-08) - Total"), (r"\b31-03-\s+2017\b", "31-03-2017"),
    (r"^tem-wise\b", "Item-wise"),
]


def _word(w, first, prev, nxt):
    """Case one piece of a title that has no space, hyphen or slash in it."""
    pre, core, post = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", w).groups()
    if not core or not core[0].isalpha():
        return w
    low = core.lower()
    if low in ACRONYM:
        core = ACRONYM[low]
    elif re.fullmatch(r"([a-z]\.)+[a-z]?", low):          # h.w. -> H.W.
        core = core.upper()
    elif core == "A" and (prev.lower() == "vitamin" or nxt == "&"):
        pass
    elif low in SMALL and not first:
        core = low
    elif core[1:] != core[1:].lower():                    # NFHS, PHCs, MoH&FW: left as written
        pass
    else:
        core = core[0].upper() + core[1:]
    return pre + core + post


def space(raw):
    """Typos and spacing; the wording and the casing are left as they are."""
    s = re.sub(r"\s+", " ", raw).strip()
    if s == s.upper():
        s = s.lower()
    for pat, rep in TYPO:
        s = re.sub(pat, rep, s, flags=re.I)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"([\w.])([(\[])", r"\1 \2", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    s = re.sub(r"\s+([)\]])", r"\1", s)
    s = re.sub(r"\)(?=\(|\d|[A-Za-z]{2})", ") ", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",(?=[A-Za-z]|\d{4}\b)", ", ", s)
    s = re.sub(r"(?i)\b(%s)\s*-\s+(?=(?:19|20)\d\d\b)" % "|".join(MONTH), r"\1 ", s)    # "March- 2012"
    s = re.sub(r"([A-Za-z)\]])-\s+", r"\1 - ", s)        # "Births- 2009" -> "Births - 2009"
    s = re.sub(r"(?<=\d)-\s+(?=[A-Za-z])", " - ", s)
    s = re.sub(r"\s+-(?=\w)", " - ", s)
    s = re.sub(r"([)\]])-(?![IVX]+\b)(?=\w)", r"\1 - ", s)
    s = re.sub(r"([A-Za-z]+)-(?=(?:19|20)\d\d)",          # "Years-2008-09", not "December-2014-15"
               lambda m: m.group(0) if m.group(1).lower() in MONTH else m.group(1) + " - ", s)
    s = re.sub(r"([a-z])-(Rural|Urban|Total)\b", r"\1 - \2", s)
    return re.sub(r"(?i)([A-Za-z])[ -]wise\b", r"\1-wise", s)


def clean(raw):
    out, ws = [], space(raw).split(" ")
    for i, w in enumerate(ws):
        parts = re.split(r"([-/])", w)
        first = i == 0 or (i == 1 and ws[0].lower().endswith("-wise"))
        done = []
        for j, p in enumerate(parts):
            if p in "-/" or not p:
                done.append(p)
            elif j and parts[j - 1] == "-" and p.strip(",.;:)") != "A" and (
                    p.lower() in SMALL | {"wise", "up", "ups"}
                    or (parts[j - 2].lower() in PREFIX and p[1:] == p[1:].lower())):
                done.append(p.lower())
            else:                                         # the head of a compound is never a small word
                done.append(_word(p, (first and j == 0) or (j == 0 and "-" in parts[1:2]),
                                  ws[i - 1] if i else "", ws[i + 1] if i + 1 < len(ws) else ""))
        out.append("".join(done))
    return re.sub(r"\s+", " ", " ".join(out)).strip()


con = duckdb.connect(DB_PATH, read_only=DRY or BUILD)
if BUILD:
    # a row already written keeps the old name it had in the CSV
    prev = pd.read_csv(CHANGES, dtype=str).set_index("nid").old_new_title.to_dict() if CHANGES.exists() else {}
    df = con.execute(f"""
        SELECT d.nid::VARCHAR AS nid, d."Identifier[UUID]" AS "UUID", d.merge_method, r."Title" AS raw_title,
               d.new_title AS cur
        FROM {TABLE} d JOIN raw_metadata r ON r.nid::VARCHAR = d.nid::VARCHAR
        WHERE d."Collection" IS NULL ORDER BY d."Relation[Catalog Title]", r."Title", d.nid""").df()
    df["new_title"] = df.raw_title.map(clean)
    df["old_new_title"] = [prev.get(n, c) for n, c in zip(df.nid, df.cur)]
    df = df[df.old_new_title != df.new_title]
    df[["nid", "UUID", "merge_method", "raw_title", "old_new_title", "new_title"]].to_csv(CHANGES, index=False)
    print(f"{CHANGES.name}: {len(df)} rows, {df.new_title.nunique()} distinct new titles")
    sys.exit()

ch = pd.read_csv(CHANGES, dtype=str)
con.register("ch", ch)
cur = con.execute(f"""
    SELECT c.nid, d.new_title AS cur, d."Collection" AS coll, c.old_new_title AS old, c.new_title AS new
    FROM ch c LEFT JOIN {TABLE} d ON d.nid::VARCHAR = c.nid""").df()
bad = cur[~((cur.cur == cur.old) | (cur.cur == cur.new)) | cur.coll.notna()]
assert bad.empty, f"rows that hold neither name or are in a collection\n{bad}"
todo = cur[cur.cur != cur.new]
print(f"{TABLE}: {len(ch)} listed, {len(todo)} to write, {len(ch) - len(todo)} already done")
if not DRY and len(todo):
    n = con.execute(f"""
        UPDATE {TABLE} AS d SET new_title = c.new_title FROM ch c
        WHERE d.nid::VARCHAR = c.nid AND d.new_title = c.old_new_title AND d.new_title <> c.new_title
        RETURNING 1""").fetchall()
    assert len(n) == len(todo), (len(n), len(todo))
    print(f"  {len(n)} rows updated")
stale = 'FROM {t} WHERE "Collection" IS NOT NULL AND new_title IS DISTINCT FROM "Collection"'.format(t=TABLE)
n = con.execute(f"SELECT count(*), count(DISTINCT new_title) {stale}").fetchone()
print(f"collection members not on their collection's name: {n[0]} rows, {n[1]} names")
if not DRY and n[0]:
    con.execute(f'UPDATE {TABLE} SET new_title = "Collection" WHERE "Collection" IS NOT NULL '
                'AND new_title IS DISTINCT FROM "Collection"')
    print(f"  {n[0]} rows set to Collection")
con.close()
