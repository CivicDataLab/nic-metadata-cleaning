import argparse
import json
import logging
import os
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



DB_PATH = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning/transformation/metadata.db"
SOURCE_TABLE = "dublin_core_metadata"
RESULTS_TABLE = "llm_keyword_results"

MODEL = "gpt-5.4-nano"
POLL_INTERVAL = 60          # seconds between status checks
MAX_CONCURRENT_BATCHES = 1  # OpenAI concurrent batch limit
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "text_generation")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "llm_keyword_results.csv")

# Fields pulled from dublin_core_metadata for each request
SOURCE_FIELDS = [
    "nid", "Title", "Relation[Catalog Title]",
    "Note", "Accrual Periodicity", "Jurisdiction", "Coverage",
    "Publisher[ministry_department]", "Subject[sector_resource]",
    "High Value Dataset Category",
]



client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



categorize_system_prompt='''
# Optimized System Prompt: OGD Metadata Enrichment

## Role
You are an expert metadata curator for Indian government open data. Generate enriched metadata fields from dataset resource metadata following Dublin Core and DCAT v3 standards.

## Input Fields
title, catalog_title, ministry_department, sector_resource, note, frequency, govt_type, granularity, HVD Flag (0|1).
Semicolon-separated values in any field should be parsed individually.

## Output: Strict JSON
{
  "generated_title": "",
  "generated_description": "",
  "generated_note": "",
  "generated_alt_title": "",
  "generated_short_description": "",
  "generated_keywords": "",
  "generated_sponsored_keywords": "",
  "generated_theme": "",
  "hvd_category": "",
}

Return ONLY valid JSON. No markdown fences, no preamble.

## Field Specifications
### generated_title (10–20 words, Title Case)
- Compare your draft to the original: if you changed fewer than 2 substantive words (ignoring casing). 
- NEVER inject the sector_resource, ministry name, or catalog_title context into the title. Those fields exist separately — the title must not duplicate them.
- If multiple datasets share the same title pattern (e.g. monthly reports differing only by month), apply the EXACT same transformation to each — do not vary phrasing, prepositions, or punctuation across the batch.
- These are titles for health and medical datasets published on India's Open Government Data (OGD) Exchange platform. Apply domain awareness when interpreting abbreviations and terminology.
- Well-known medical and public health acronyms (TB, HIV, AIDS, NCD, ASHA, ANM, OPD, IPD, MCH, ANC, etc.) must remain fully uppercase — never apply Title Case to individual letters within an acronym.
- Expand non-obvious abbreviations (KCC → Kisan Call Centre, RoC → Registrars of Companies), but do NOT expand standard medical acronyms — leave TB as TB, HIV as HIV, etc.
- Preserve punctuation from the original title (e.g., commas, hyphens, colons) unless it is clearly erroneous.
- Add geographic scope ("in India" / state name) ONLY if genuinely unclear from context.
- Add temporal range ONLY if absent from the original title.
- Do not rephrase temporal markers unnecessarily (e.g., keep "upto March 2015-16" as "upto March 2015-16" — do not change it to "as on", "as of", or put it in brackets).
- No redundancy with catalog_title.
- Do not hallucinate content not present in or clearly implied by the source metadata.
- Change the title if title is less than 3-4 words or is too vague on its own
- Think Deeply before changing the title, and if you decide to change it make sure it makes sense to other metadata fields and is not just a rephrasing of the original title. The title should be concise and informative, but not necessarily a full sentence. 

### generated_description (40–60 words)
- 2–3 sentences: what the dataset contains, its purpose/use cases, source ministry, geographic & temporal scope, granularity, and update frequency.
- Avoid Starting with "This dataset contains..."
### generated_note (20–75 words, or "" if not needed)
- Dont generate for all dataset only some if there's useful operational/technical context to add (methodology, source portal, data quality notes, related datasets). Empty string if not relevant, only some datasets require note.

### generated_alt_title (8–15 words, Title Case)
- Different perspective from main title. Simpler language, colloquial terms, SEO-friendly.

### generated_short_description (20–40 words)
- 1–2 sentences. What + why. No technical details. For quick previews.

### Enhanced Layman Keywords (`generated_keywords`)
Produce 6–10 layman-friendly keywords:
- Simple, everyday language — avoid jargon where possible, but retain well-known leyman medical terms (e.g., "tuberculosis", "AIDS", "coinfection") since these are meaningful to the target audience
- 1–2 words each, lowercase, singular form, no punctuation
- Avoid overly generic terms that add no search value — do NOT include words very common words like "health", "data", "india", "dataset"
- Avoid ministry/department names
- Prefer specific over broad: "coinfection" over "disease", "tuberculosis" over "illness", "patient" over "person"
- Include relevant disease names, conditions, affected populations, and medical concepts directly present in or strongly implied by the title and description
- Keywords are must

### Sponsored Keywords (`generated_sponsored_keywords`)
Produce 3–5 domain-specific / policy-aligned keywords (may be multi-word phrases):
- Use official programme names, policy frameworks, or institutional terms (e.g., "AIDS control programme", "national tuberculosis elimination programme")
- May include relevant acronyms where they are standard in the policy/health domain (e.g., "NACP", "RNTCP"), avoid making mistakes. 
- Avoid generic phrases like "government data" or "public health policy" and use phrases about the datasets content that the user
- Use the title and catalog_title fields to identify relevant programmes, policies, and institutional terms to include as sponsored keywords. These are often explicitly mentioned in the title/catalog_title of datasets, especially for health datasets.

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

### hvd_category
If HVD Flag=0: "". If HVD Flag=1: classify into exactly one of: geospatial | earth observation and environment | meteorological | statistics | companies and company ownership | mobility.

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
- Avoid overly generic terms that add no search value — do NOT include words like "health", "data", "india", "report", "dataset", or "information"
- Avoid ministry/department names
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


def _hvd_flag(value) -> int:
    try:
        return int(value) if value == value else 0   # handles NaN
    except (ValueError, TypeError):
        return 0


def build_user_content(row: dict) -> str:
    return (
        f"Title: {_clean(row.get('Title', ''))}\n"
        f"Catalog Title: {_clean(row.get('Relation[Catalog Title]', ''))}\n"
        f"Ministry_Department: {_clean(row.get('Publisher[ministry_department]', ''))}\n"
        f"Sector_Resource: {_clean(row.get('Subject[sector_resource]', ''))}\n"
        f"Note: {_clean(row.get('Note', ''))}\n"
        f"Frequency: {_clean(row.get('Accrual Periodicity', ''))}\n"
        f"Govt Type: {_clean(row.get('Jurisdiction', ''))}\n"
        f"Granularity: {_clean(row.get('Coverage', ''))}\n"
        f"HVD Flag: {_hvd_flag(row.get('High Value Dataset Category', 0))}"
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
            "messages": [
                {"role": "system", "content": categorize_system_prompt},
                {"role": "user", "content": build_user_content(row)},
            ],
        },
    }


def load_rows(batch_number: int | None, limit: int | None) -> pd.DataFrame:
    # Only select columns that exist in the table
    con = duckdb.connect(DB_PATH)
    available = [
        r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{SOURCE_TABLE}'"
        ).fetchall()
    ]
    # Case-insensitive match: use the actual stored column name for the SELECT,
    # but alias it to the SOURCE_FIELDS name so row.get('Title') works downstream.
    available_lower = {c.lower(): c for c in available}

    col = [
        c for c in SOURCE_FIELDS
        if c.lower() in available_lower]
    cols = [
        f'"{available_lower[c.lower()]}" AS "{c}"'
        for c in SOURCE_FIELDS
        if c.lower() in available_lower
    ]
    select = ", ".join(cols)

    query = f"SELECT {select} FROM {SOURCE_TABLE} WHERE dataset_merge = FALSE"
    if batch_number is not None:
        query += f" AND batch = {batch_number}"
        #query += f" OFFSET 10"

    if limit is not None:
        query += f" LIMIT {limit}"

    df = con.execute(query).fetchdf()
    con.close()
    logging.info(f"Loaded {len(df)} rows from {SOURCE_TABLE}")
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


def _list_to_str(value) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value) if value else ""


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
            "generated_keywords": _list_to_str(r.get("generated_keywords", [])),
            "generated_sponsored_keywords": _list_to_str(r.get("generated_sponsored_keywords", [])),
            "generated_theme": r.get("generated_theme", ""),
            "hvd_category": r.get("hvd_category", ""),
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


def run_batch_job(
    batch_number: int | None = None,
    limit: int | None = None,
    chunk_size: int = 500,
) -> list[str]:
    """
    Full pipeline:
      1. Load rows from DB
      2. Split into chunks; submit up to MAX_CONCURRENT_BATCHES (2) at a time
      3. Poll that window concurrently; wait for all to finish before the next window
      4. Download results and merge into CSV + DuckDB
    """
    df = load_rows(batch_number, limit)
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
        completed = poll_all_batches(window_ids)

        for batch in completed:
            all_results.update(download_results(batch))

        all_batch_ids.extend(window_ids)
        logging.info(
            f"Window {window_start // MAX_CONCURRENT_BATCHES + 1} done. "
            f"Running total: {len(all_batch_ids)} batch(es) finished."
        )

    merge_and_save(df, all_results)
    logging.info(f"All done. Total batch jobs: {len(all_batch_ids)}")
    return all_batch_ids


def resume_poll(batch_id: str) -> None:
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
    available = [
        r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{SOURCE_TABLE}'"
        ).fetchall()
    ]
    available_lower = {c.lower(): c for c in available}
    cols = [
        f'"{available_lower[c.lower()]}" AS "{c}"'
        for c in SOURCE_FIELDS
        if c.lower() in available_lower
    ]
    placeholder = ", ".join(str(n) for n in nids)
    df = con.execute(
        f"SELECT {', '.join(cols)} FROM {SOURCE_TABLE} WHERE nid IN ({placeholder})"
    ).fetchdf()
    con.close()

    results = download_results(batch)
    merge_and_save(df, results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Batch Classifier — gpt-5-nano via OpenAI Batch API")
    parser.add_argument("--batch", type=int, default=None, help="Process rows from a specific batch partition")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of rows (for testing)")
    parser.add_argument("--chunk-size", type=int, default=500, help="Number of rows per OpenAI batch (default: 500)")
    parser.add_argument("--poll", type=str, default=None, metavar="BATCH_ID",
                        help="Resume polling an existing batch job by its ID")
    args = parser.parse_args()

    if args.poll:
        resume_poll(args.poll)
    else:
        batch_ids = run_batch_job(batch_number=args.batch, limit=args.limit, chunk_size=args.chunk_size)
        if batch_ids:
            print(f"\nDone. batch_ids={batch_ids}")
            print(f"CSV → {OUTPUT_CSV}")
            print(f"DB  → {DB_PATH}::{RESULTS_TABLE}")

