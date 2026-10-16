#!/usr/bin/env python3
"""
Rebuild dublin_core_remaining.new_catalog_title from "Relation[Catalog Title]".

Catalogs are merged only when they are the same series split by year, state,
district level, session, month or language (English/Hindi), or when they are
spelling/format variants of one title. Unlike dublin_core_metadata (365
catalogs -> 14 topic names) nothing is merged on a broad topic.

  * Smart Cities Mission catalogs stay one per city. The city comes from the
    publisher ("..., Smart Cities Mission, <State>, <City>"), since some titles
    carry no city and one title can be shared by several cities. The name is
    "<Topic> : <City>", so "Buses: Nagpur" and "Buses : Nagpur" merge, and
    "Digital Payments" (Kohima) becomes "Digital Payments : Kohima".
  * Every other catalog is grouped per ministry on a key with years, states,
    District/State-wise, months, sessions and language tags removed.
  * Merges already on the table are kept (Crime in India, ADSI, ...) except the
    ones in BROKEN_OLD, which lumped unrelated catalogs together or dropped the
    city from the name.
  * FORCE_GROUPS / RENAME fix the cases the key rules cannot see.

--table dublin_core_lot3 builds the column for lot 3 with the same series rules.
Lot 3 is mostly state data, so a catalog belongs to the ministry or the state
department that maintains it and is only ever merged with that owner's other
catalogs; see the "lot 3" section below for what else differs.

Default is a dry run that writes the proposal to data/backups/. --apply
updates the table in one statement (adding the column if the table has none);
for dublin_core_remaining it snapshots nid + new_catalog_title first.

Usage:
  python3 fix_new_catalog_title_remaining.py            # proposal only
  python3 fix_new_catalog_title_remaining.py --apply
  python3 fix_new_catalog_title_remaining.py --table dublin_core_lot3 [--apply]
"""

import argparse
import datetime as dt
import re
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "metadata.db"
BACKUPS = HERE.parent.parent / "data" / "backups"
TABLE = "dublin_core_remaining"
LOT3_TABLE = "dublin_core_lot3"
CAT = "Relation[Catalog Title]"
PUB = "Publisher[ministry_department]"
STATE_PUB = "Publisher[state_department]"

# Old merges that were wrong: unrelated catalogs under one name, or a
# Chandigarh topic with the city dropped from the name.
BROKEN_OLD = {
    "Rajya Sabha Questions and Answers", "Roads", "Diseases", "Environment",
    "Health Infrastructure", "Property Tax", "Open Spaces", "Water Tax",
    "Water Consumption", "Community Facilities", "Digital availability",
}

# name -> regexes on the catalog title; wins over every other rule.
FORCE_GROUPS = {
    "Crime in India": [r"^Crime in India\s*-\s*\d{4}$"],
    "Accidental Deaths & Suicides in India (ADSI)":
        [r"^Accidental Deaths & Suicides in India( \(ADSI\))?\s*-\s*\d{4}$"],
    "Prison Statistics India (PSI)": [r"^Prison Statistics( India \(PSI\))?\s*-\s*\d{4}$"],
    "Road Accidents in India": [r"^Road Accidents in India\s*-?\s*\d{4}$"],
    "India Tourism Statistics": [r"^India Tourism Statistics$", r"^Tourism Statistics of India$"],
    "Wholesale Price Index": [r"^Wholesale Price Index$", r"^Wholesale Price Index - \(Base Year 2004-05\)$"],
    "School Education Institutions": [r"^Institutions - School education$", r"^School education institutions$"],
    "Enrolment in School Education":
        [r"^Enrolment in school education$", r"^Enrolment In School Education - Statistics of School Education$"],
    "Gender Parity Index (GPI) in Higher Education":
        [r"^Gender parity index \(GPI\) in Higher Education$", r"^Gender Parity Index \(GPI\) in higher education \(AISHE Survey\)$"],
    "Month-wise Rajya Sabha Members Birthday Feeds":
        [r"^Month[- ]wise (Rajya Sabha )?Members Birthday Feeds for the Month of \w+ \((English|Hindi)\)$"],
    "Daily List of Rajya Sabha Starred Questions":
        [r"^Daily List of Rajya Sabha Starred Questions \(English\)$", r"^Daily List of Starred Questions \(Hindi\)$"],
    "Daily List of Rajya Sabha Unstarred Questions":
        [r"^Daily List of Rajya Sabha Unstarred Questions \(English\)$", r"^Daily List of Unstarred Questions \(Hindi\)$"],
    "Rajya Sabha RSS Feeds": [r"^Rajya Sabha (English|Hindi) RSS Feeds$"],
    "Rajya Sabha Parliamentary Bulletin Part I": [r"^Rajya Sabha Parliamentary Bulletin Part[- ]I \((English|Hindi)\)$"],
    "Rajya Sabha Parliamentary Bulletin Part II": [r"^Rajya Sabha Parliamentary Bulletin Part[- ]II \((English|Hindi)\)$"],
    "Special Mentions by Rajya Sabha Members": [r"^Member[- ]wise Special Mentions in Rajya Sabha \((English|Hindi)\)$"],
}

# Derived group name -> better name.
RENAME = {
    "GDP and Growth Rate at Constant Price()": "District Wise GDP and Growth Rate at Constant Price",
    "GDP and Growth Rate at Current Price()": "District Wise GDP and Growth Rate at Current Price",
    "Wise GDP and Growth Rate at Current Price()": "District Wise GDP and Growth Rate at Current Price",
    "Review of the Performance of State Road Transport Undertakings (SRTUs) for":
        "Review of the Performance of State Road Transport Undertakings (SRTUs)",
    "Meteorological Sub-division Wise Monthly Rainfall": "Meteorological Sub-division Wise Rainfall",
    "Use Based Monthly Indices for all India Index of Industrial Production":
        "Use Based Indices of All India Index of Industrial Production",
    "Number of Telephones in India - Year-wise": "Number of Telephones in India",
    "Year-wise Industrial Investment Proposals Received From Industrial Undertakings":
        "Industrial Investment Proposals Received From Industrial Undertakings",
    "Factory Employment By States": "Factory Employment",
    "Status of Coverage under Rural Roads in Sample States - Based on Sample Survey":
        "Status of Coverage under Rural Roads in Sample States and Districts - Based on Sample Survey",
    "Month wise Members Birthday Feeds": "Month-wise Rajya Sabha Members Birthday Feeds",
    "Crime": "Crime in India",
    "Road Accidents": "Road Accidents in India",
    "Water Quality": "Water Quality in India",
    "Status of Water Quality": "Status of Water Quality in India",
    "Basic Road Statistics": "Basic Road Statistics of India",
}

# ---------------------------------------------------------------- smart cities
# Publisher city -> (display name, other spellings used in titles).
CITY_FIX = {
    "Tiruvanantapuram": ("Thiruvananthapuram", ["Thiruvananthapuram", "Trivandrum"]),
    "Puduchery": ("Puducherry", ["Puducherry", "Pondicherry"]),
    "Tiruchirapalli": ("Tiruchirappalli", ["Tiruchirappalli", "Trichy"]),
    "Kalyan Dombivali": ("Kalyan Dombivli", ["Kalyan Dombivli", "Kalyan-Dombivli", "KDMC"]),
    "Davangere": ("Davanagere", ["Davanagere"]),
    "Naya Raipur": ("Atal Nagar", ["Atal Nagar", "Atalnagar", "Nava Raipur", "Naya Raipur"]),
    "Hubli Dharwad": ("Hubballi-Dharwad", ["Hubballi-Dharawad", "Hubballi-Dharwad", "Hubballi Dharwad", "Hubli-Dharwad"]),
    "Greater Warangal": ("Warangal", ["Warangal"]),
    "Amravati": ("Amaravati", ["Amaravati"]),
    "Rajkot": ("Rajkot", ["RMC"]),
    "Bengaluru": ("Bengaluru", ["Bangalore"]),
    "Kanpur": ("Kanpur", ["Kanpur Nagar"]),
    "Ujjain": ("Ujjain", ["Ujjan"]),
    "Prayagraj": ("Prayagraj", ["Allahabad"]),
    "Agartala": ("Agartala", ["Tripura"]),
    "Pimpri Chinchwad": ("Pimpri Chinchwad", ["Pimpri-Chinchwad", "PCMC"]),
    "Gwalior": ("Gwalior", ["Gwalior MP", "Gwalior Mp"]),
    "Bareilly": ("Bareilly", ["Bareilly Smart City"]),
}


ACRONYMS = {"VAT", "GST", "ITC", "ICCC", "RTO", "SWM", "BPL", "ITMS", "COVID", "NDMC", "PPP",
            "LED", "CCTV", "MC", "FY", "UT", "OSRTC", "PM", "NO2", "SO2", "S02", "O3"}
SEP = "\x00"   # marks where a city/date was cut out of a title


def city_names(city):
    return sorted({city, *CITY_FIX.get(city, (city, []))[1]}, key=len, reverse=True)


def cut_city(s, city, state):
    """Replace the city (any spelling, plus 'in/of', 'City', ', <State>', ...) with SEP."""
    alts = "|".join(r"[\s\-]*".join(map(re.escape, re.split(r"[\s\-]+", n))) for n in city_names(city))
    tail = r"(?:\s*\b(?:Smart City|City|MP|Municipal Corporat\w+|Nagar Nigam)\b)?"
    if state:
        tail += r"(?:\s*,\s*" + re.escape(state) + r")?"
    pat = re.compile(r"(?:\b(?:in|of|for|at)\s+)?<?\s*\b(?:" + alts + r")\b\s*>?" + tail, re.I)
    s2 = pat.sub(SEP, s)
    if s2 != s:
        return s2
    # misspelt city ("Visakhaptnam", "Prayagrag"): best 1-3 word window, >= 6 chars
    words = s.split(" ")
    best = (0.0, None)
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            w = " ".join(words[i:i + n]).strip(":-,<>")
            if len(w) < 6:
                continue
            for name in city_names(city):
                r = SequenceMatcher(None, w.lower(), name.lower()).ratio()
                if r > best[0]:
                    best = (r, (i, n))
    if best[0] >= 0.8:
        i, n = best[1]
        pre = words[:i]
        if pre and pre[-1].lower() in ("in", "of", "for", "at"):
            pre = pre[:-1]
        return " ".join(pre + [SEP] + words[i + n:])
    return s


def sc_topic(title, city, state=""):
    s = title.replace("_", " ")
    s = re.sub(r"\b([A-Z][a-z]+)((?:[A-Z][a-z]+)+)\b",                 # "SolidWasteManagement"
               lambda m: re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(0)), s)
    s = re.sub(r"^D\s?\d+\s*[-_ ]\s*", "", s)                         # "D46 ", "D13-", "D 30 "
    s = cut_city(s, city, state) if city else s
    # dates, years and year ranges ("2014 to 2018", "2013-14 to 2017-18", "FY (2020-21)")
    s = re.sub(r"\bas on\s+\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", SEP, s, flags=re.I)
    s = re.sub(r"\b(FY\s*)?\(?\b(19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?\)?"
               r"(\s*(to|-|–)\s*\(?(19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?\)?)?", SEP, s, flags=re.I)
    s = re.sub(r"\b[A-Z]{3}\s+to\s+[A-Z]{3}\d{2}\b", SEP, s)          # "APR to DEC18"
    s = re.sub(r"\s+", " ", s)
    # drop separators left next to the cut-outs; keep one " - " where text follows
    s = re.sub(r"[\s:,\-]*" + SEP + r"[\s:,\-]*", SEP, s)
    s = re.sub(SEP + "+", SEP, s).strip(SEP + " :-,")
    s = s.replace(SEP, " - ")
    s = re.sub(r"\s*:\s*", " : ", s)
    s = re.sub(r"\s+(in|of|for|at|to)$", "", s, flags=re.I).strip(" :-,")
    if not s:
        return title
    if s.isupper():
        s = " ".join(w if w.strip("()&,") in ACRONYMS else w.title() for w in s.split(" "))
    return s[:1].upper() + s[1:]


def topic_key(topic):
    s = topic.lower().replace("&", " and ")
    s = re.sub(r"\bcent(re|er)s?\b", "center", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(and|of|in|the|for|to|by|at|on|data|details|catalog)\b", " ", s)
    s = re.sub(r"\b(\w{3,}?)s\b", r"\1", s)
    return " ".join(s.split())


def best_variant(variants):
    """Pick the display form among spelling variants (list of (text, rows))."""
    def score(v):
        t, n = v
        return (not t.isupper(), t[:1].isupper(), not re.search(r"\w&|&\w|[a-z]-[A-Z]", t),
                " : " not in t, n, -len(t))
    return max(variants, key=score)[0]


# ---------------------------------------------------------------- other catalogs
STATES = (r"andaman and nicobar islands|andaman & nicobar islands|a & n islands|andaman and nicobar|"
          r"andhra pradesh|arunachal pradesh|assam|bihar|chandigarh|chhattisgarh|"
          r"dadra and nagar haveli and daman and diu|dadra & nagar haveli|dadra and nagar haveli|"
          r"daman and diu|daman & diu|nct of delhi|delhi|goa|gujarat|haryana|himachal pradesh|"
          r"jammu and kashmir|jammu & kashmir|jharkhand|karnataka|kerala|ladakh|lakshadweep|"
          r"madhya pradesh|maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|orissa|puducherry|"
          r"pondicherry|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|uttar pradesh|"
          r"uttarakhand|uttaranchal|west bengal|all india|india")
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
YEAR = r"\b(19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?\b"


def series_key(t):
    s = t.lower()
    s = re.sub(r"\((english|hindi)\)|\bin (english|hindi)\b|\b(english|hindi)\b", " ", s)
    s = re.sub(YEAR, " ", s)
    s = re.sub(r"\b(" + MONTHS + r")\b", " ", s)
    s = re.sub(r"\bsession\s*\d+\b", "session", s)
    s = re.sub(r"\b(" + STATES + r")\b", " ", s)
    s = re.sub(r"\b(state|states|ut|uts|district|districts)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(and|of|in|the|for|to|by|at|on|as|upto|up|during|year|years|wise|month|"
               r"monthly|annual|yearly|census|data)\b", " ", s)
    s = re.sub(r"\b(\w+?)s\b", r"\1", s)
    return " ".join(s.split())


def series_name(t):
    s = re.sub(r"\s*\((English|Hindi)\)|\s+in (English|Hindi)\b", "", t, flags=re.I)
    s = re.sub(r"\s*,?\s*Census (19|20)\d\d\b", "", s)
    s = re.sub(r"\s+for the Month of (" + MONTHS + ")", "", s, flags=re.I)
    s = re.sub(r"\s+for\s+(the\s+)?Session\s*\d+", "", s, flags=re.I)
    s = re.sub(r"\s*[-:,]?\s*\b(19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?"
               r"(\s*(and|&)\s*(19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?)?\b", "", s)
    s = re.sub(r"^(District|State|State/UT)[- ]?[Ww]ise\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -:,_")
    return s[:1].upper() + s[1:] if s else t


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


# ---------------------------------------------------------------- lot 3
# dublin_core_lot3 differs from dublin_core_remaining in four ways:
#   * The publisher of a state row is "Publisher[state_department]", written
#     "<State>,<Department>,<Office>". Catalogs are grouped per owner: the
#     ministry for a Central row, the state and its department for a State row.
#   * A catalog title used by two owners stays two catalogs.
#   * It has no earlier new_catalog_title worth keeping, so a re-run depends on
#     the catalog title and the publisher alone.
#   * Two kinds of series are split on something other than a year: bulletins
#     named by date ("... as on 15/06/2021"), and one table published once per
#     district ("<Name> District Hand Book ...", "Crop Survey of <Name>
#     District of Karnataka ..."). Both are cut before the series key is taken.
# The names the rules build were then reviewed against the old titles (Haiku
# agents, 2026-10-07; working files in data/catalog_title_work/lot3/). The
# accepted corrections are in LOT3_NAMES, one row per owner and series key, and
# win over the rule-built name. FORCE_GROUPS and RENAME are not used for lot 3.
LOT3_NAMES = HERE.parent / "text_generation" / "lot3_new_catalog_title_names.csv"
DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"


def lot3_names():
    """(owner, series key) -> reviewed name."""
    if not LOT3_NAMES.exists():
        return {}
    df = pd.read_csv(LOT3_NAMES, dtype=str, keep_default_na=False)
    return {(o, k): n for o, k, n in zip(df.owner, df.key, df.name)}


def owner(ministry_pub, state_pub):
    """Who maintains the catalog: the ministry, else '<State> / <Department>'."""
    if norm(ministry_pub):
        return re.split(r"[,|]", ministry_pub)[0].strip()
    # levels are joined by a bare comma; a comma inside a name has a space after it
    levels = [norm(p) for p in re.split(r",(?! )", state_pub or "")]
    return " / ".join(levels[:2])


def _short_year(m):
    """'2018 19' -> '2018-19', only when the second number is the next year."""
    a, b = m.group(1), m.group(2)
    return f"{a}-{b}" if (int(a) + 1) % 100 == int(b) else m.group(0)


def cut_lot3(t):
    """Title without the date, district and odd year forms that split a series."""
    s = re.sub(r"^(Title\s*)?:\s*", "", t).replace("_", " ")           # "Title:Report ...", ": Crop ..."
    s = re.sub(r"\bHand\s?book\b", "Hand Book", s, flags=re.I)         # "HandBook", "Handbook"
    s = re.sub(r"\bStatisticial\b", "Statistical", s)
    s = re.sub(r"\bREVEIW\b", "REVIEW", s)
    s = re.sub(r"\b20116\b", "2016", s)                                # "... Tamil Nadu 20116-17"
    s = re.sub(r"\s*\(Source:? Media Bulletin dated [^)]*\)", "", s, flags=re.I)
    s = re.sub(r"\s*\(?\b(as on|dated)\s+" + DATE + r"\)?", "", s, flags=re.I)
    s = re.sub(r"^.+? District Hand ?book\b", "District Hand Book", s, flags=re.I)
    s = re.sub(r"^(Crop Survey of) .+? District of\b", r"\1", s, flags=re.I)
    s = re.sub(r"\b((?:19|20)\d\d) (\d\d)\b", _short_year, s)
    s = re.sub(r"\s*\([A-Z]+(19|20)\d\d\)", "", s)                     # "(TNGLANCE2019)"
    return norm(s)


# Spellings of one word across the editions of a lot 3 series, for the key only.
LOT3_SPELLING = [
    # series_key drops the word "state", which would make "Gross State Domestic
    # Product of <State>" the same series as "Gross Domestic Product - All India and <State>"
    (r"\bstate domestic product\b", "sdp"),
    (r"\s*:\s*SCR\b", ""),                      # Season and Crop Report: the 2016-17 titles lack the tag
    (r"\bFY\b", ""),
    (r"(?<=[a-z])wise\b", " wise"),             # "Branchwise"
    (r"(\w)ies\b", r"\1y"),                     # facilities / facility, supplies / supply
    (r"\bprinciple\b", "principal"),
    (r"\bsugar cane\b", "sugarcane"),
    (r"\bfood grains\b", "foodgrains"),
    (r"\bhusbandary\b", "husbandry"),
    (r"\b(recreational|reception)(?= and cultural)", "recreation"),
    (r"\bstorage faculties\b", "storage facility"),
    (r"\bprisions\b", "prisons"),
    (r"\btaxes\b", "tax"),
]


def key_lot3(t):
    s = cut_lot3(t)
    for pat, rep in LOT3_SPELLING:
        s = re.sub(pat, rep, s, flags=re.I)
    return series_key(s)


def tidy_lot3(s):
    """Drop what the year cut leaves hanging: '... for the Year', '()', a last 'for' or month."""
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+(" + MONTHS + r")$", "", s, flags=re.I)
    s = re.sub(r"\s+(for|during|in|of)\s+(the\s+)?(financial\s+)?years?$", "", s, flags=re.I)
    s = re.sub(r"(\s+(for|in|of|during|upto|as on|from|to|and|the))+$", "", s, flags=re.I)
    s = re.sub(r"(Hand Book)\s*:\s*", r"\1 : ", s)
    return norm(s).strip(" -:,_")


# ---------------------------------------------------------------- build
def build(con, table=TABLE):
    lot3 = table == LOT3_TABLE
    cols = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    old_sql = "new_catalog_title" if "new_catalog_title" in cols else "CAST(NULL AS VARCHAR)"
    rows = con.execute(f'''
        SELECT rowid AS rid, nid, "{CAT}" AS cat, {old_sql} AS old, "{PUB}" AS pub,
               "{STATE_PUB}" AS spub
        FROM {table}''').df()
    rows["k"] = rows.cat.map(norm)
    rows["old_raw"] = rows.old
    rows["old"] = rows.old.map(lambda x: norm(x) or None)
    rows["sc"] = rows.pub.fillna("").str.contains("Smart Cities Mission")
    parts = rows.pub.fillna("").str.split(",")
    # "..., Smart Cities Mission, <State>, <City>"; Chandigarh has only "..., Smart Cities Mission, Chandigarh"
    rows["city"] = [p[-1].strip() if sc and len(p) >= 3 else "" for p, sc in zip(parts, rows.sc)]
    rows["state"] = [p[-2].strip() if sc and len(p) >= 4 else "" for p, sc in zip(parts, rows.sc)]
    if lot3:
        rows["ministry"] = [owner(m, s) for m, s in zip(rows.pub, rows.spub)]
        rows["unit"] = rows.ministry + "\x1f" + rows.k
    else:
        rows["ministry"] = rows.pub.fillna("").str.split(r"[,|]").str[0].str.strip()
        rows["unit"] = rows.k
    cut, key_of = (cut_lot3, key_lot3) if lot3 else (lambda t: t, series_key)
    reviewed = lot3_names() if lot3 else {}

    forced = {}
    for name, pats in ({} if lot3 else FORCE_GROUPS).items():
        for k in rows.k.unique():
            if any(re.search(p, k) for p in pats):
                forced[k] = name

    # ---- smart cities: group on (city, topic key)
    sc = rows[rows.sc]
    sc_units = sc.groupby(["k", "city", "state"]).size().rename("n").reset_index()
    sc_units["topic"] = [sc_topic(k, c, st) for k, c, st in zip(sc_units.k, sc_units.city, sc_units.state)]
    sc_units["tkey"] = sc_units.topic.map(topic_key)
    sc_name = {}
    for (city, _), g in sc_units.groupby(["city", "tkey"]):
        topic = best_variant(list(zip(g.topic, g.n)))
        disp = CITY_FIX.get(city, (city, []))[0]
        name = f"{topic} : {disp}" if disp else topic
        for k in g.k:
            sc_name[(k, city)] = name

    # ---- everything else: group on (ministry, series key), keeping good old merges
    ot = rows[~rows.sc]
    units = ot.groupby("unit").agg(k=("k", "first"),
                                   n=("rid", "size"),
                                   ministry=("ministry", "first"),
                                   old=("old", lambda s: next((x for x in s if x), None))).reset_index()
    if lot3:
        units["old"] = None
    units["key"] = [key_of(k) for k in units.k]
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for (_, _), g in units.groupby(["ministry", "key"]):
        for u in g.unit[1:]:
            union(u, g.unit.iloc[0])
    for old, g in units[units.old.notna()].groupby("old"):
        if old in BROKEN_OLD or len(g) < 2:
            continue
        for u in g.unit[1:]:
            union(u, g.unit.iloc[0])
    units["grp"] = units.unit.map(find)

    ot_name = {}
    for _, g in units.groupby("grp"):
        g = g.sort_values("n", ascending=False)
        olds = [o for o in g.old.dropna().unique() if o not in BROKEN_OLD]
        curated = [o for o in olds if o not in set(g.k)]
        if len(g) == 1:
            r = g.iloc[0]
            name = r.old if r.old and r.old not in BROKEN_OLD else r.k
        elif len(curated) == 1:
            name = curated[0]
        elif lot3:
            name = tidy_lot3(series_name(cut(best_variant(list(zip(g.k, g.n))))))
        else:
            name = series_name(best_variant(list(zip(g.k, g.n))))
        if lot3:
            name = reviewed.get((g.ministry.iloc[0], g.key.iloc[0]), name)
        else:
            name = RENAME.get(name, name)
        for u in g.unit:
            ot_name[u] = name

    rows["new"] = [forced.get(k) or (sc_name[(k, c)] if sc else ot_name[u])
                   for k, c, sc, u in zip(rows.k, rows.city, rows.sc, rows.unit)]
    if lot3:
        # one name under two states is two catalogs: "<Name> : <State>", as for the smart cities
        rows["top"] = rows.ministry.str.split(r" / |,", regex=True).str[0].str.strip()
        tops = rows.groupby("new").top.nunique()
        shared = set(tops[tops > 1].index)
        rows["new"] = [f"{n} : {t}" if n in shared and t else n for n, t in zip(rows.new, rows.top)]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--table", default=TABLE, choices=[TABLE, LOT3_TABLE])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    table = args.table

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    con = duckdb.connect(args.db, read_only=not args.apply)
    rows = build(con, table)

    changed = rows[rows.old_raw.fillna("") != rows.new]   # raw, so stray spaces get fixed too
    by = ["ministry", "k", "old", "new"] if table == LOT3_TABLE else ["k", "city", "old", "new"]
    pairs = (rows.groupby(by, dropna=False).size()
             .rename("n").reset_index().sort_values(["new", "k"]))
    out = BACKUPS / f"{table}_new_catalog_title_proposal_{ts}.csv"
    pairs.to_csv(out, index=False)
    print(f"rows {len(rows)}; blank before {rows.old.isna().sum()}, after {(rows.new == '').sum()}")
    print(f"catalog titles {rows.k.nunique()}; new_catalog_title before {rows.old.nunique()}, "
          f"after {rows.new.nunique()}")
    print(f"rows changed {len(changed)}  ({changed.k.nunique()} catalog titles)")
    print(f"proposal: {out}")

    if not args.apply:
        return
    has_col = con.execute("""SELECT count(*) FROM duckdb_columns() WHERE table_name = ?
                             AND column_name = 'new_catalog_title'""", [table]).fetchone()[0]
    if not has_col:
        con.execute(f"ALTER TABLE {table} ADD COLUMN new_catalog_title VARCHAR")
        print(f"added column new_catalog_title to {table}")
    if table == TABLE:
        snap = BACKUPS / f"{table}_new_catalog_title_{ts}.csv"
        con.execute(f"COPY (SELECT nid, new_catalog_title FROM {table}) TO '{snap}' (HEADER)")
        print(f"snapshot: {snap}")
    # by rowid: lot 3 has a row with no nid and one nid that occurs twice
    upd = changed[["rid", "new"]]
    con.register("upd_df", upd)
    con.execute("CREATE TEMP TABLE upd AS SELECT * FROM upd_df")
    con.execute(f"UPDATE {table} t SET new_catalog_title = u.new FROM upd u WHERE t.rowid = u.rid")
    left = con.execute(f"""SELECT count(*) FROM {table} t JOIN upd u ON t.rowid = u.rid
                           WHERE t.new_catalog_title IS DISTINCT FROM u.new""").fetchone()[0]
    con.close()
    print(f"updated {len(upd)} rows; mismatches after update: {left}")


if __name__ == "__main__":
    main()
