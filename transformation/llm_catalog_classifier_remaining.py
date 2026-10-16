"""Catalog-level metadata for remaining_catalog via the OpenAI Batch API.

Copy of llm_batch_classifier.py, re-targeted from datasets to catalogs.

Rows of remaining_catalog are merged on `new_catalog_title` (rows with no
new_catalog_title are skipped), and one request is sent per merged catalog. The
new_catalog_title is the catalog's title; the member catalogs' raw titles,
descriptions, ministries, sectors and jurisdictions are context. The model
returns a sector (SECTOR_VOCAB) and a description, which are written back to
every remaining_catalog row sharing that new_catalog_title as
`generated_sector` / `generated_description`.

The years and states a merged catalog covers are worked out here, not by the
model: from the new_catalog_title when it names them, else from the members
(e.g. "Crime in India" merges 1953..2023 editions, so its description must give
that span, not the year of whichever member it read first). They are sent as
"Temporal scope" / "Geographic scope" lines the prompt treats as ground truth.

Usage:
  python3 llm_catalog_classifier_remaining.py --dry-run --limit 20   # write JSONL only
  python3 llm_catalog_classifier_remaining.py --limit 50            # small live run
  python3 llm_catalog_classifier_remaining.py                       # every pending catalog
  python3 llm_catalog_classifier_remaining.py --poll <batch_id>     # resume one batch
  python3 llm_catalog_classifier_remaining.py --sync                # push CSV -> table
"""
import argparse
import hashlib
import html
import json
import logging
import os
import re
import time
from pathlib import Path

import duckdb
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
load_dotenv()

OUTPUT_DIR = HERE / "text_generation"
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s : %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "catalog_batch_jobs.log", encoding="utf-8"),
    ],
)


DB_PATH = str(HERE / "metadata.db")
SOURCE_TABLE = "remaining_catalog"

MODEL = "gpt-5.4-nano"
POLL_INTERVAL = 60          # seconds between status checks
MAX_CONCURRENT_BATCHES = 2  # 2 x chunk_size must stay under the 2M enqueued-token cap
OUTPUT_CSV = OUTPUT_DIR / "remaining_catalog_llm_results.csv"

# Separate from the dataset job's key: different system prompt, different prefix.
PROMPT_CACHE_KEY = "nic-metadata-catalog-remaining-v3"

# Columns written to remaining_catalog, and the JSON keys they come from.
OUTPUT_COLUMNS = {
    "generated_sector": "generated_sector",
    "generated_description": "generated_description",
}

# Caps on how much member context goes into one request. The biggest group
# ("Crime in India") has 67 members. Member titles mostly differ by the year or
# state the scope lines already carry, so a dozen is enough to show the pattern.
MAX_MEMBER_TITLES = 12
MAX_MEMBER_DESCRIPTIONS = 3
MAX_DESCRIPTION_CHARS = 500
MAX_KEYWORDS = 25


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


catalog_system_prompt = '''
# System Prompt: OGD Catalog Metadata Enrichment

## Role
You are an expert metadata curator for Indian government open data (data.gov.in).
Generate catalog-level metadata following Dublin Core and DCAT v3 standards.

## What a catalog is here
A catalog groups related datasets (resources). Several source catalogs may have
been MERGED under one Catalog Title — e.g. yearly editions of the same report,
the same table for different states, or English/Hindi variants. You receive the
merged Catalog Title plus, where they add anything, the member catalogs' titles
and descriptions. Describe the MERGED catalog as a whole, never a single member.

## Output: Strict JSON
{
  "generated_description": "",
  "generated_sector": ""
}

Return ONLY valid JSON. No markdown fences, no preamble.

## Scope rules (highest priority)
- "Temporal scope" and "Geographic scope" were computed from the Catalog Title
  and all its members. Treat them as ground truth and state them.
- A year/period or place named in the Catalog Title MUST appear in the
  description exactly.
- A span across editions ("1953 to 2023 (67 editions: ...)"): describe the full
  span. NEVER present a single member's year as the catalog's year.
- Several States/UTs: with five or fewer, name them; with more, give only the
  count ("across 34 States/UTs") — do NOT list or abbreviate them ("Andhra
  Pradesh through West Bengal"). Never narrow it to one member's state.
- A Geographic scope of "India" says where the data is from, not its
  granularity. When the titles say "India and States", "State-wise",
  "District-wise" etc., describe it that way — not as "national level" only.
- NEVER mention a year, State/UT, district or city that appears neither in the
  Catalog Title nor in the scope lines.
- A scope line that is ABSENT means that aspect is unknown. Say nothing about
  it: do not invent one, and do not write "not stated", "not specified",
  "unspecified" or similar.
- The scope lines are instructions to you, not text to copy. Work the period
  and place into a sentence naturally ("crime statistics for India from 1953 to
  2023", "for the 1991, 2001 and 2011 Censuses"). Never copy their brackets or
  wording, never add a sentence that only restates the scope, and never write
  meta phrases such as "geographic scope", "temporal scope", "national
  coverage", "listed States/UTs", "editions/periods", "merged members" or
  "provided metadata".

## generated_description (50–90 words)
- 2–4 sentences: what the catalog's datasets cover, key indicators/themes,
  purpose/use cases, publishing ministry/department, geographic and temporal
  scope (per the scope rules), and granularity where evident.
- Do not start with "This catalog contains" or "This dataset contains".
- Do not copy a member description verbatim; synthesise across members.
- Do not hallucinate content not present in or clearly implied by the input.

## generated_sector
Map to SECTOR_VOCAB only. Format: "Sector; Sub-sector" pairs, comma-separated if
multiple. Example: "Agriculture; Agricultural Marketing, Health and Family welfare; Health".
If no sub-sector fits, use sector only. Never invent sectors outside the
vocabulary. Prefer 1–2 pairs; use the source Sector_Resource as a hint only.

SECTOR_VOCAB:
Census and Surveys: Annual Health Survey, Census, Civil Registration System, National Population Register, Sample Registration System, Socio-economic & Caste Census
Census: House listing and Housing Census, Population Enumerator
Agriculture: Agricultural Marketing, Dairying, Agricultural Produces, Agricultural Research & Extension, Animal Husbandry, Crops, Fertilizers, Horticulture, Irrigation, Organic farming, Plant Protection, Seeds, Soil and Water Conservation, Fisheries, Sericulture
Animal Husbandry: Fishery
Art and Culture: Archaeology, Dance, Festivals, Handicrafts, Heritage, Literature, Monuments, Music, Painting, Theatre
Commerce: Companies, Export, Import, SEZs, Trade promotion
Parliament Of india: Rajya Sabha, Lok Sabha
Water and Sanitation: Drinking Water, Sanitation
Information and Communications: Information and Technology, Post, Telecom
Defence: Air Force, Army, Navy, Para Military Forces
Economy: Prices, Macro Economy
Education: Adult Education, Elementary, Higher Education, Secondary
Environment and Forest: Bio-diversity, Biomedical Waste, Ecology, Forest, Forest Resources, Hazardous Waste, Industrial Air Pollution, Municipal Waste, Noise Pollution, Residential Air Pollution, Vehicular Air Pollution, Water Quality, Natural Resources, Sanitation, Wild life
Water Resources: Drinking Water, Ground Water, Surface Water
Finance: Banking, Economy, Revenue, Insurance, Pension Reforms
Food: Consumer Affairs, Consumer Cooperatives, Public Distribution
Foreign Affairs: Consulates, Embassy, NRI, Passport, Visa
Governance and Administration: Constitution, District Adminstration, Grievances, Local Government, Lok Sabha, Pensions, Rajya Sabha, State Legislative, Union/State Government Administration
Health and Family welfare: Family Welfare, Health
Home Affairs and Enforcement: Enforcement Organizations, Internal Security, Police
Housing: EWS Housing, Rural Housing, Urban Housing
Industries: Chemicals and Petrochemicals, Corportae governance, Cottage, Defence Products, Food Processing, Heavy, Insurance, Manufacturing, Medium, Micro, Petroleum and Natural Gas, Pharmaceuticals, Retail, Small Scale, Textiles, Tourism
Textiles: Sericulture
Information and Broadcasting: Broadcasting, Film, Print Media
Infrastructure: Bridges, Dams, Power, Roads
Urban: Development
Judiciary: District Court, High Court, Subordinate Court, Supreme Court
Labour and Employment: Employment, Organized Sector Workers, Unorganized Sector Workers
Power and Energy: Non Renewable, Renewable
Rural: Development, Land Resources, Panchayati Raj
Science and Technology: Atmospheric Science, Coastal & Island, Earth Sciences, Geo Technology, Marine Science, Polar Science, Research & Development
Social Development: Children, Disabled, Minority, Tribal, Women
Transport: Aviation, Metro, Railways, Road Transport, Water ways
Travel and Tourism: Lodging, Modes of Travel, Places
Youth and Sports: Games, Youth Affairs

'''.strip()


# ---------------------------------------------------------------------------
# Scope extraction (years / states) — deterministic, done before the LLM
# ---------------------------------------------------------------------------

# Canonical name -> spellings seen in titles and field_asset_jurisdiction:name.
# Longest spellings are matched first so "Dadra and Nagar Haveli and Daman and
# Diu" wins over "Daman and Diu".
STATE_ALIASES = {
    "Andhra Pradesh": ["andhra pradesh"],
    "Arunachal Pradesh": ["arunachal pradesh"],
    "Assam": ["assam"],
    "Bihar": ["bihar"],
    "Chhattisgarh": ["chhattisgarh", "chattisgarh"],
    "Goa": ["goa"],
    "Gujarat": ["gujarat"],
    "Haryana": ["haryana"],
    "Himachal Pradesh": ["himachal pradesh"],
    "Jharkhand": ["jharkhand"],
    "Karnataka": ["karnataka"],
    "Kerala": ["kerala"],
    "Madhya Pradesh": ["madhya pradesh"],
    "Maharashtra": ["maharashtra"],
    "Manipur": ["manipur"],
    "Meghalaya": ["meghalaya"],
    "Mizoram": ["mizoram"],
    "Nagaland": ["nagaland"],
    "Odisha": ["odisha", "orissa"],
    "Punjab": ["punjab"],
    "Rajasthan": ["rajasthan"],
    "Sikkim": ["sikkim"],
    "Tamil Nadu": ["tamil nadu", "tamilnadu"],
    "Telangana": ["telangana"],
    "Tripura": ["tripura"],
    "Uttar Pradesh": ["uttar pradesh"],
    "Uttarakhand": ["uttarakhand", "uttaranchal"],
    "West Bengal": ["west bengal"],
    "Andaman and Nicobar Islands": ["andaman and nicobar islands", "andaman & nicobar islands",
                                    "andaman and nicobar", "andaman & nicobar"],
    "Chandigarh": ["chandigarh"],
    "Dadra and Nagar Haveli and Daman and Diu": ["dadra and nagar haveli and daman and diu",
                                                 "dadra & nagar haveli and daman & diu"],
    "Dadra and Nagar Haveli": ["dadra and nagar haveli", "dadra & nagar haveli"],
    "Daman and Diu": ["daman and diu", "daman & diu"],
    "Delhi": ["nct of delhi", "delhi"],
    "Jammu and Kashmir": ["jammu and kashmir", "jammu & kashmir"],
    "Ladakh": ["ladakh"],
    "Lakshadweep": ["lakshadweep"],
    "Puducherry": ["puducherry", "pondicherry"],
}
_STATE_PATTERNS = sorted(
    ((alias, canon) for canon, aliases in STATE_ALIASES.items() for alias in aliases),
    key=lambda p: -len(p[0]),
)

NOT_STATED = "Not stated"

# Jurisdiction tokens that are levels, not places.
_JURISDICTION_LEVELS = {"state", "all india", "central", "district", "city", "national", "india", ""}

# 4-digit years 1800-2099, optionally a range/fiscal year: 2015-16, 1976-77, 2001-2011.
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?:\s*[-–/]\s*(\d{4}|\d{2}))?(?!\d)")


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    return "" if s.lower() in ("nan", "none") else s


def _strip_html(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def find_states(text: str) -> list[str]:
    """Canonical State/UT names named in `text`, in order of first appearance."""
    low = f" {text.lower()} "
    found: list[tuple[int, str]] = []
    for alias, canon in _STATE_PATTERNS:
        for m in re.finditer(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low):
            found.append((m.start(), canon))
            # Blank the match so a shorter alias inside it can't match again.
            low = low[:m.start()] + " " * len(alias) + low[m.end():]
    seen, out = set(), []
    for _, canon in sorted(found):
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def find_years(text: str) -> list[tuple[int, int, str]]:
    """[(start_year, end_year, label)] for every year / year-range in `text`."""
    out = []
    for m in _YEAR_RE.finditer(text):
        start = int(m.group(1))
        end = start
        if m.group(2):
            tail = m.group(2)
            end = int(tail) if len(tail) == 4 else (start // 100) * 100 + int(tail)
            if end < start:          # 1999-00 -> 2000
                end += 100
            if end - start > 50:     # not a range, just two unrelated numbers
                end = start
        out.append((start, end, m.group(0).replace(" ", "")))
    return out


def temporal_scope(catalog_title: str, member_titles: list[str]) -> str:
    title_years = find_years(catalog_title)
    if title_years:
        labels = ", ".join(dict.fromkeys(y[2] for y in title_years))
        return f"{labels} (named in the Catalog Title — use exactly this)"

    member_years = [y for t in member_titles for y in find_years(t)]
    if not member_years:
        return NOT_STATED
    member_years.sort()
    labels = list(dict.fromkeys(y[2] for y in member_years))
    if len(labels) == 1:
        return f"{labels[0]} (all member catalogs)"
    if len(labels) <= 5:
        # Few editions (e.g. Census 1991, 2001, 2011): name them, a "span"
        # would imply years in between that the catalog doesn't have.
        return (f"editions {', '.join(labels)} — name these editions; never present "
                f"one of them as the catalog's only period")
    first = member_years[0][2]
    last = max(member_years, key=lambda y: (y[1], y[0]))[2]
    shown = ", ".join(labels[:12]) + (", ..." if len(labels) > 12 else "")
    return (f"{first} to {last} ({len(labels)} editions: {shown}) — describe the "
            f"full span, not one edition")


def geographic_scope(catalog_title: str, member_titles: list[str], jurisdictions: list[str]) -> str:
    title_states = find_states(catalog_title)

    # Smart Cities style "<Topic> : <City>".
    city = ""
    if " : " in catalog_title:
        tail = catalog_title.rsplit(" : ", 1)[1].strip()
        if tail and not find_years(tail) and not find_states(tail):
            city = tail

    jur_tokens = [t.strip() for j in jurisdictions for t in j.split(";")]
    jur_states = find_states(";".join(jur_tokens))
    member_states = find_states(" | ".join(member_titles))
    all_states = list(dict.fromkeys(jur_states + member_states))
    all_india = any(t.lower() == "all india" for t in jur_tokens)

    if city:
        state = title_states or all_states[:1]
        return f"City of {city}" + (f", {state[0]}" if state else "") + " (named in the Catalog Title)"
    if title_states:
        return ", ".join(title_states) + " (named in the Catalog Title — use exactly this)"

    if len(all_states) == 1:
        places = [
            t for t in dict.fromkeys(jur_tokens)
            if t.lower() not in _JURISDICTION_LEVELS and not find_states(t)
        ]
        suffix = f" (places: {', '.join(places[:5])})" if places and len(places) <= 5 else ""
        return f"{all_states[0]}{suffix}"
    if len(all_states) > 1:
        return f"{len(all_states)} States/UTs: {', '.join(all_states)}"
    if all_india:
        return "India"
    return NOT_STATED


# ---------------------------------------------------------------------------
# Loading and grouping
# ---------------------------------------------------------------------------

# "<scope word> ... is/are not stated|specified|..." — the subject has to be the
# scope, so Census categories like "age not stated" are left alone.
_UNKNOWN_SCOPE_RE = re.compile(
    r"\b(temporal|time|period|years?|dates?|geographic\w*|spatial|scope|coverage)\b[^.]*?"
    r"\b(is|are|was|were|has|have)\s+(not|n't)\s+(been\s+)?"
    r"(stated|specified|provided|mentioned|indicated|available|given)\b"
    r"|\b(temporal|geographic\w*|spatial)\s+(scope|coverage)\s+(is\s+)?unspecified\b",
    re.IGNORECASE,
)


# Scope-line wording that leaked into a sentence that otherwise says something useful.
_LEAK_PHRASES = re.compile(
    r",?\s*(?:while\s+|and\s+)?(?:maintaining\s+)?national coverage\b|\s+across the listed States(?:/UTs)?",
    re.IGNORECASE,
)


# Sentences about the metadata itself rather than the data ("reflecting the geographic scope
# indicated in the catalog title", "The publishing authority is not specified in ...").
_META_SENTENCE_RE = re.compile(
    r"geographic scope|temporal scope|in the (provided|given|source) (information|metadata)|"
    r"\b(publishing authority|publisher|ministry|source)\b[^.]*\bnot (stated|specified|provided|available)\b",
    re.IGNORECASE,
)


def scrub_description(text: str) -> str:
    """Drop sentences that only report an unknown scope ("Temporal coverage is not specified.")."""
    text = _LEAK_PHRASES.sub("", text)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [x for x in sentences if not (_UNKNOWN_SCOPE_RE.search(x) or _META_SENTENCE_RE.search(x))]
    return " ".join(kept) if kept else text.strip()


def _parse_vocab() -> dict[str, list[str]]:
    block = catalog_system_prompt.split("SECTOR_VOCAB:")[1].split("\n## ")[0]
    vocab = {}
    for line in block.strip().splitlines():
        if ":" in line:
            sector, subs = line.split(":", 1)
            vocab[sector.strip()] = [x.strip() for x in subs.split(",")]
    return vocab


SECTOR_VOCAB = _parse_vocab()
_ALL_SUBSECTORS = {sub for subs in SECTOR_VOCAB.values() for sub in subs}

# Near-misses the model produced in the full run (sector, wrong sub) -> right sub.
SUBSECTOR_FIX = {
    ("Governance and Administration", "Local Government Administration"): "Local Government",
    ("Information and Communications", "Information Technology"): "Information and Technology",
    ("Urban", "Urban Development"): "Development",
    ("Agriculture", "Fishery"): "Fisheries",
}


# The 12 catalogs whose model sector had nothing in the vocabulary ("Statistics",
# "Biotechnology; Biotechnology", ...). Assigned by hand 2026-10-05 from each
# catalog's content and source sector; matched on the start of new_catalog_title.
MANUAL_SECTORS = {
    "Crimes : Tumakuru": "Home Affairs and Enforcement; Police",
    "Demographic Profile : Erode": "Census and Surveys; Census",
    "Digital India Land Records Modernization Programme Progress": "Rural; Land Resources",
    "District-wise Key Performance Indicators": "Rural; Land Resources",
    "Hotels : Chandigarh": "Travel and Tourism; Lodging",
    "Household Profile : Jalandhar": "Census and Surveys; Census",
    "Informal Non-Agricultural Enterprises Survey: NSS": "Census and Surveys",
    "No of Vehicle Registration : Kohima": "Transport; Road Transport",
    "Number of Reporting Mines In India": "Industries",
    "Published Quadrangle Geological map of Degree Sheet": "Science and Technology; Earth Sciences",
    "State-wise Number of Societal Development Proposals Not Found Suitable": "Science and Technology; Research & Development",
    "State-wise Ongoing Societal Development Projects": "Science and Technology; Research & Development",
    # lot 3 (2026-10-08)
    "Cuddalore District Hand Book 2017-18 : Non-Conventional Energy": "Power and Energy; Renewable",
    "District Hand Book : Non-Conventional Energy Generation": "Power and Energy; Renewable",
    "Ayush Colleges in India": "Health and Family welfare; Health",
    "Application wise Document Count, Stamp Duty and Registration Fees": "Finance; Revenue",
}


def manual_sector(catalog_title: str) -> str:
    return next((v for k, v in MANUAL_SECTORS.items() if catalog_title.startswith(k)), "")


def normalise_sector(value: str) -> str:
    """Make generated_sector conform to SECTOR_VOCAB, never adding anything new.

    The model (like the source field_sector:name) emits a flat run of terms —
    "Education; Elementary, Education; Secondary", "Development; Urban",
    "Economy; Finance" — so every ";" / "," separated term is classified on its own:
      * a sector starts a group, unless it is also a sub-sector of the current
        group ("Census and Surveys; Census" keeps Census as the sub-sector);
      * a sub-sector joins the current group, or the NEXT sector when it came first;
      * anything outside the vocabulary is dropped (SUBSECTOR_FIX maps the known
        near-misses first). A sector with no sub-sector is allowed, an invented
        one is not.
    Output is "Sector; Sub, Sector; Sub" — one pair per sub-sector, bare sector if none.
    """
    groups: dict[str, list[str]] = {}
    current = None
    pending: list[str] = []          # sub-sectors seen before their sector
    for tok in (t.strip() for t in re.split(r"[;,]", value)):
        if not tok:
            continue
        tok = SUBSECTOR_FIX.get((current, tok), tok)
        if current and tok in SECTOR_VOCAB[current]:
            groups[current].append(tok)
        elif tok in SECTOR_VOCAB:
            current = tok
            groups.setdefault(current, []).extend(x for x in pending if x in SECTOR_VOCAB[current])
            pending = []
        elif tok in _ALL_SUBSECTORS:
            pending.append(tok)
    out = []
    for sector, subs in groups.items():
        subs = list(dict.fromkeys(subs))
        out += [f"{sector}; {sub}" for sub in subs] if subs else [sector]
    return ", ".join(out)


def custom_id_for(catalog_title: str) -> str:
    """Stable, short request id — new_catalog_title itself is too long for custom_id."""
    return "cat_" + hashlib.sha1(catalog_title.encode("utf-8")).hexdigest()[:20]


def _distinct(values) -> list[str]:
    out = []
    for v in values:
        v = _clean(v)
        if v and v not in out:
            out.append(v)
    return out


def _split_distinct(values) -> list[str]:
    return _distinct(p.strip() for v in values for p in _clean(v).split(";"))


def load_groups(db_path: str, title_filter: str | None = None, unnamed: bool = False) -> pd.DataFrame:
    """One row per new_catalog_title, with the member context and computed scopes.

    unnamed=True instead covers the rows that have NO new_catalog_title and no generated
    text yet: each distinct source title is its own catalog (nothing is merged) and
    new_catalog_title is left untouched in the table.
    """
    con = duckdb.connect(db_path, read_only=True)
    name = "trim(title)" if unnamed else "trim(new_catalog_title)"
    where = ("(new_catalog_title IS NULL OR trim(new_catalog_title) = '') "
             "AND coalesce(trim(generated_description), '') = ''") if unnamed else \
            "new_catalog_title IS NOT NULL AND trim(new_catalog_title) <> ''"
    df = con.execute(f"""
        SELECT nid, title, "body:value" AS body,
               "field_asset_jurisdiction:name" AS jurisdiction,
               "field_ministry_department:name" AS ministry,
               "field_sector:name" AS sector,
               keywords, {name} AS new_catalog_title
        FROM {SOURCE_TABLE}
        WHERE {where}
        ORDER BY 8, nid
    """).fetchdf()
    con.close()

    if title_filter:
        df = df[df["new_catalog_title"].str.contains(title_filter, case=False, regex=False)]

    groups = []
    for catalog_title, g in df.groupby("new_catalog_title", sort=True):
        member_titles = sorted(_distinct(g["title"]), key=str.lower)
        descriptions = _distinct(_strip_html(_clean(b)) for b in g["body"])
        jurisdictions = _distinct(g["jurisdiction"])
        groups.append({
            "custom_id": custom_id_for(("unnamed:" if unnamed else "") + catalog_title),
            "new_catalog_title": catalog_title,
            "unnamed": unnamed,
            "member_count": len(g),
            "member_nids": ";".join(str(n) for n in g["nid"]),
            "member_titles": member_titles,
            "descriptions": descriptions,
            "ministries": _distinct(g["ministry"]),
            "sectors": _split_distinct(g["sector"]),
            "keywords": _split_distinct(g["keywords"]),
            "temporal_scope": temporal_scope(catalog_title, member_titles),
            "geographic_scope": geographic_scope(catalog_title, member_titles, jurisdictions),
        })
    out = pd.DataFrame(groups)
    if unnamed:
        logging.info(f"Loaded {len(df)} unnamed catalog rows -> {len(out)} single-title catalogs")
        return out
    skipped = count_skipped(db_path)
    logging.info(
        f"Loaded {len(df)} catalog rows -> {len(out)} merged catalogs "
        f"({skipped} rows with no new_catalog_title skipped)"
    )
    return out


def count_skipped(db_path: str) -> int:
    con = duckdb.connect(db_path, read_only=True)
    n = con.execute(
        f"SELECT count(*) FROM {SOURCE_TABLE} "
        f"WHERE new_catalog_title IS NULL OR trim(new_catalog_title) = ''"
    ).fetchone()[0]
    con.close()
    return n


def _same_title(a: str, b: str) -> bool:
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    return norm(a) == norm(b)


def build_user_content(group: dict) -> str:
    """Only fields the model uses for the description or the sector; empty ones are left out."""
    lines = [f"Catalog Title: {group['new_catalog_title']}"]
    # An unknown scope is sent as no line at all: given "Not stated" the model
    # writes "temporal coverage is not specified" into the description.
    for label, key in (("Temporal scope", "temporal_scope"), ("Geographic scope", "geographic_scope")):
        if group[key] != NOT_STATED:
            lines.append(f"{label}: {group[key]}")

    # 4,837 of 6,004 catalogs have one member whose title IS the catalog title;
    # repeating it adds nothing.
    titles = [t for t in group["member_titles"] if not _same_title(t, group["new_catalog_title"])]
    if group["member_count"] > 1:
        lines.append(f"Merged member catalogs: {group['member_count']}")
    if titles:
        shown = titles[:MAX_MEMBER_TITLES]
        lines.append("Member catalog titles:")
        lines += [f"  - {t}" for t in shown]
        if len(titles) > len(shown):
            lines.append(f"  ... and {len(titles) - len(shown)} more")

    descs = [d[:MAX_DESCRIPTION_CHARS] for d in group["descriptions"][:MAX_MEMBER_DESCRIPTIONS]]
    if descs:
        lines.append("Member descriptions:")
        lines += [f"  - {d}" for d in descs]

    for label, values in (("Ministry_Department", group["ministries"]),
                          ("Sector_Resource", group["sectors"]),
                          ("Keywords", group["keywords"][:MAX_KEYWORDS])):
        if values:
            lines.append(f"{label}: {'; '.join(values)}")
    return "\n".join(lines)


def build_request_line(group: dict) -> dict:
    return {
        "custom_id": group["custom_id"],
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": MODEL,
            "response_format": {"type": "json_object"},
            "prompt_cache_retention": "24h",
            "prompt_cache_key": PROMPT_CACHE_KEY,
            # See llm_batch_classifier.py: temperature 0 roughly halves
            # run-to-run disagreement on the sector field.
            "temperature": 0,
            "seed": 42,
            "messages": [
                {"role": "system", "content": catalog_system_prompt},
                {"role": "user", "content": build_user_content(group)},
            ],
        },
    }


def done_titles(db_path: str) -> set[str]:
    """new_catalog_titles already generated — from the results CSV and the table."""
    done: set[str] = set()
    if OUTPUT_CSV.exists():
        prev = pd.read_csv(OUTPUT_CSV, usecols=["new_catalog_title", "generated_description"])
        done |= set(prev.loc[prev["generated_description"].fillna("").str.strip() != "",
                             "new_catalog_title"])
    try:
        con = duckdb.connect(db_path, read_only=True)
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [SOURCE_TABLE]).fetchall()}
        if "generated_description" in cols:
            done |= {r[0] for r in con.execute(
                f"SELECT DISTINCT trim(new_catalog_title) FROM {SOURCE_TABLE} "
                f"WHERE coalesce(trim(generated_description), '') <> ''").fetchall()}
        con.close()
    except duckdb.IOException as e:
        logging.warning(f"Could not read {SOURCE_TABLE} for done titles ({e}); using CSV only")
    return done


# ---------------------------------------------------------------------------
# OpenAI Batch plumbing (unchanged from llm_batch_classifier.py apart from ids)
# ---------------------------------------------------------------------------

def write_requests(groups: pd.DataFrame, suffix: str = "") -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    jsonl_path = OUTPUT_DIR / f"catalog_batch_requests_{ts}{suffix}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for _, row in groups.iterrows():
            f.write(json.dumps(build_request_line(row.to_dict()), ensure_ascii=False) + "\n")
    logging.info(f"Wrote {len(groups)} requests to {jsonl_path}")
    return jsonl_path


def upload_requests(groups: pd.DataFrame, suffix: str = "") -> str:
    jsonl_path = write_requests(groups, suffix)
    with open(jsonl_path, "rb") as f:
        uploaded = client.files.create(file=(jsonl_path.name, f, "application/jsonl"), purpose="batch")
    logging.info(f"Uploaded {jsonl_path.name} → file_id={uploaded.id}")
    return uploaded.id


def submit_batch(file_id: str) -> str:
    batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"project": "nic-metadata-cleaning", "model": MODEL, "job": "remaining_catalog"},
    )
    logging.info(f"Batch submitted - batch_id={batch.id}  status={batch.status}")
    return batch.id


def poll_batch(batch_id: str) -> object:
    """Block until the batch reaches a terminal state, return the batch object."""
    terminal = {"completed", "failed", "cancelled", "expired"}
    while True:
        batch = client.batches.retrieve(batch_id)
        counts = batch.request_counts
        logging.info(
            f"[{batch_id}] status={batch.status} error_file_id={batch.error_file_id} "
            f"total={counts.total}  completed={counts.completed}  failed={counts.failed}"
        )
        if batch.status in terminal:
            return batch
        time.sleep(POLL_INTERVAL)


def poll_all_batches(batch_ids: list[str]) -> list[object]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=len(batch_ids)) as executor:
        future_to_id = {executor.submit(poll_batch, bid): bid for bid in batch_ids}
        for future in as_completed(future_to_id):
            results[future_to_id[future]] = future.result()
    return [results[bid] for bid in batch_ids]


def download_results(batch) -> dict[str, dict]:
    """Returns {custom_id: parsed_result_dict}. Errors are logged but not raised."""
    if batch.status != "completed" or not batch.output_file_id:
        logging.error(f"Batch {batch.id} ended status={batch.status} output_file_id={batch.output_file_id}")
        if batch.error_file_id:
            logging.error(f"Error file contents:\n{client.files.content(batch.error_file_id).text}")
        return {}

    raw = client.files.content(batch.output_file_id).text
    results: dict[str, dict] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        cid = obj["custom_id"]
        try:
            content = obj["response"]["body"]["choices"][0]["message"]["content"]
            results[cid] = json.loads(content)
        except Exception as e:
            logging.warning(f"{cid}: failed to parse response — {e}")
            results[cid] = {}
    logging.info(f"Parsed {len(results)} result(s) from output file")

    raw_path = OUTPUT_DIR / f"catalog_batch_output_{batch.id}.jsonl"
    raw_path.write_text(raw, encoding="utf-8")
    logging.info(f"Raw output saved to {raw_path}")
    return results


def _submit_with_autosplit(groups: pd.DataFrame, suffix: str = "") -> list[str]:
    from openai import BadRequestError

    if len(groups) == 0:
        return []
    try:
        return [submit_batch(upload_requests(groups, suffix=suffix))]
    except BadRequestError as e:
        err = str(e).lower()
        # "Billing hard limit has been reached" also says "limit", but halving
        # the batch can't fix it — fail straight away instead of splitting.
        size_error = "billing" not in err and any(
            k in err for k in ("maximum", "limit", "exceed", "too large", "too many"))
        if len(groups) > 1 and size_error:
            mid = len(groups) // 2
            logging.warning(f"Batch limit exceeded ({len(groups)} rows) — splitting into {mid} + {len(groups) - mid}.")
            return (_submit_with_autosplit(groups.iloc[:mid], suffix=f"{suffix}_a")
                    + _submit_with_autosplit(groups.iloc[mid:], suffix=f"{suffix}_b"))
        logging.error(f"Batch submission failed ({len(groups)} rows): {e}")
        raise


def _retry_failed_batches(batches: list) -> list:
    """Resubmit any batch that ended non-completed (e.g. token_limit_exceeded), once."""
    out = []
    for batch in batches:
        if batch.status == "completed":
            out.append(batch)
            continue
        reason = ""
        if getattr(batch, "errors", None) and getattr(batch.errors, "data", None):
            reason = "; ".join(e.code or "" for e in batch.errors.data)
        logging.warning(f"Batch {batch.id} ended status={batch.status} ({reason or 'no detail'}) — resubmitting once.")
        try:
            retried = client.batches.create(
                input_file_id=batch.input_file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"project": "nic-metadata-cleaning", "model": MODEL,
                          "job": "remaining_catalog", "retry_of": batch.id},
            )
            out.append(poll_batch(retried.id))
        except Exception as e:
            logging.error(f"Retry of {batch.id} could not be submitted: {e}")
            out.append(batch)
    return out


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_results(groups: pd.DataFrame, results: dict[str, dict], db_path: str) -> pd.DataFrame:
    """Append to the results CSV, then write the columns onto remaining_catalog."""
    records = []
    for _, g in groups.iterrows():
        r = results.get(g["custom_id"])
        if r is None:
            continue
        records.append({
            "new_catalog_title": g["new_catalog_title"],
            "custom_id": g["custom_id"],
            "member_count": g["member_count"],
            "member_nids": g["member_nids"],
            "unnamed": "1" if g.get("unnamed") else "",
            "temporal_scope": g["temporal_scope"],
            "geographic_scope": g["geographic_scope"],
            "generated_sector": _clean(r.get("generated_sector", "")),
            "generated_description": scrub_description(_clean(r.get("generated_description", ""))),
            "llm_response": json.dumps(r, ensure_ascii=False),
        })
    if not records:
        logging.warning("save_results: no matching results — nothing written.")
        return pd.DataFrame()

    res = pd.DataFrame(records)
    res.to_csv(OUTPUT_CSV, mode="a", header=not OUTPUT_CSV.exists(), index=False, encoding="utf-8")
    logging.info(f"Appended {len(res)} rows to {OUTPUT_CSV}")

    try:
        write_to_table(res, db_path)
    except duckdb.IOException as e:
        # Usually DBeaver holding the lock. The CSV has everything; --sync later.
        logging.error(f"Could not write {SOURCE_TABLE} ({e}). Results are in the CSV — run --sync later.")
    return res


def write_unnamed(res: pd.DataFrame, db_path: str) -> None:
    """Rows with no new_catalog_title: update by nid (member_nids), in one transaction."""
    if res.empty:
        return
    res = res.drop_duplicates("custom_id", keep="last").copy()
    res["generated_sector"] = res["generated_sector"].fillna("").map(normalise_sector)
    res["generated_description"] = res["generated_description"].map(scrub_description)
    rows = [(nid, r.generated_sector, r.generated_description)
            for r in res.itertuples() for nid in str(r.member_nids).split(";") if nid]
    upd = pd.DataFrame(rows, columns=["nid", "generated_sector", "generated_description"])
    con = duckdb.connect(db_path)
    for col in OUTPUT_COLUMNS:
        con.execute(f"ALTER TABLE {SOURCE_TABLE} ADD COLUMN IF NOT EXISTS {col} VARCHAR")
    con.register("upd_df", upd)
    con.execute("CREATE OR REPLACE TEMP TABLE upd_n AS SELECT * FROM upd_df")
    total_before = con.execute(f"SELECT count(*) FROM {SOURCE_TABLE}").fetchone()[0]
    expected = con.execute(f"SELECT count(*) FROM {SOURCE_TABLE} t JOIN upd_n u ON t.nid = u.nid").fetchone()[0]
    con.execute("BEGIN")
    try:
        assert expected == len(upd), f"{expected} rows match, expected {len(upd)} (duplicate or missing nid)"
        con.execute(f"""UPDATE {SOURCE_TABLE} SET generated_sector = u.generated_sector,
                        generated_description = u.generated_description
                        FROM upd_n u WHERE {SOURCE_TABLE}.nid = u.nid
                        AND coalesce(trim({SOURCE_TABLE}.new_catalog_title), '') = ''""")
        written = con.execute(f"""SELECT count(*) FROM {SOURCE_TABLE} t JOIN upd_n u ON t.nid = u.nid
                                  WHERE t.generated_description IS NOT DISTINCT FROM u.generated_description""").fetchone()[0]
        assert written == expected, f"{written} rows carry the new text, expected {expected}"
        assert con.execute(f"SELECT count(*) FROM {SOURCE_TABLE}").fetchone()[0] == total_before
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    logging.info(f"Updated {expected} unnamed {SOURCE_TABLE} rows across {len(res)} catalogs (by nid)")


def write_to_table(res: pd.DataFrame, db_path: str) -> None:
    """One UPDATE ... FROM a temp table, keyed on new_catalog_title, in one transaction."""
    res = res[res["generated_description"].str.strip() != ""]
    if "unnamed" in res.columns:
        flag = res["unnamed"].fillna("").astype(str) == "1"
        write_unnamed(res[flag], db_path)
        res = res[~flag]
    res = res.drop_duplicates("new_catalog_title", keep="last").copy()
    if res.empty:
        return
    res["generated_sector"] = res["generated_sector"].fillna("").map(normalise_sector)
    blank = res["generated_sector"] == ""
    res.loc[blank, "generated_sector"] = res.loc[blank, "new_catalog_title"].map(manual_sector)
    res["generated_description"] = res["generated_description"].map(scrub_description)

    con = duckdb.connect(db_path)
    # Outside the transaction: DuckDB can't UPDATE a table altered in the same one.
    for col in OUTPUT_COLUMNS:
        con.execute(f"ALTER TABLE {SOURCE_TABLE} ADD COLUMN IF NOT EXISTS {col} VARCHAR")

    upd = res[["new_catalog_title", *OUTPUT_COLUMNS]]
    con.register("upd_df", upd)
    con.execute("CREATE OR REPLACE TEMP TABLE upd AS SELECT * FROM upd_df")
    join = f"{SOURCE_TABLE} t JOIN upd ON trim(t.new_catalog_title) = upd.new_catalog_title"
    total_before = con.execute(f"SELECT count(*) FROM {SOURCE_TABLE}").fetchone()[0]
    expected = con.execute(f"SELECT count(*) FROM {join}").fetchone()[0]

    sets = ", ".join(f"{c} = upd.{c}" for c in OUTPUT_COLUMNS)
    same = " AND ".join(f"t.{c} IS NOT DISTINCT FROM upd.{c}" for c in OUTPUT_COLUMNS)
    con.execute("BEGIN")
    try:
        con.execute(f"""
            UPDATE {SOURCE_TABLE} SET {sets}
            FROM upd WHERE trim({SOURCE_TABLE}.new_catalog_title) = upd.new_catalog_title
        """)
        written = con.execute(f"SELECT count(*) FROM {join} WHERE {same}").fetchone()[0]
        total_after = con.execute(f"SELECT count(*) FROM {SOURCE_TABLE}").fetchone()[0]
        assert written == expected, f"{written} rows carry the new values, expected {expected}"
        assert total_after == total_before, f"row count changed {total_before} -> {total_after}"
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    logging.info(f"Updated {expected} {SOURCE_TABLE} rows across {len(upd)} catalogs")


def sync_from_csv(db_path: str) -> None:
    """Push every result in the CSV into remaining_catalog (after a lock failure)."""
    if not OUTPUT_CSV.exists():
        logging.error(f"{OUTPUT_CSV} does not exist")
        return
    res = pd.read_csv(OUTPUT_CSV, dtype=str).fillna("")
    write_to_table(res, db_path)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_batch_job(
    db_path: str,
    limit: int | None = None,
    offset: int = 0,
    chunk_size: int = 390,
    title_filter: str | None = None,
    redo: bool = False,
    dry_run: bool = False,
    unnamed: bool = False,
) -> list[str]:
    groups = load_groups(db_path, title_filter, unnamed=unnamed)
    if not redo and not unnamed:
        done = done_titles(db_path)
        before = len(groups)
        groups = groups[~groups["new_catalog_title"].isin(done)]
        logging.info(f"Skipping {before - len(groups)} catalogs already generated ({len(groups)} pending)")
    groups = groups.iloc[offset:]
    if limit is not None:
        groups = groups.iloc[:limit]
    if groups.empty:
        logging.warning("Nothing to process.")
        return []

    if dry_run:
        path = write_requests(groups, suffix="_dryrun")
        print(f"Dry run: {len(groups)} requests written to {path} (nothing uploaded)")
        return []

    chunks = [groups.iloc[i:i + chunk_size] for i in range(0, len(groups), chunk_size)]
    logging.info(f"Split {len(groups)} catalogs into {len(chunks)} chunk(s) of up to {chunk_size}")

    all_batch_ids: list[str] = []
    saved = 0
    n_windows = (len(chunks) + MAX_CONCURRENT_BATCHES - 1) // MAX_CONCURRENT_BATCHES
    for window_start in range(0, len(chunks), MAX_CONCURRENT_BATCHES):
        window = chunks[window_start:window_start + MAX_CONCURRENT_BATCHES]
        window_no = window_start // MAX_CONCURRENT_BATCHES + 1
        window_ids: list[str] = []
        for idx, chunk in enumerate(window):
            global_idx = window_start + idx + 1
            logging.info(f"Submitting chunk {global_idx}/{len(chunks)} ({len(chunk)} catalogs) — window {window_no}")
            window_ids.extend(_submit_with_autosplit(chunk, suffix=f"_chunk{global_idx}"))

        logging.info(f"Window {window_no}: polling {window_ids}")
        completed = _retry_failed_batches(poll_all_batches(window_ids))

        window_results: dict[str, dict] = {}
        for batch in completed:
            window_results.update(download_results(batch))
        if window_results:
            saved += len(save_results(pd.concat(window), window_results, db_path))

        all_batch_ids.extend(window_ids)
        logging.info(f"Window {window_no}/{n_windows} done. {saved}/{len(groups)} catalogs saved so far.")

    logging.info(f"All done. {saved} catalogs over {len(all_batch_ids)} batch job(s).")
    return all_batch_ids


def resume_poll(batch_id: str, db_path: str) -> None:
    """Resume an already-submitted batch; custom_ids map back via new_catalog_title hashes."""
    batch = poll_batch(batch_id)
    input_text = client.files.content(batch.input_file_id).text
    ids = {json.loads(line)["custom_id"] for line in input_text.splitlines() if line.strip()}
    groups = load_groups(db_path)
    groups = groups[groups["custom_id"].isin(ids)]
    logging.info(f"Matched {len(groups)}/{len(ids)} custom_ids to current new_catalog_titles")
    save_results(groups, download_results(batch), db_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Catalog metadata (sector, description) for remaining_catalog, merged on new_catalog_title")
    parser.add_argument("--db", default=DB_PATH, help=f"DuckDB path (default: {DB_PATH})")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of merged catalogs")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N pending catalogs (title order)")
    parser.add_argument("--title", type=str, default=None,
                        help="Only catalogs whose new_catalog_title contains this text (case-insensitive)")
    parser.add_argument("--chunk-size", type=int, default=390, help="Catalogs per OpenAI batch (default: 390)")
    parser.add_argument("--unnamed", action="store_true",
                        help="Only the rows with no new_catalog_title and no generated text: each "
                             "distinct title is its own catalog, written back by nid")
    parser.add_argument("--redo", action="store_true", help="Regenerate catalogs that already have results")
    parser.add_argument("--dry-run", action="store_true", help="Write the request JSONL only; don't upload")
    parser.add_argument("--poll", type=str, default=None, metavar="BATCH_ID",
                        help="Resume polling an existing batch job by its ID")
    parser.add_argument("--sync", action="store_true",
                        help="Write every result in the CSV into remaining_catalog (no API calls)")
    args = parser.parse_args()

    if args.sync:
        sync_from_csv(args.db)
    elif args.poll:
        resume_poll(args.poll, args.db)
    else:
        batch_ids = run_batch_job(args.db, limit=args.limit, offset=args.offset,
                                  chunk_size=args.chunk_size, title_filter=args.title,
                                  redo=args.redo, dry_run=args.dry_run, unnamed=args.unnamed)
        if batch_ids:
            print(f"\nDone. batch_ids={batch_ids}")
            print(f"CSV → {OUTPUT_CSV}")
            print(f"DB  → {args.db}::{SOURCE_TABLE} ({', '.join(OUTPUT_COLUMNS)})")
