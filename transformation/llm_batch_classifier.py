import argparse
import json
import logging
import os
import sys
import time
import tempfile
import duckdb
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_log_file = os.path.join(os.path.dirname(__file__), "text_generation", "batch_jobs.log")
os.makedirs(os.path.dirname(_log_file), exist_ok=True)

logging.basicConfig(
    format="%(asctime)s : %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)



DB_PATH = os.path.join(os.path.dirname(__file__), "metadata.db")
SOURCE_TABLE = "dublin_core_lot3"
RESULTS_TABLE = "llm_keyword_results_lot3"

MODEL = "gpt-5.4-nano"
POLL_INTERVAL = 60          # seconds between status checks
MAX_CONCURRENT_BATCHES = 2  # 2 x chunk_size must stay under the 2M enqueued-token cap
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "text_generation")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "llm_keyword_results.csv")

# Constant across every request so the Batch API routes same-prefix requests to
# the same machine — without it the shared system prompt measured a 0% cache hit
# rate on gpt-5.4-nano, while the (longer) collection prompt hit 82-85%.
PROMPT_CACHE_KEY = "nic-metadata-dataset-v1"

# Fields pulled from the source table for each request. `build_user_content`
# reads rows by these names, so every source table aliases its own columns to
# them in SOURCES below.
SOURCE_FIELDS = [
    "nid", "Title", "Relation[Catalog Title]",
    "Note", "Accrual Periodicity", "Jurisdiction", "Coverage",
    "Publisher[ministry_department]", "Subject[sector_resource]",
]

# {source name: {table, columns {SOURCE_FIELDS name: actual column}}}.
# dublin_core_metadata already uses the Dublin names, so it maps to itself and
# is resolved case-insensitively against the live schema; remaining-raw-datasets
# carries the raw snake_case names and needs an explicit mapping.
SOURCES = {
    "dublin": {
        "table": "dublin_core_metadata",
        "columns": {c: c for c in SOURCE_FIELDS},
    },
    "lot3": {
        "table": SOURCE_TABLE,
        "columns": {c: c for c in SOURCE_FIELDS},
    },
    "remaining": {
        "table": "remaining-raw-datasets",
        "columns": {
            "nid": "nid",
            "Title": "title",
            "Relation[Catalog Title]": "catalog_title",
            "Note": "note",
            "Accrual Periodicity": "frequency",
            "Jurisdiction": "govt_type",
            "Coverage": "granularity",
            "Publisher[ministry_department]": "ministry_department",
            "Subject[sector_resource]": "sector_resource",
        },
    },
}



client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



categorize_system_prompt='''
# Optimized System Prompt: OGD Metadata Enrichment

## Role
You are an expert metadata curator for Indian government open data. Generate enriched metadata fields from dataset resource metadata following Dublin Core and DCAT v3 standards.

## Input Fields
title, catalog_title, ministry_department, sector_resource, note, frequency, govt_type, granularity.
Semicolon-separated values in any field should be parsed individually.

## Output: Strict JSON
{
  "generated_title": "",
  "generated_description": "",
  "generated_note": "",
  "generated_alt_title": "",
  "generated_short_description": "",
  "generated_theme": ""
}

Return ONLY valid JSON. No markdown fences, no preamble.

## Field Specifications
### generated_title (10–20 words, Title Case)
ONLY TRY TO ATTEMPT CHANGING WHEN ABSOLUTELY NECESSARY. Compare your draft to the original: if you changed fewer than 2 substantive words (ignoring casing). 
- NEVER inject the sector_resource, ministry name, or catalog_title context into the title. Those fields exist separately — the title must not duplicate them.
- If multiple datasets share the same title pattern (e.g. monthly reports differing only by month), apply the EXACT same transformation to each — do not vary phrasing, prepositions, or punctuation across the batch.
- These are titles for health and medical datasets published on India's Open Government Data (OGD) Exchange platform. Apply domain awareness when interpreting abbreviations and terminology.
- Well-known medical and public health acronyms (TB, HIV, AIDS, NCD, ASHA, ANM, OPD, IPD, MCH, ANC, etc.) must remain fully uppercase — never apply Title Case to individual letters within an acronym.
- Expand non-obvious abbreviations (KCC → Kisan Call Centre, RoC → Registrars of Companies), but do NOT expand standard medical acronyms — leave TB as TB, HIV as HIV, etc.
- Preserve punctuation from the original title (e.g., commas, hyphens, colons) unless it is clearly erroneous.
- NEVER DROP A GEOGRAPHIC NAME THAT IS ALREADY IN THE SOURCE TITLE. Every state, UT, division, district, sub-district, tehsil, taluk, block, city or village named in the source title MUST still be present in the generated title.
- In particular, when the source names an administrative unit TOGETHER WITH ITS PARENT ("<District> District of <State>", "<Taluk> Taluk of <State>", "<Block> Block of <District>"), keep BOTH parts. Compressing the parent away is WRONG — a district name alone is ambiguous, because many districts share a name across states, and these datasets are published one per district.
    - "... for Scheduled Tribe (Each Tribe Separately) for Koriya District of Chhattisgarh, 2001" → "... for Scheduled Tribe in Koriya District, Chhattisgarh, 2001"   (state RETAINED)
    - WRONG: "... for Scheduled Tribe in Koriya District, 2001"   (state silently lost)
    - "... for Udupi District of Karnataka" → "... for Udupi District, Karnataka"   (state RETAINED)
  You may change the connecting words ("of" → a comma) but never the names themselves.
- This retention rule OUTRANKS the 10–20 word guidance and every shortening instruction below: if the title cannot fit the word budget, shorten the subject wording, never the geography. A slightly long title is always better than one missing its state or district.
- Add geographic scope ("in India" / state name) ONLY if genuinely unclear from context. This permits ADDING a missing scope; it never licenses REMOVING a scope that the source title already carries.
- Add temporal range ONLY if absent from the original title.
- Do not rephrase temporal markers unnecessarily (e.g., keep "upto March 2015-16" as "upto March 2015-16" — do not change it to "as on", "as of", or put it in brackets).
- No redundancy with catalog_title.
- Do not hallucinate content not present in or clearly implied by the source metadata.
- Change the title if title is less than 3-4 words or is too vague on its own
- Do not use terms like "in India" or "Number of" if they are already implied by the context of the dataset and do not add meaningful specificity. For example, a title like "Monthly IUD Distribution Report" may not need "in India" added if it's already clear from the context that this dataset is about IUD distribution in India.

### generated_description (40–60 words)
- 2–3 sentences: what the dataset contains, its purpose/use cases, source ministry, geographic & temporal scope, granularity, and update frequency.
- Avoid Starting with "This dataset contains..."
### generated_note (20–75 words, or "" if not needed)
- Dont generate for all dataset only some if there's useful operational/technical context to add (methodology, source portal, data quality notes, related datasets). Empty string if not relevant, only some datasets require note.

### generated_alt_title (8–15 words, Title Case)
- Different perspective from main title. Simpler language, colloquial terms, SEO-friendly.

### generated_short_description (20–40 words)
- 1–2 sentences. What + why. No technical details. For quick previews.

### generated_theme
Map to SECTOR_VOCAB only. Format: "Sector; Sub-sector" pairs, comma-separated if multiple. Example: "Agriculture; Agricultural Marketing, Health and Family welfare; Health". If no sub-sector fits, use sector only. Never invent sectors outside the vocabulary.

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

## Reference: Indian States, Union Territories and Common Title Variants
Reference data only — use it to RECOGNISE geographic names that appear in a
title. Do NOT rewrite, modernise, correct or expand a geographic name that the
source title already uses, and never add a name from this list that the title
does not contain. The title rules above take precedence.

States: Andhra Pradesh, Arunachal Pradesh, Assam, Bihar, Chhattisgarh, Goa,
Gujarat, Haryana, Himachal Pradesh, Jharkhand, Karnataka, Kerala, Madhya
Pradesh, Maharashtra, Manipur, Meghalaya, Mizoram, Nagaland, Odisha, Punjab,
Rajasthan, Sikkim, Tamil Nadu, Telangana, Tripura, Uttar Pradesh, Uttarakhand,
West Bengal.

Union Territories: Andaman and Nicobar Islands, Chandigarh, Dadra and Nagar
Haveli and Daman and Diu, Delhi (NCT of Delhi), Jammu and Kashmir, Ladakh,
Lakshadweep, Puducherry.

Historic state/UT spellings common in older OGD titles, shown so you can
recognise them — NOT a mandate to change them: Orissa (Odisha), Pondicherry
(Puducherry), Uttaranchal (Uttarakhand), Madhya Bharat, NCT of Delhi. The same
applies to older city and district spellings (Bombay, Madras, Calcutta,
Bangalore, Balasore, Allahabad, ...): recognise them, reproduce them exactly as
the source title writes them.

Administrative granularity terms that may appear in titles: State, Union
Territory, Division, District, Sub-district, Tehsil, Taluk, Taluka, Block,
Mandal, Circle, Range, Zone, Ward, Village, Gram Panchayat, Municipality,
Municipal Corporation, Census Town, Urban Agglomeration, Rural, Urban, Combined.

'''


# ### confidence_score (0.0|1.0)
# Base at 0.85. Deduct 0.1 if note is null. Deduct 0.15 if sector_resource is null. Set 0.3 if title+sector both missing/malformed.

# ### metadata_gaps
# Comma-separated list of null/missing input fields that affected quality.

# ### justification
# One short sentence on key assumptions or ambiguities. Only include if confidence_score < 0.7.



KEYWORD_SYSTEM_PROMPT = """
# System Prompt: Metadata Keyword Generation for Open Government Data

## Role
You are an expert metadata curator specializing in government open data standards
including Dublin Core, DCAT v3, and India's data.gov.in specifications. Your task
is to generate high-quality keywords and metadata classifications from dataset
resource metadata.

## Input Format
You will receive metadata fields for a single dataset resource.

## Task Requirements

### 1. Enhanced Layman Keywords (`enhanced_keywords`)
Produce 6–10 layman-friendly keywords:
- Simple, everyday language — avoid jargon where possible, but retain well-known medical terms (e.g., "tuberculosis", "AIDS", "coinfection") since these are meaningful to the target audience
- 1–2 words each, lowercase, singular form, no punctuation
- If the title is not that informative, you can also use the note and description fields to identify keywords. For example, if the title is "Monthly IUD Distribution Report" but the note mentions that the dataset contains data on "IUD distribution, broken down by state and district", you could extract keywords like "iud", "contraceptive", "family planning", etc. The note and description fields often contain useful context that can help you generate better keywords, especially when the title is vague.
- Avoid overly generic terms that add no search value — do NOT include words like "health", "data", "india", "report", "dataset", or "information"
- Avoid ministry/department names or any district name. 
- Prefer specific over broad: "coinfection" over "disease", "tuberculosis" over "illness", "patient" over "person"
- Include relevant disease names, conditions, affected populations, and medical concepts directly present in or strongly implied by the title and description

### 2. Sponsored Keywords (`generated_sponsored_keywords`)
Produce 3–5 domain-specific / policy-aligned keywords (may be multi-word phrases):
- Use official programme names, policy frameworks, or institutional terms (e.g., "AIDS control programme", "national tuberculosis elimination programme")
- May include relevant acronyms where they are standard in the policy/health domain (e.g., "NACP", "RNTCP")
- Avoid generic phrases like "government data" or "public health policy"

### 3. Theme Classification (`generated_theme`)
Pick 1–3 themes from: Agriculture, Education, Finance, Health, Transport,
Environment, Energy, Governance, Industry, Science & Technology, Social Welfare,
Urban Development, Water Resources, Labour & Employment, Other.

### 4. Subject Classification (`generated_subject`)
One short subject phrase summarising the dataset's primary domain.

### 5. HVD Category (`hvd_category`)
If the dataset qualifies as High Value Dataset assign a category:
Geospatial | Earth Observation & Environment | Meteorological | Statistics |
Companies & Company Ownership | Mobility | None.

## Output Format
Return ONLY valid JSON — no prose, no markdown fences:
{
  "enhanced_keywords": ["kw1", "kw2", ...],
  "generated_sponsored_keywords": ["kw1", ...],
  "generated_theme": ["Theme1", ...],
  "hvd_category": "None | <category>",
  "enhanced_title: "None | "title",


}
""".strip()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value) -> str:
    if pd.isna(value) or str(value).strip() in ("nan", ""):
        return ""
    return str(value).strip()


def build_user_content(row: dict) -> str:
    return (
        f"Title: {_clean(row.get('Title', ''))}\n"
        f"Catalog Title: {_clean(row.get('Relation[Catalog Title]', ''))}\n"
        f"Ministry_Department: {_clean(row.get('Publisher[ministry_department]', ''))}\n"
        f"Sector_Resource: {_clean(row.get('Subject[sector_resource]', ''))}\n"
        f"Note: {_clean(row.get('Note', ''))}\n"
        f"Frequency: {_clean(row.get('Accrual Periodicity', ''))}\n"
        f"Govt Type: {_clean(row.get('Jurisdiction', ''))}\n"
        f"Granularity: {_clean(row.get('Coverage', ''))}"
    )


def build_request_line(row: dict) -> dict:
    """Return one JSONL request object. custom_id = nid (string)."""
    return {
        "custom_id": str(int(row["nid"])),
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": MODEL,
            "response_format": {"type": "json_object"},
            "prompt_cache_retention": "24h",
            "prompt_cache_key": PROMPT_CACHE_KEY,
            # Default temperature (1.0) made this job disagree with itself: two
            # identical runs over the same 300 rows matched on only 68% of
            # generated_theme. At 0 that rises to 88%, and invalid-sector rows
            # fall from 2.3% to ~0. Not fully deterministic — ~12% of themes
            # still vary between runs.
            "temperature": 0,
            "seed": 42,
            "messages": [
                {"role": "system", "content": categorize_system_prompt},
                {"role": "user", "content": build_user_content(row)},
            ],
        },
    }


def _select_clause(con, source: str) -> tuple[str, str]:
    """Return (select_list, quoted_table) for `source`, skipping absent columns.

    Column names are matched case-insensitively against the live schema and
    aliased back to their SOURCE_FIELDS name, so `row.get('Title')` works no
    matter which table the row came from.
    """
    spec = SOURCES[source]
    table = spec["table"]
    available = [
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
    ]
    available_lower = {c.lower(): c for c in available}

    cols = [
        f'"{available_lower[actual.lower()]}" AS "{field}"'
        for field, actual in spec["columns"].items()
        if actual.lower() in available_lower
    ]
    if not cols:
        raise ValueError(f"No usable columns found on table {table!r} for source {source!r}")

    missing = [f for f, a in spec["columns"].items() if a.lower() not in available_lower]
    if missing:
        logging.warning(f"{table}: missing column(s) for {missing} — sent empty")

    return ", ".join(cols), f'"{table}"'


def _ministry_column(con, source: str) -> str:
    """Quoted actual name of the ministry column on `source`'s table.

    The column is named differently per source (`Publisher[ministry_department]`
    on dublin, `ministry_department` on remaining), so the WHERE clause has to
    go through the SOURCES mapping the same way the SELECT list does. The
    brackets in the Dublin name make quoting mandatory.
    """
    spec = SOURCES[source]
    actual = spec["columns"]["Publisher[ministry_department]"]
    available = {
        r[0].lower(): r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [spec["table"]],
        ).fetchall()
    }
    if actual.lower() not in available:
        raise ValueError(
            f"--ministry needs column {actual!r} on table {spec['table']!r}, which has none"
        )
    return f'"{available[actual.lower()]}"'


def load_rows(
    batch_number: int | None,
    limit: int | None,
    source: str = "dublin",
    offset: int = 0,
    ministry: str | None = None,
) -> pd.DataFrame:
    con = duckdb.connect(DB_PATH)
    select, table = _select_clause(con, source)

    query = f"SELECT {select} FROM {table} WHERE nid IS NOT NULL"
    if batch_number is not None:
        query += f" AND batch = {batch_number}"
    if ministry:
        # Substring match, not equality: a ministry also appears inside joint
        # attributions ("NITI Aayog, Unique Identification Authority of India
        # (UIDAI)"), and those rows belong to the ministry's run too.
        col = _ministry_column(con, source)
        pattern = ministry.replace("'", "''")
        query += f" AND {col} ILIKE '%{pattern}%'"
        matched = con.execute(
            f"SELECT {col}, count(*) FROM {table} WHERE nid IS NOT NULL "
            f"AND {col} ILIKE '%{pattern}%' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        if not matched:
            logging.warning(f"--ministry {ministry!r} matched no rows in {table}")
        for value, count in matched:
            logging.info(f"  ministry match: {value!r} -> {count} row(s)")
    # ORDER BY nid keeps the window stable across runs, so --offset resumes
    # where the previous run stopped instead of re-sending arbitrary rows.
    query += " ORDER BY nid"
    if limit is not None:
        query += f" LIMIT {limit}"
    if offset:
        query += f" OFFSET {offset}"

    df = con.execute(query).fetchdf()
    con.close()

    # A duplicate nid becomes a duplicate custom_id in the batch request,
    # which OpenAI rejects for the whole batch (not just the dupe row) —
    # seen on dublin_core_lot3 (nid 88731), silently dropping 347 rows.
    dupe_mask = df["nid"].duplicated(keep="first")
    if dupe_mask.any():
        dupe_nids = df.loc[dupe_mask, "nid"].tolist()
        logging.warning(f"{table}: dropping {dupe_mask.sum()} duplicate-nid row(s): {dupe_nids}")
        df = df[~dupe_mask]

    logging.info(f"Loaded {len(df)} rows from {table} (source={source}, offset={offset})")
    return df



def upload_requests(df: pd.DataFrame, suffix: str = "") -> str:
    """Write JSONL to a timestamped file, upload to OpenAI, return file_id."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"batch_requests_{ts}{suffix}.jsonl"
    jsonl_path = os.path.join(OUTPUT_DIR, filename)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            f.write(json.dumps(build_request_line(row.to_dict())) + "\n")

    logging.info(f"Wrote {len(df)} requests to {jsonl_path}")

    with open(jsonl_path, "rb") as f:
        # Pass filename explicitly so OpenAI recognises the .jsonl format
        uploaded = client.files.create(file=(filename, f, "application/jsonl"), purpose="batch")

    logging.info(f"Uploaded {filename} → file_id={uploaded.id}")
    return uploaded.id


def submit_batch(file_id: str) -> str:

    batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"project": "nic-metadata-cleaning", "model": MODEL},
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
        # if batch.status = "failed":
        # logging.info(
        #     f"total={counts.total}  completed={counts.completed}  failed={counts.failed}"

        if batch.status in terminal:
            return batch
        time.sleep(POLL_INTERVAL)


def poll_all_batches(batch_ids: list[str]) -> list[object]:
    """
    Poll all batch_ids concurrently. Returns list of completed batch objects
    in the same order as batch_ids.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=len(batch_ids)) as executor:
        future_to_id = {executor.submit(poll_batch, bid): bid for bid in batch_ids}
        for future in as_completed(future_to_id):
            bid = future_to_id[future]
            results[bid] = future.result()

    return [results[bid] for bid in batch_ids]


def download_results(batch) -> dict[str, dict]:
    """
    Download output JSONL, parse each line.
    Returns {nid_str: parsed_result_dict}.
    Errors are logged but not raised.
    """
    if batch.status != "completed":
        logging.error(f"Batch {batch.id} ended with status={batch.status}. No results to parse.")
        if batch.error_file_id:
            errors = client.files.content(batch.error_file_id).text
            logging.error(f"Error file contents:\n{errors}")
        return {}

    if not batch.output_file_id:
        logging.error(f"Batch {batch.id} completed but output_file_id is None — all requests likely failed.")
        if batch.error_file_id:
            errors = client.files.content(batch.error_file_id).text
            logging.error(f"Error file contents:\n{errors}")
        return {}

    raw = client.files.content(batch.output_file_id).text
    results: dict[str, dict] = {}

    for line in raw.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        nid = obj["custom_id"]
        try:
            content = obj["response"]["body"]["choices"][0]["message"]["content"]
            results[nid] = json.loads(content)
        except Exception as e:
            logging.warning(f"nid={nid}: failed to parse response — {e}")
            results[nid] = {}

    logging.info(f"Parsed {len(results)} result(s) from output file")

    # Save raw output for reference
    raw_path = os.path.join(OUTPUT_DIR, f"batch_output_{batch.id}.jsonl")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw)
    logging.info(f"Raw output saved to {raw_path}")

    return results


def merge_and_save(df: pd.DataFrame, results: dict[str, dict]) -> pd.DataFrame:
    """
    Join LLM results back to source rows by nid, write CSV + DuckDB table.
    Only rows with an actual LLM result are written — skips unprocessed rows.
    """
    records = []
    for _, row in df.iterrows():
        nid = str(int(row["nid"]))
        if nid not in results:
            continue
        r = results[nid]
        records.append({
            "nid": nid,
            "title": _clean(row.get("Title", "")),
            "llm_response": json.dumps(r, ensure_ascii=False),
            "generated_title": r.get("generated_title", ""),
            "generated_description": r.get("generated_description", ""),
            "generated_note": r.get("generated_note", ""),
            "generated_alt_title": r.get("generated_alt_title", ""),
            "generated_short_description": r.get("generated_short_description", ""),
            "generated_theme": r.get("generated_theme", ""),
        })

    if not records:
        logging.warning("merge_and_save: no matching results found — nothing written.")
        return pd.DataFrame()

    results_df = pd.DataFrame(records)

    # CSV
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    write_header = not os.path.exists(OUTPUT_CSV)
    results_df.to_csv(OUTPUT_CSV, mode="a", header=write_header, index=False, encoding="utf-8")
    logging.info(f"Appended {len(results_df)} rows to {OUTPUT_CSV}")

    # DuckDB
    con = duckdb.connect(DB_PATH)
    table_exists = con.execute(
        f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{RESULTS_TABLE}'"
    ).fetchone()[0]
    if table_exists:
        con.execute(f"INSERT INTO {RESULTS_TABLE} SELECT * FROM results_df" )
    else:
        con.execute(f"CREATE TABLE {RESULTS_TABLE} AS SELECT * FROM results_df")
    count = con.execute(f"SELECT COUNT(*) FROM {RESULTS_TABLE}").fetchone()[0]
    con.close()
    logging.info(f"Appended {len(results_df)} rows to {DB_PATH}::{RESULTS_TABLE} (total: {count})")

    return results_df


def _submit_with_autosplit(df: pd.DataFrame, suffix: str = "") -> list[str]:
    """
    Upload df as a batch. If OpenAI rejects it for exceeding limits,
    split in half and retry each half recursively.
    Returns list of batch_ids submitted.
    """
    from openai import BadRequestError

    if len(df) == 0:
        logging.warning("_submit_with_autosplit: empty chunk, skipping.")
        return []

    try:
        file_id = upload_requests(df, suffix=suffix)
        batch_id = submit_batch(file_id)
        return [batch_id]
    except BadRequestError as e:
        err = str(e).lower()
        if len(df) > 1 and ("maximum" in err or "limit" in err or "exceed" in err or "too large" in err or "too many" in err):
            mid = len(df) // 2
            logging.warning(
                f"Batch limit exceeded ({len(df)} rows) — splitting into two halves of {mid} and {len(df) - mid}."
            )
            left  = _submit_with_autosplit(df.iloc[:mid],  suffix=f"{suffix}_a")
            right = _submit_with_autosplit(df.iloc[mid:], suffix=f"{suffix}_b")
            return left + right
        logging.error(f"Batch submission failed ({len(df)} rows): {e}")
        raise


def _retry_failed_batches(batches: list) -> list:
    """Resubmit any batch that ended non-completed, one at a time.

    The enqueued-token cap (2M/org) is reported *after* creation succeeds — the
    batch simply ends up status=failed with a token_limit_exceeded error, which
    `_submit_with_autosplit` cannot see. Without this, those rows are dropped
    silently. Retrying sequentially also guarantees the cap has cleared.
    """
    out = []
    for batch in batches:
        if batch.status == "completed":
            out.append(batch)
            continue
        reason = ""
        if getattr(batch, "errors", None) and getattr(batch.errors, "data", None):
            reason = "; ".join(e.code or "" for e in batch.errors.data)
        logging.warning(
            f"Batch {batch.id} ended status={batch.status} ({reason or 'no error detail'}) "
            f"— resubmitting its input file once, sequentially."
        )
        try:
            retried = client.batches.create(
                input_file_id=batch.input_file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"project": "nic-metadata-cleaning", "model": MODEL, "retry_of": batch.id},
            )
            out.append(poll_batch(retried.id))
        except Exception as e:
            logging.error(f"Retry of {batch.id} could not be submitted: {e}")
            out.append(batch)
    return out


def run_batch_job(
    batch_number: int | None = None,
    limit: int | None = None,
    chunk_size: int = 390,
    source: str = "dublin",
    offset: int = 0,
    ministry: str | None = None,
) -> list[str]:
    """
    Full pipeline:
      1. Load rows from DB
      2. Split into chunks; submit up to MAX_CONCURRENT_BATCHES (2) at a time
      3. Poll that window concurrently; wait for all to finish before the next window
      4. Download results and merge into CSV + DuckDB
    """
    df = load_rows(batch_number, limit, source=source, offset=offset, ministry=ministry)
    if df.empty:
        logging.warning("Nothing to process.")
        return []

    chunks = [df.iloc[i:i + chunk_size] for i in range(0, len(df), chunk_size)]
    logging.info(f"Split {len(df)} rows into {len(chunks)} chunk(s) of up to {chunk_size}")

    all_batch_ids: list[str] = []
    all_results:   dict[str, dict] = {}

    # Process chunks in windows of MAX_CONCURRENT_BATCHES (2).
    # Submit the window, wait for all to finish, then move on.
    for window_start in range(0, len(chunks), MAX_CONCURRENT_BATCHES):
        window = chunks[window_start : window_start + MAX_CONCURRENT_BATCHES]
        window_ids: list[str] = []

        for idx, chunk in enumerate(window):
            global_idx = window_start + idx + 1
            logging.info(
                f"Submitting chunk {global_idx}/{len(chunks)} "
                f"({len(chunk)} rows) — "
                f"window {window_start // MAX_CONCURRENT_BATCHES + 1} ..."
            )
            batch_ids = _submit_with_autosplit(chunk, suffix=f"_chunk{global_idx}")
            window_ids.extend(batch_ids)

        logging.info(
            f"Window {window_start // MAX_CONCURRENT_BATCHES + 1}: "
            f"{len(window_ids)} batch(es) in flight — polling until complete: {window_ids}"
        )
        completed = _retry_failed_batches(poll_all_batches(window_ids))

        window_results: dict[str, dict] = {}
        for batch in completed:
            window_results.update(download_results(batch))
        all_results.update(window_results)

        # Persist per window, not at the very end: a full run is ~150 windows
        # over many hours, and an end-only write loses everything on a crash.
        if window_results:
            merge_and_save(pd.concat(window), window_results)

        all_batch_ids.extend(window_ids)
        logging.info(
            f"Window {window_start // MAX_CONCURRENT_BATCHES + 1}"
            f"/{(len(chunks) + MAX_CONCURRENT_BATCHES - 1) // MAX_CONCURRENT_BATCHES} done. "
            f"{len(all_results)}/{len(df)} rows saved so far."
        )

    logging.info(f"All done. {len(all_results)} rows over {len(all_batch_ids)} batch job(s).")
    return all_batch_ids


def resume_poll(batch_id: str, source: str = "dublin") -> None:
    """
    Resume polling an already-submitted batch by its ID.
    Fetches the nids directly from the batch's input file on OpenAI
    so it works regardless of local JSONL filenames.
    """
    batch = poll_batch(batch_id)

    # Fetch nids from the original input file stored on OpenAI
    logging.info(f"Fetching input file {batch.input_file_id} to reconstruct nids...")
    input_text = client.files.content(batch.input_file_id).text
    nids = [
        int(json.loads(line)["custom_id"])
        for line in input_text.splitlines()
        if line.strip()
    ]
    logging.info(f"Reconstructed {len(nids)} nids from input file")

    con = duckdb.connect(DB_PATH)
    select, table = _select_clause(con, source)
    placeholder = ", ".join(str(n) for n in nids)
    df = con.execute(
        f"SELECT {select} FROM {table} WHERE CAST(nid AS BIGINT) IN ({placeholder})"
    ).fetchdf()
    con.close()

    results = download_results(batch)
    merge_and_save(df, results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Batch Classifier — gpt-5-nano via OpenAI Batch API")
    parser.add_argument("--batch", type=int, default=None, help="Process rows from a specific batch partition")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of rows (for testing)")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N rows (nid order) before selecting")
    parser.add_argument("--source", choices=sorted(SOURCES), default="dublin",
                        help="Source table: 'dublin' (dublin_core_metadata) or "
                             "'remaining' (remaining-raw-datasets). Default: dublin")
    parser.add_argument("--chunk-size", type=int, default=390,
                        help="Rows per OpenAI batch. MAX_CONCURRENT_BATCHES x chunk-size x ~2540 "
                             "(p99 prompt tokens) must stay under the 2M enqueued-token cap (default: 390)")
    parser.add_argument("--ministry", type=str, default=None,
                        help="Only process rows whose ministry_department contains this text "
                             "(case-insensitive substring, e.g. 'NITI Aayog')")
    parser.add_argument("--poll", type=str, default=None, metavar="BATCH_ID",
                        help="Resume polling an existing batch job by its ID")
    args = parser.parse_args()

    if args.poll:
        resume_poll(args.poll, source=args.source)
    else:
        batch_ids = run_batch_job(batch_number=args.batch, limit=args.limit,
                                  chunk_size=args.chunk_size, source=args.source,
                                  offset=args.offset, ministry=args.ministry)
        if batch_ids:
            print(f"\nDone. batch_ids={batch_ids}")
            print(f"CSV → {OUTPUT_CSV}")
            print(f"DB  → {DB_PATH}::{RESULTS_TABLE}")

