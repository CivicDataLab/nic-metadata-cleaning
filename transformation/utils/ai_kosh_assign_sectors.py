"""Assign a controlled ``Sector; Sub-sector`` to the AIKosh metadata CSV.

Title-only LLM pass over
``ai-kosh metadata fields added - ai-kosh metadata fields added.csv`` using the
same OpenAI Batch API machinery as ``transformation/llm_batch_classifier.py``,
stripped down to a single output field.

Differences from the classifier it borrows from:
  * the only input sent to the model is the dataset title — no note, ministry,
    frequency or granularity, because this CSV does not carry them;
  * the only output is ``sector``; no titles, descriptions or notes;
  * ``custom_id`` is the CSV row index, not the nid — 7 rows have a blank nid
    and ``str(int(nid))`` would drop them silently. Results join back
    positionally, so every row gets a sector;
  * nothing is written to metadata.db, and the source CSV's ``sector`` column
    (which mixes the AIKosh platform taxonomy with earlier SECTOR_VOCAB work)
    is never overwritten — results land in a new ``generated_sector`` column.

Run:
    python ai_kosh_assign_sectors.py --limit 50    # small trial
    python ai_kosh_assign_sectors.py               # full run (~9.3k rows)
    python ai_kosh_assign_sectors.py --resume      # only rows not yet done
    python ai_kosh_assign_sectors.py --annotate    # write annotated CSV copy
    python ai_kosh_assign_sectors.py --poll BATCH_ID
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = "/home/aakash/NIC/Newfolder/nic-metadata-cleaning"
SOURCE_CSV = os.path.join(
    BASE_DIR, "ai-kosh metadata fields added - ai-kosh metadata fields added.csv"
)
OUTPUT_DIR = os.path.join(BASE_DIR, "transformation", "text_generation")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "ai_kosh_sector_assignments.csv")
ANNOTATED_CSV = os.path.join(
    BASE_DIR, "ai-kosh metadata fields added - with generated sector.csv"
)

TITLE_COL = "Title"
NID_COL = "nid"
RESULT_COL = "generated_sector"

MODEL = "gpt-5.4-nano"
POLL_INTERVAL = 60
# The enqueued-token cap is 2M org-wide and is only reported *after* the batch
# is created (it ends status=failed), so stay well inside it: 1 batch in flight
# x 1000 rows x ~1.5k prompt tokens ~= 1.5M.
MAX_CONCURRENT_BATCHES = 1
DEFAULT_CHUNK_SIZE = 1000

PROMPT_CACHE_KEY = "nic-metadata-aikosh-sector-v1"

_log_file = os.path.join(OUTPUT_DIR, "batch_jobs.log")
os.makedirs(OUTPUT_DIR, exist_ok=True)
logging.basicConfig(
    format="%(asctime)s : %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Verbatim from llm_batch_classifier.categorize_system_prompt so the two passes
# assign from exactly the same controlled vocabulary.
SECTOR_VOCAB = """
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
""".strip()

SECTOR_SYSTEM_PROMPT = f"""
# System Prompt: Sector Classification for Indian Government Open Data

## Role
You are an expert metadata curator for Indian government open data. Given a
dataset title, classify it into the controlled sector vocabulary below.

## Input
A single dataset title. Nothing else is provided — infer the sector from the
title alone, using domain knowledge of Indian government schemes, ministries and
programme acronyms (JJM, PMAY, NHM, RTE, MGNREGA, HMIS, NSS, ...).

## Output: Strict JSON
{{"sector": ""}}

Return ONLY valid JSON. No markdown fences, no preamble.

## sector
- Map to SECTOR_VOCAB only. Format: "Sector; Sub-sector" pairs, comma-separated
  if more than one applies. Example:
  "Agriculture; Agricultural Marketing, Health and Family welfare; Health".
- If no sub-sector fits, use the sector name alone (e.g. "Urban; Development"
  has a sub-sector, but "Economy" may be used bare if neither sub-sector fits).
- Prefer ONE pair. Emit a second only when the title genuinely spans two
  sectors; never more than two.
- NEVER invent a sector or sub-sector outside the vocabulary, and never alter
  its spelling or casing — reproduce the vocabulary entry character for
  character, including its typos.
- Do not classify on the geography, the year, or the reporting frequency in the
  title; classify on the subject matter.
- If the title is too vague to place, choose the closest defensible sector
  rather than returning an empty string.

## Survey instruments — do not invent one
The "Census and Surveys" sub-sectors name SPECIFIC statistical instruments.
Never attribute a dataset to an instrument its title does not name.
- Title names an instrument → use that instrument's sub-sector:
  AHS / Annual Health Survey → "Census and Surveys; Annual Health Survey";
  SRS / Sample Registration System → "Census and Surveys; Sample Registration System";
  CRS / Civil Registration System → "Census and Surveys; Civil Registration System";
  NPR / National Population Register → "Census and Surveys; National Population Register";
  SECC → "Census and Surveys; Socio-economic & Caste Census";
  Census / House listing → "Census and Surveys; Census" or the "Census" sector.
- Title names NFHS, DLHS, NSS or any other survey that is NOT in the
  vocabulary → do NOT reach for a different instrument. Classify on the subject
  matter instead (e.g. NFHS/DLHS maternal, child or immunisation indicators →
  "Health and Family welfare; Family Welfare"; NFHS/DLHS disease or treatment
  indicators → "Health and Family welfare; Health").
- Title names NO instrument at all → classify on the subject matter. The one
  exception is unattributed vital statistics (birth rate, death rate, crude
  death rate, infant mortality rate, total fertility rate, fertility indicators,
  live births by order), which come from the SRS →
  "Census and Surveys; Sample Registration System".

## Consistency across related datasets
These datasets are published in families that differ only by state, district,
year, round or indicator variant. Titles that differ ONLY in those respects MUST
receive the identical sector pair — decide from the shared subject matter, and
do not let a geography or a year pull one member of a family into a different
sector from its siblings.

SECTOR_VOCAB:
{SECTOR_VOCAB}
""".strip()


# ---------------------------------------------------------------------------
# Vocabulary validation
# ---------------------------------------------------------------------------

def parse_vocab() -> dict[str, set[str]]:
    """{sector: {sub-sector, ...}} parsed out of SECTOR_VOCAB."""
    vocab: dict[str, set[str]] = {}
    for line in SECTOR_VOCAB.splitlines():
        if not line.strip():
            continue
        sector, _, subs = line.partition(":")
        vocab.setdefault(sector.strip(), set()).update(
            s.strip() for s in subs.split(",") if s.strip()
        )
    return vocab


# Sector names the model reaches for that are one rename away from the
# vocabulary. Sub-sector misses are NOT aliased — they fall back to the bare
# sector instead, which is always defensible.
SECTOR_ALIASES = {
    "energy": "Power and Energy",
    "power": "Power and Energy",
    "environment": "Environment and Forest",
    "health": "Health and Family welfare",
    "animal husbandry and dairying": "Animal Husbandry",
    "governance": "Governance and Administration",
    "labour": "Labour and Employment",
    "science and technology and research": "Science and Technology",
}


def normalise_sector(value: str, vocab: dict[str, set[str]]) -> tuple[str, list[str]]:
    """Return (canonical value, model pairs that were not vocabulary-clean).

    Recognition is case-insensitive, but every recognised half is rewritten to
    the vocabulary's exact casing — downstream joins against the rest of the
    pipeline are case-sensitive, so "health and family welfare; health" must not
    pass through unchanged just because it validates. A bare sector with no
    sub-sector is valid.

    Three repairs run before a pair is given up on, because the model's misses
    are overwhelmingly near-misses rather than invented sectors:

    1. A bare token that names a valid sub-sector of a sector already seen in
       the same value is attached to it. "Commerce; Export, Import" is one
       sector with two sub-sectors, but the comma-separated pair format splits
       it into "Commerce; Export" and a stray "Import".
    2. A recognised sector with an unrecognised sub-sector falls back to the
       bare sector. Ambient air-quality datasets, for instance, return
       "Environment and Forest; Air Quality" — the vocabulary only has the three
       pollution-source sub-sectors, and none of them fits, so the sector alone
       is the honest answer.
    3. A sector named by a common synonym is mapped through SECTOR_ALIASES.

    Anything still unmatched is passed through untouched and reported, so the
    returned list is the audit trail of what the model got wrong — including the
    pairs that were subsequently repaired.
    """
    if not value:
        return "", []
    canon_sector = {s.lower(): s for s in vocab}
    canon_sub = {s.lower(): {x.lower(): x for x in subs} for s, subs in vocab.items()}

    out, bad, seen_sectors = [], [], []
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            continue
        sector, sep, sub = pair.partition(";")
        sl, sub_l = sector.strip().lower(), sub.strip().lower()

        # (1) bare sub-sector trailing an earlier "Sector; Sub" pair
        if not sep:
            attached = next(
                (s for s in reversed(seen_sectors) if sl in canon_sub[s]), None
            )
            if attached:
                bad.append(pair)
                out.append(f"{canon_sector[attached]}; {canon_sub[attached][sl]}")
                continue

        # (3) sector synonym
        if sl not in canon_sector and sl in SECTOR_ALIASES:
            bad.append(pair)
            sl = SECTOR_ALIASES[sl].lower()

        if sl not in canon_sector:
            bad.append(pair)
            out.append(pair)
            continue

        seen_sectors.append(sl)
        if sub_l and sub_l not in canon_sub[sl]:
            # (2) unknown sub-sector -> keep the sector alone
            bad.append(pair)
            out.append(canon_sector[sl])
            continue

        out.append(
            f"{canon_sector[sl]}; {canon_sub[sl][sub_l]}" if sub_l else canon_sector[sl]
        )

    # Duplicate pairs can appear once a sub-sector is dropped; keep first order.
    deduped = list(dict.fromkeys(out))
    return ", ".join(deduped), bad


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

def _clean(value) -> str:
    if pd.isna(value) or str(value).strip() in ("nan", ""):
        return ""
    return str(value).strip()


def build_request_line(row_index: int, title: str) -> dict:
    """One JSONL request. custom_id is the CSV row index (see module docstring)."""
    return {
        "custom_id": str(row_index),
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": MODEL,
            "response_format": {"type": "json_object"},
            "prompt_cache_retention": "24h",
            "prompt_cache_key": PROMPT_CACHE_KEY,
            # Default temperature made the sibling job disagree with itself on
            # generated_theme across identical runs; 0 + a fixed seed is what
            # keeps sector assignment reproducible.
            "temperature": 0,
            "seed": 42,
            "messages": [
                {"role": "system", "content": SECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Title: {title}"},
            ],
        },
    }


def load_rows(limit: int | None = None, offset: int = 0, resume: bool = False) -> pd.DataFrame:
    """Read the source CSV, keeping the original row index as `row_index`."""
    df = pd.read_csv(SOURCE_CSV)
    df = df.reset_index().rename(columns={"index": "row_index"})
    df = df[["row_index", NID_COL, TITLE_COL]]

    blank = df[TITLE_COL].map(_clean) == ""
    if blank.any():
        logging.warning(f"{blank.sum()} row(s) have no title — skipped")
        df = df[~blank]

    if resume and os.path.exists(OUTPUT_CSV):
        done = set(pd.read_csv(OUTPUT_CSV)["row_index"].tolist())
        before = len(df)
        df = df[~df["row_index"].isin(done)]
        logging.info(f"--resume: {before - len(df)} row(s) already in {OUTPUT_CSV}")

    if offset:
        df = df.iloc[offset:]
    if limit is not None:
        df = df.iloc[:limit]

    logging.info(f"Loaded {len(df)} row(s) from {os.path.basename(SOURCE_CSV)}")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Batch API plumbing
# ---------------------------------------------------------------------------

def upload_requests(df: pd.DataFrame, suffix: str = "") -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"aikosh_sector_requests_{ts}{suffix}.jsonl"
    jsonl_path = os.path.join(OUTPUT_DIR, filename)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            line = build_request_line(int(row["row_index"]), _clean(row[TITLE_COL]))
            f.write(json.dumps(line) + "\n")
    logging.info(f"Wrote {len(df)} requests to {jsonl_path}")

    with open(jsonl_path, "rb") as f:
        uploaded = client.files.create(
            file=(filename, f, "application/jsonl"), purpose="batch"
        )
    logging.info(f"Uploaded {filename} → file_id={uploaded.id}")
    return uploaded.id


def submit_batch(file_id: str) -> str:
    batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"project": "nic-metadata-cleaning", "job": "aikosh-sector", "model": MODEL},
    )
    logging.info(f"Batch submitted - batch_id={batch.id}  status={batch.status}")
    return batch.id


def poll_batch(batch_id: str):
    terminal = {"completed", "failed", "cancelled", "expired"}
    while True:
        batch = client.batches.retrieve(batch_id)
        c = batch.request_counts
        logging.info(
            f"[{batch_id}] status={batch.status} total={c.total} "
            f"completed={c.completed} failed={c.failed}"
        )
        if batch.status in terminal:
            return batch
        time.sleep(POLL_INTERVAL)


def download_results(batch) -> dict[int, str]:
    """{row_index: sector} parsed from the batch output file."""
    if batch.status != "completed" or not batch.output_file_id:
        logging.error(f"Batch {batch.id} status={batch.status} — no results to parse.")
        if batch.error_file_id:
            logging.error(f"Error file:\n{client.files.content(batch.error_file_id).text}")
        return {}

    raw = client.files.content(batch.output_file_id).text
    results: dict[int, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        idx = int(obj["custom_id"])
        try:
            content = obj["response"]["body"]["choices"][0]["message"]["content"]
            results[idx] = str(json.loads(content).get("sector", "")).strip()
        except Exception as e:
            logging.warning(f"row_index={idx}: failed to parse response — {e}")
            results[idx] = ""

    raw_path = os.path.join(OUTPUT_DIR, f"aikosh_sector_output_{batch.id}.jsonl")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw)
    logging.info(f"Parsed {len(results)} result(s); raw output → {raw_path}")
    return results


def _retry_failed_batches(batches: list) -> list:
    """Resubmit any batch that ended non-completed, one at a time.

    The enqueued-token cap is only reported after creation succeeds, so an
    over-cap batch simply ends status=failed. Without this its rows vanish.
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
            f"Batch {batch.id} ended status={batch.status} ({reason or 'no detail'}) "
            f"— resubmitting its input file once."
        )
        try:
            retried = client.batches.create(
                input_file_id=batch.input_file_id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"project": "nic-metadata-cleaning", "job": "aikosh-sector",
                          "model": MODEL, "retry_of": batch.id},
            )
            out.append(poll_batch(retried.id))
        except Exception as e:
            logging.error(f"Retry of {batch.id} could not be submitted: {e}")
            out.append(batch)
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_results(df: pd.DataFrame, results: dict[int, str]) -> pd.DataFrame:
    """Append {row_index, nid, title, generated_sector} to OUTPUT_CSV."""
    vocab = parse_vocab()
    records = []
    for _, row in df.iterrows():
        idx = int(row["row_index"])
        if idx not in results:
            continue
        raw = results[idx]
        sector, repaired = normalise_sector(raw, vocab)
        # Second pass over the repaired value: whatever is still flagged could
        # not be mapped into the vocabulary at all and needs a human.
        _, unmapped = normalise_sector(sector, vocab)
        records.append({
            "row_index": idx,
            "nid": _clean(row[NID_COL]),
            "title": _clean(row[TITLE_COL]),
            RESULT_COL: sector,
            "model_raw_sector": raw,
            "repaired_from": " | ".join(repaired),
            "unmapped": " | ".join(unmapped),
        })

    if not records:
        logging.warning("save_results: nothing to write.")
        return pd.DataFrame()

    out = pd.DataFrame(records)
    write_header = not os.path.exists(OUTPUT_CSV)
    out.to_csv(OUTPUT_CSV, mode="a", header=write_header, index=False, encoding="utf-8")

    logging.info(
        f"Appended {len(out)} row(s) to {OUTPUT_CSV} — "
        f"{(out['repaired_from'] != '').sum()} repaired into the vocabulary, "
        f"{(out['unmapped'] != '').sum()} still unmapped"
    )
    return out


def revalidate() -> None:
    """Rebuild the results CSV from the saved raw batch outputs.

    Lets a change to the vocabulary or to `normalise_sector` be applied to
    completed batches without re-sending anything to the API.
    """
    raw_files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.startswith("aikosh_sector_output_") and f.endswith(".jsonl")
    )
    if not raw_files:
        logging.error(f"No aikosh_sector_output_*.jsonl found in {OUTPUT_DIR}")
        return

    results: dict[int, str] = {}
    for name in raw_files:
        with open(os.path.join(OUTPUT_DIR, name), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                try:
                    content = obj["response"]["body"]["choices"][0]["message"]["content"]
                    results[int(obj["custom_id"])] = str(
                        json.loads(content).get("sector", "")
                    ).strip()
                except Exception as e:
                    logging.warning(f"{name} custom_id={obj.get('custom_id')}: {e}")
    logging.info(f"Read {len(results)} result(s) from {len(raw_files)} raw output file(s)")

    df = pd.read_csv(SOURCE_CSV).reset_index().rename(columns={"index": "row_index"})
    df = df[["row_index", NID_COL, TITLE_COL]]

    if os.path.exists(OUTPUT_CSV):
        backup = OUTPUT_CSV.replace(".csv", f".bak_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        os.rename(OUTPUT_CSV, backup)
        logging.info(f"Previous results moved to {backup}")
    save_results(df, results)


def _family_key(title: str) -> str:
    """Collapse a title to its family: siblings differ only by digits/whitespace.

    "Data Item Comparison Report of Agra (Uttar Pradesh) for 2011-2012" and its
    2012-2013 sibling share a key.
    """
    import re
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", str(title))).strip().lower()


def harmonise_families() -> None:
    """Force one sector per title family, in place on the results CSV.

    The prompt asks for family consistency but cannot deliver it: the model sees
    one title at a time and has no idea what its siblings were assigned. On
    titles that are uninformative on their own ("Data Item Comparison Report of
    Agra"), it coin-flips — 365 of 1,372 multi-row families disagreed with
    themselves. This resolves each family after the fact:

    * Family agrees on the SECTOR but splits on the SUB-SECTOR -> drop to the
      bare sector. If siblings that differ only by year disagree about which
      sub-sector applies, the title does not support a sub-sector at all. This
      is what fixes ambient air-quality datasets, which the model scattered
      across Vehicular / Industrial Air Pollution and the bare sector: ambient
      monitoring attributes to no pollution source.
    * Family splits on the SECTOR -> plurality vote. `value_counts()` sorts
      stably, so a tie goes to whichever value appears first in row_index order
      and the result is reproducible across runs. Families whose winner lacks a
      strict majority are counted and reported — one guess is being propagated
      to the whole family there.

    Singleton families are untouched. The pre-harmonisation value is preserved
    in `pre_harmonise_sector`.
    """
    if not os.path.exists(OUTPUT_CSV):
        logging.error(f"{OUTPUT_CSV} does not exist — run the job first.")
        return

    r = pd.read_csv(OUTPUT_CSV)
    r[RESULT_COL] = r[RESULT_COL].fillna("")
    if "pre_harmonise_sector" not in r.columns:
        r["pre_harmonise_sector"] = r[RESULT_COL]

    # This rewrites OUTPUT_CSV in place; keep the pre-pass copy so a crash
    # mid-write cannot destroy an hour of batch results.
    backup = OUTPUT_CSV.replace(".csv", f".bak_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    r.to_csv(backup, index=False, encoding="utf-8")
    logging.info(f"Pre-harmonise copy → {backup}")

    key = r["title"].map(_family_key)
    changed = sector_votes = sub_drops = no_majority = 0

    for _, idx in r.groupby(key).groups.items():
        if len(idx) < 2:
            continue
        values = r.loc[idx, RESULT_COL]
        # A blank would win the "one sector" branch and wipe the family.
        values = values[values.str.strip() != ""]
        if len(values) < 2 or values.nunique() < 2:
            continue

        sectors = values.map(lambda v: {p.split(";")[0].strip() for p in v.split(",")})
        one_sector = set.union(*sectors) if len(sectors) else set()
        if len(one_sector) == 1:
            winner = one_sector.pop()          # sub-sector unsupported by title
            sub_drops += 1
        else:
            counts = values.value_counts()
            winner = counts.index[0]
            sector_votes += 1
            # A "majority" that is really a plurality or a tie propagates one
            # guess to the whole family. Counted so it can be reported rather
            # than shipped silently.
            if counts.iloc[0] <= len(values) / 2:
                no_majority += 1

        changed += int((values != winner).sum())
        r.loc[values.index, RESULT_COL] = winner

    r.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    logging.info(
        f"Harmonised {sub_drops + sector_votes} split famil(ies) "
        f"({sub_drops} dropped to a bare sector, {sector_votes} by majority vote) — "
        f"{changed} row(s) changed. Wrote {OUTPUT_CSV}"
    )


def replace_sector_in_source() -> None:
    """Overwrite the source CSV's `sector` column with the classified value.

    Destructive by request — the column being replaced holds earlier work (a mix
    of the AIKosh platform taxonomy and a partial SECTOR_VOCAB pass), so the
    original is copied to a timestamped .bak alongside it first. Every row must
    have a classified sector or nothing is written; a partial replacement would
    silently blank rows.
    """
    if not os.path.exists(OUTPUT_CSV):
        logging.error(f"{OUTPUT_CSV} does not exist — run the job first.")
        return

    src = pd.read_csv(SOURCE_CSV)
    res = pd.read_csv(OUTPUT_CSV).drop_duplicates("row_index", keep="last")
    mapping = dict(zip(res["row_index"], res[RESULT_COL]))
    new = src.index.map(mapping)

    missing = pd.isna(new).sum()
    if missing:
        logging.error(
            f"{missing}/{len(src)} row(s) have no classified sector — refusing to "
            f"write a partial replacement. Run --resume to fill the gaps first."
        )
        return

    backup = SOURCE_CSV.replace(".csv", f".bak_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    src.to_csv(backup, index=False, encoding="utf-8")
    logging.info(f"Original sector column preserved in {backup}")

    src["sector"] = new
    src.columns = ["" if c.startswith("Unnamed:") else c for c in src.columns]
    src.to_csv(SOURCE_CSV, index=False, encoding="utf-8")
    logging.info(f"Replaced `sector` on all {len(src)} row(s) of {SOURCE_CSV}")


def annotate_source() -> None:
    """Write a copy of the source CSV with `generated_sector` joined on row_index.

    The source file and its existing `sector` column are left untouched. The
    source header has one unnamed column, which pandas reads as "Unnamed: 5";
    it is restored to blank so the copy's header matches the original.
    """
    if not os.path.exists(OUTPUT_CSV):
        logging.error(f"{OUTPUT_CSV} does not exist — run the job first.")
        return

    src = pd.read_csv(SOURCE_CSV)
    res = pd.read_csv(OUTPUT_CSV).drop_duplicates("row_index", keep="last")
    mapping = dict(zip(res["row_index"], res[RESULT_COL]))
    src[RESULT_COL] = src.index.map(mapping)

    filled = src[RESULT_COL].notna().sum()
    logging.info(f"{filled}/{len(src)} row(s) have a generated sector")

    src.columns = ["" if c.startswith("Unnamed:") else c for c in src.columns]
    src.to_csv(ANNOTATED_CSV, index=False, encoding="utf-8")
    logging.info(f"Annotated copy → {ANNOTATED_CSV}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_batch_job(limit: int | None, offset: int, chunk_size: int,
                  resume: bool) -> list[str]:
    df = load_rows(limit=limit, offset=offset, resume=resume)
    if df.empty:
        logging.warning("Nothing to process.")
        return []

    chunks = [df.iloc[i:i + chunk_size] for i in range(0, len(df), chunk_size)]
    logging.info(f"Split {len(df)} rows into {len(chunks)} chunk(s) of up to {chunk_size}")

    all_ids: list[str] = []
    done = 0

    for start in range(0, len(chunks), MAX_CONCURRENT_BATCHES):
        window = chunks[start:start + MAX_CONCURRENT_BATCHES]
        window_ids = []
        for i, chunk in enumerate(window):
            n = start + i + 1
            logging.info(f"Submitting chunk {n}/{len(chunks)} ({len(chunk)} rows)...")
            window_ids.append(submit_batch(upload_requests(chunk, suffix=f"_chunk{n}")))

        completed = _retry_failed_batches([poll_batch(b) for b in window_ids])

        results: dict[int, str] = {}
        for batch in completed:
            results.update(download_results(batch))
        # Persist per window — a full run is many hours and an end-only write
        # loses everything on a crash.
        if results:
            save_results(pd.concat(window), results)
        done += len(results)
        all_ids.extend(window_ids)
        logging.info(f"{done}/{len(df)} rows saved so far.")

    logging.info(f"All done. {done} rows over {len(all_ids)} batch job(s).")
    return all_ids


def resume_poll(batch_id: str) -> None:
    """Resume an already-submitted batch, rebuilding its rows from the input file."""
    batch = poll_batch(batch_id)
    input_text = client.files.content(batch.input_file_id).text
    idxs = [int(json.loads(l)["custom_id"]) for l in input_text.splitlines() if l.strip()]
    logging.info(f"Reconstructed {len(idxs)} row_index values from the input file")

    df = pd.read_csv(SOURCE_CSV).reset_index().rename(columns={"index": "row_index"})
    df = df[df["row_index"].isin(idxs)][["row_index", NID_COL, TITLE_COL]]
    save_results(df, download_results(batch))


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Title-only sector classification for the AIKosh metadata CSV"
    )
    p.add_argument("--limit", type=int, default=None, help="Cap rows (for testing)")
    p.add_argument("--offset", type=int, default=0, help="Skip the first N rows")
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                   help=f"Rows per OpenAI batch (default: {DEFAULT_CHUNK_SIZE}). "
                        "chunk-size x ~1.5k prompt tokens must stay under the "
                        "2M enqueued-token cap")
    p.add_argument("--resume", action="store_true",
                   help="Skip rows already present in the results CSV")
    p.add_argument("--poll", metavar="BATCH_ID", help="Resume polling an existing batch")
    p.add_argument("--annotate", action="store_true",
                   help="Write the annotated source copy from the results CSV and exit")
    p.add_argument("--revalidate", action="store_true",
                   help="Rebuild the results CSV from saved raw batch outputs "
                        "(re-applies vocabulary normalisation, no API calls)")
    p.add_argument("--harmonise", action="store_true",
                   help="Force one sector per title family in the results CSV "
                        "(run after --revalidate, before --annotate)")
    p.add_argument("--replace-sector", action="store_true",
                   help="Overwrite the source CSV's `sector` column in place "
                        "(backs the original up to a timestamped .bak first)")
    args = p.parse_args()

    if args.revalidate:
        revalidate()
    elif args.harmonise:
        harmonise_families()
    elif args.replace_sector:
        replace_sector_in_source()
    elif args.annotate:
        annotate_source()
    elif args.poll:
        resume_poll(args.poll)
    else:
        ids = run_batch_job(args.limit, args.offset, args.chunk_size, args.resume)
        if ids:
            print(f"\nDone. batch_ids={ids}")
            print(f"Results → {OUTPUT_CSV}")
            print("Then:  python ai_kosh_assign_sectors.py --annotate")
