import argparse
import json
import logging
import os
import time
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
RESULTS_TABLE = "llm_collection_results"

MODEL = "gpt-5.4-nano"
POLL_INTERVAL = 60          # seconds between status checks
MAX_CONCURRENT_BATCHES = 1  # OpenAI concurrent batch limit
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "text_generation")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "llm_collection_results.csv")

# Fields pulled from dublin_core_metadata for each request.
# We classify per *collection* (the merged dataset name), so Collection is the
# primary input. The remaining fields are light context for an accurate
# description / theme — they come from one representative member row.
SOURCE_FIELDS = [
    "nid", "Collection",
    "Note", "Accrual Periodicity", "Jurisdiction", "Coverage",
    "Publisher[ministry_department]", "Subject[sector_resource]",
]



client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



categorize_system_prompt='''
# System Prompt: OGD Collection Metadata Enrichment

## Role
You are an expert metadata curator for Indian government open data. Many small
datasets are being merged into a single dataset; the name of the merged dataset
is the COLLECTION provided below. Your job is to turn that collection name into a
clean, publication-quality title for the merged dataset, plus supporting
metadata, following Dublin Core and DCAT v3 standards.

## Input Fields
collection, ministry_department, sector_resource, note, frequency, govt_type, granularity.
The `collection` is the working name of the merged dataset and is your PRIMARY input — the title you generate is the title of this whole merged collection. The title MUST be derived from the `collection` string ALONE; the other fields are context for the description/theme only.
Semicolon-separated values in any field should be parsed individually. Treat the other fields as context only; do not let them leak verbatim into the title.

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

## Output Wording Rule (applies to ALL generated text fields)
In the generated prose (description, note, short_description), refer to the merged
dataset as a "dataset" — NEVER as a "collection" or "compilation". Do not write
"this merged collection", "this compilation", "a State/UT-wise compilation of ...",
etc. Say "this dataset", "this merged dataset", or "a State/UT-wise dataset of ...".
Verb forms like "compiled from" / "compiles" are fine; only the NOUNS "collection"
and "compilation" are banned from the output. (The `collection` INPUT field name is
unaffected — this rule governs only what you write in the output fields.)

## Field Specifications
### generated_title (10–20 words, Title Case)
This is the title for the MERGED dataset (the collection). Improve the collection
name into a clean, human-readable title — do not start from scratch.
- Treat the `collection` string as the draft title. Change it ONLY when it improves clarity. If the collection name is already a clean, descriptive title, return it essentially unchanged (compare your draft to the collection string: if you altered fewer than 2 substantive words, ignoring casing, keep the original).
- LEAD WITH THE SUBJECT, NOT THE BREAKDOWN DIMENSION. When the collection name BEGINS with a grouping/breakdown dimension written as "<Dimension>-wise" or "<Dimension> Wise" (e.g. "State/UT-wise", "State/UT Wise", "District-wise", "Range-wise"), move that dimension to the END as a "by <Dimension>" suffix so the dataset's real subject comes first. This reordering IS encouraged even though it barely changes the words — it overrides the "keep it unchanged" rule above. Normalise the suffix spelling to "by State/UT", "by District", "by Range", etc. Examples:
    - "State/UT wise Infant Mortality Rates" → "Infant Mortality Rates by State/UT"
    - "District-wise Availability of Health Centres" → "Availability of Health Centres by District"
    - "State/UT Wise Building Position for Community Health Centres" → "Building Position for Community Health Centres by State/UT"
- BUT do NOT relocate "-wise" when it is part of an established term for the report/data TYPE rather than a geographic/administrative breakdown — e.g. "Item-wise" and "Indicator Wise" describe the report type and MUST stay in place ("HMIS Item-wise Monthly Report for Sub-districts of Udupi, Karnataka (FY 2010-11 to 2016-17)" stays as-is). Only relocate leading geographic/administrative dimensions: State, State/UT, District, Block, Range, Zone, Division.
- NEVER inject the sector_resource or ministry name into the title. Those fields exist separately — the title must not duplicate them. In particular, NEVER replace or append a state/UT/district name in the title from the context fields; only use geographic names that already appear in the `collection` string itself.
- These are titles for health and medical datasets published on India's Open Government Data (OGD) platform. Apply domain awareness when interpreting abbreviations and terminology.
- Well-known medical and public health acronyms (TB, HIV, AIDS, NCD, ASHA, ANM, OPD, IPD, MCH, ANC, etc.) must remain fully uppercase — never apply Title Case to individual letters within an acronym.
- Expand non-obvious abbreviations (KCC → Kisan Call Centre, RoC → Registrars of Companies), but do NOT expand standard medical acronyms — leave TB as TB, HIV as HIV, etc.
- Preserve punctuation from the collection name (commas, hyphens, colons, parenthetical FY/state spans like "(FY 2011-12 to 2016-17)") unless it is clearly erroneous. Do not rephrase temporal markers unnecessarily (keep "upto March 2015-16" as-is — do not change it to "as on"/"as of"/brackets).
- Add geographic or temporal scope ONLY if genuinely unclear from the collection name; most collection names already carry state / district / FY scope, so usually leave it.
- Strip mechanical merge artefacts from the collection name where present (e.g. trailing column-count tags like "[11 cols]", "#5") — these are housekeeping markers, not part of the published title.
- Do not hallucinate content not present in or clearly implied by the inputs.
- Rewrite more substantially only if the collection name is fewer than 3–4 words or too vague to stand alone as a title.
- Do not add "in India" or "Number of" when already implied by context and they add no specificity.

### generated_description (40–60 words)
- 2–3 sentences describing the MERGED dataset: what it contains, its purpose/use cases, source ministry, geographic & temporal scope, granularity, and update frequency.
- Refer to it as a "dataset", never a "collection" or "compilation" (see Output Wording Rule).
- Avoid starting with "This dataset contains...".

### generated_note (20–75 words, or "" if not needed)
- Only generate when there is useful operational/technical context (methodology, source portal, data-quality notes, related datasets, what the merge combines). Empty string if not relevant — most collections will not need one.

### generated_alt_title (8–15 words, Title Case)
- A different perspective on the title. Simpler language, hieracical order for the title, SEO-friendly.

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

'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value) -> str:
    if pd.isna(value) or str(value).strip() in ("nan", ""):
        return ""
    return str(value).strip()


def build_user_content(row: dict) -> str:
    # Collection is the primary input (the merged dataset name); the rest is
    # light context drawn from one representative member row.
    return (
        f"Collection: {_clean(row.get('Collection', ''))}\n"
        f"Ministry_Department: {_clean(row.get('Publisher[ministry_department]', ''))}\n"
        f"Sector_Resource: {_clean(row.get('Subject[sector_resource]', ''))}\n"
        f"Note: {_clean(row.get('Note', ''))}\n"
        f"Frequency: {_clean(row.get('Accrual Periodicity', ''))}\n"
        f"Govt Type: {_clean(row.get('Jurisdiction', ''))}\n"
        f"Granularity: {_clean(row.get('Coverage', ''))}"
    )


def build_request_line(coll_id: str, row: dict) -> dict:
    """Return one JSONL request object. custom_id = collection id (string).

    Collection names are too long to use directly as a custom_id (OpenAI caps it
    at 64 chars), so we key requests by a per-run integer id. The collection
    string itself is recoverable from the user content's `Collection:` line,
    which keeps resume_poll self-contained.
    """
    return {
        "custom_id": str(coll_id),
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


def load_rows() -> pd.DataFrame:
    """Load all member rows (one per nid) carrying Collection + context fields."""
    con = duckdb.connect(DB_PATH)
    available = [
        r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{SOURCE_TABLE}'"
        ).fetchall()
    ]
    # Case-insensitive match: use the actual stored column name for the SELECT,
    # but alias it to the SOURCE_FIELDS name so row.get('Collection') works.
    available_lower = {c.lower(): c for c in available}
    cols = [
        f'"{available_lower[c.lower()]}" AS "{c}"'
        for c in SOURCE_FIELDS
        if c.lower() in available_lower
    ]
    select = ", ".join(cols)

    query = (
        f"SELECT {select} FROM {SOURCE_TABLE} "
        f"WHERE nid IS NOT NULL AND Collection IS NOT NULL AND TRIM(Collection) <> ''"
    )
    df = con.execute(query).fetchdf()
    con.close()
    logging.info(f"Loaded {len(df)} member rows from {SOURCE_TABLE}")
    return df


def load_processed_collections() -> set[str]:
    """Return the set of collection strings already present in RESULTS_TABLE.

    Used by --remaining to skip collections that have already been classified.
    Values are compared against _clean(Collection) since that is what
    merge_and_save() stores.
    """
    con = duckdb.connect(DB_PATH)
    table_exists = con.execute(
        f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{RESULTS_TABLE}'"
    ).fetchone()[0]
    if not table_exists:
        con.close()
        logging.info(f"{RESULTS_TABLE} does not exist yet — no collections processed.")
        return set()
    rows = con.execute(
        f"SELECT DISTINCT collection FROM {RESULTS_TABLE} WHERE collection IS NOT NULL"
    ).fetchall()
    con.close()
    processed = {_clean(r[0]) for r in rows}
    logging.info(f"Found {len(processed)} collection(s) already in {RESULTS_TABLE}")
    return processed


def build_collections(
    df: pd.DataFrame, n_collections: int | None = None, offset: int = 0
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Dedupe to one representative row per unique Collection.

    Selects a window of collections: skip `offset`, then keep `n_collections`
    (None = all remaining). E.g. offset=0, n=1000 → the first 1000 collections.

    Returns the representative frame (with a `coll_id` column) and the
    {coll_id: collection_string} mapping used to fan results back out.
    """
    reps = df.drop_duplicates(subset="Collection").reset_index(drop=True)
    total = len(reps)
    if offset:
        reps = reps.iloc[offset:]
    if n_collections is not None:
        reps = reps.head(n_collections)
    reps = reps.reset_index(drop=True)
    reps["coll_id"] = reps.index.astype(str)
    id_to_coll = dict(zip(reps["coll_id"], reps["Collection"]))
    logging.info(
        f"Selected {len(reps)} collection(s) "
        f"(offset={offset}, n={n_collections}) of {total} total "
        f"from {len(df)} member rows"
    )
    return reps, id_to_coll


def upload_requests(reps: pd.DataFrame, suffix: str = "") -> str:
    """Write JSONL (one line per collection) to file, upload, return file_id."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"collection_requests_{ts}{suffix}.jsonl"
    jsonl_path = os.path.join(OUTPUT_DIR, filename)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for _, row in reps.iterrows():
            d = row.to_dict()
            f.write(json.dumps(build_request_line(d["coll_id"], d)) + "\n")

    logging.info(f"Wrote {len(reps)} requests to {jsonl_path}")

    with open(jsonl_path, "rb") as f:
        uploaded = client.files.create(file=(filename, f, "application/jsonl"), purpose="batch")

    logging.info(f"Uploaded {filename} → file_id={uploaded.id}")
    return uploaded.id


def submit_batch(file_id: str) -> str:
    batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"project": "nic-metadata-cleaning", "model": MODEL, "mode": "collection"},
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
    """Poll all batch_ids concurrently, return completed batches in input order."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=len(batch_ids)) as executor:
        future_to_id = {executor.submit(poll_batch, bid): bid for bid in batch_ids}
        for future in as_completed(future_to_id):
            bid = future_to_id[future]
            results[bid] = future.result()

    return [results[bid] for bid in batch_ids]


def download_results(batch) -> dict[str, dict]:
    """Download output JSONL, parse each line. Returns {coll_id: result_dict}."""
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
        coll_id = obj["custom_id"]
        try:
            content = obj["response"]["body"]["choices"][0]["message"]["content"]
            results[coll_id] = json.loads(content)
        except Exception as e:
            logging.warning(f"coll_id={coll_id}: failed to parse response — {e}")
            results[coll_id] = {}

    logging.info(f"Parsed {len(results)} result(s) from output file")

    raw_path = os.path.join(OUTPUT_DIR, f"collection_output_{batch.id}.jsonl")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw)
    logging.info(f"Raw output saved to {raw_path}")

    return results


def merge_and_save(df: pd.DataFrame, results_by_collection: dict[str, dict]) -> pd.DataFrame:
    """Fan each collection's result out to every member nid, write CSV + DuckDB.

    Output stays keyed per-nid so the downstream join in
    utils/update_dublin_metadata.py (CAST(nid AS VARCHAR)) works unchanged.
    Only rows whose collection has a result are written.
    """
    records = []
    for _, row in df.iterrows():
        collection = _clean(row.get("Collection", ""))
        r = results_by_collection.get(collection)
        if not r:
            continue
        records.append({
            "nid": str(int(row["nid"])),
            "collection": collection,
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
        con.execute(f"INSERT INTO {RESULTS_TABLE} SELECT * FROM results_df")
    else:
        con.execute(f"CREATE TABLE {RESULTS_TABLE} AS SELECT * FROM results_df")
    count = con.execute(f"SELECT COUNT(*) FROM {RESULTS_TABLE}").fetchone()[0]
    con.close()
    logging.info(f"Appended {len(results_df)} rows to {DB_PATH}::{RESULTS_TABLE} (total: {count})")

    return results_df


def _submit_with_autosplit(reps: pd.DataFrame, suffix: str = "") -> list[str]:
    """Upload reps as a batch; on limit errors, split in half and retry."""
    from openai import BadRequestError

    if len(reps) == 0:
        logging.warning("_submit_with_autosplit: empty chunk, skipping.")
        return []

    try:
        file_id = upload_requests(reps, suffix=suffix)
        batch_id = submit_batch(file_id)
        return [batch_id]
    except BadRequestError as e:
        err = str(e).lower()
        if len(reps) > 1 and ("maximum" in err or "limit" in err or "exceed" in err or "too large" in err or "too many" in err):
            mid = len(reps) // 2
            logging.warning(
                f"Batch limit exceeded ({len(reps)} rows) — splitting into halves of {mid} and {len(reps) - mid}."
            )
            left  = _submit_with_autosplit(reps.iloc[:mid],  suffix=f"{suffix}_a")
            right = _submit_with_autosplit(reps.iloc[mid:], suffix=f"{suffix}_b")
            return left + right
        logging.error(f"Batch submission failed ({len(reps)} rows): {e}")
        raise


def run_batch_job(
    n_collections: int | None = None,
    offset: int = 0,
    chunk_size: int = 800,
    remaining_only: bool = False,
) -> list[str]:
    """
    Full pipeline:
      1. Load member rows from DB
      2. (optional) drop collections already present in RESULTS_TABLE
      3. Dedupe to unique collections and select a window (offset + n_collections)
      4. Chunk; submit up to MAX_CONCURRENT_BATCHES at a time and poll each window
      5. Fan results back out to member nids; merge into CSV + DuckDB
    """
    df = load_rows()
    if df.empty:
        logging.warning("Nothing to process.")
        return []

    if remaining_only:
        processed = load_processed_collections()
        if processed:
            before = df["Collection"].map(_clean).nunique()
            df = df[~df["Collection"].map(_clean).isin(processed)].reset_index(drop=True)
            after = df["Collection"].map(_clean).nunique()
            logging.info(
                f"--remaining: {after} unprocessed collection(s) left "
                f"({before - after} already done, {before} total)"
            )
        if df.empty:
            logging.info("--remaining: all collections already processed — nothing to do.")
            return []

    reps, id_to_coll = build_collections(df, n_collections, offset)
    if reps.empty:
        logging.warning("No collections in the selected window — nothing to process.")
        return []

    chunks = [reps.iloc[i:i + chunk_size] for i in range(0, len(reps), chunk_size)]
    logging.info(f"Split {len(reps)} collections into {len(chunks)} chunk(s) of up to {chunk_size}")

    all_batch_ids: list[str] = []
    results_by_id: dict[str, dict] = {}

    for window_start in range(0, len(chunks), MAX_CONCURRENT_BATCHES):
        window = chunks[window_start : window_start + MAX_CONCURRENT_BATCHES]
        window_ids: list[str] = []

        for idx, chunk in enumerate(window):
            global_idx = window_start + idx + 1
            logging.info(
                f"Submitting chunk {global_idx}/{len(chunks)} "
                f"({len(chunk)} collections) — "
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
            results_by_id.update(download_results(batch))

        all_batch_ids.extend(window_ids)
        logging.info(
            f"Window {window_start // MAX_CONCURRENT_BATCHES + 1} done. "
            f"Running total: {len(all_batch_ids)} batch(es) finished."
        )

    # Map coll_id results to collection strings, then fan out to member nids.
    results_by_collection = {
        id_to_coll[cid]: res for cid, res in results_by_id.items() if cid in id_to_coll
    }
    merge_and_save(df, results_by_collection)
    logging.info(f"All done. Total batch jobs: {len(all_batch_ids)}")
    return all_batch_ids


def _parse_collection(user_content: str) -> str:
    """Recover the collection string from a request's user message."""
    for line in user_content.splitlines():
        if line.startswith("Collection: "):
            return line[len("Collection: "):].strip()
    return ""


def resume_poll(batch_id: str) -> None:
    """
    Resume polling an already-submitted batch by its ID.
    Rebuilds the {coll_id: collection} map from the batch's input file on OpenAI
    (the `Collection:` line in each request), so it is self-contained.
    """
    batch = poll_batch(batch_id)

    logging.info(f"Fetching input file {batch.input_file_id} to reconstruct collections...")
    input_text = client.files.content(batch.input_file_id).text
    id_to_coll: dict[str, str] = {}
    for line in input_text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        content = obj["body"]["messages"][-1]["content"]
        id_to_coll[obj["custom_id"]] = _parse_collection(content)
    logging.info(f"Reconstructed {len(id_to_coll)} collection(s) from input file")

    collections = [c for c in id_to_coll.values() if c]
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
    df = con.execute(
        f"SELECT {', '.join(cols)} FROM {SOURCE_TABLE} WHERE Collection IN ?",
        [collections],
    ).fetchdf()
    con.close()

    results_by_id = download_results(batch)
    results_by_collection = {
        id_to_coll[cid]: res for cid, res in results_by_id.items() if cid in id_to_coll
    }
    merge_and_save(df, results_by_collection)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Collection Classifier — gpt-5-nano via OpenAI Batch API")
    parser.add_argument("--collections", type=int, default=None, metavar="N",
                        help="Process the first N unique collections (default: all)")
    parser.add_argument("--offset", type=int, default=0, metavar="N",
                        help="Skip the first N collections before selecting (for processing in windows)")
    parser.add_argument("--chunk-size", type=int, default=700, help="Number of collections per OpenAI batch (default: 1000)")
    parser.add_argument("--poll", type=str, default=None, metavar="BATCH_ID",
                        help="Resume polling an existing batch job by its ID")
    parser.add_argument("--remaining", action="store_true",
                        help="Only process collections not already present in "
                             f"{RESULTS_TABLE} (skips already-classified collections)")
    args = parser.parse_args()

    if args.poll:
        resume_poll(args.poll)
    else:
        batch_ids = run_batch_job(
            n_collections=args.collections,
            offset=args.offset,
            chunk_size=args.chunk_size,
            remaining_only=args.remaining,
        )
        if batch_ids:
            print(f"\nDone. batch_ids={batch_ids}")
            print(f"CSV → {OUTPUT_CSV}")
            print(f"DB  → {DB_PATH}::{RESULTS_TABLE}")
