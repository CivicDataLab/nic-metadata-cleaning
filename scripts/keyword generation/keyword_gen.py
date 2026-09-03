import os
import re
import json
import time
import yaml
import logging
import unicodedata

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI
#C:\Users\HP\scrape\2nd batch\keyword_gen.py
load_dotenv()

# ==========================================================
# CONFIGURATION
# ==========================================================

INPUT_FILE = r"C:\Users\HP\scrape\2nd batch\keyword sets\niti.xlsx"
YAML_FILE = r"C:\Users\HP\scrape\2nd batch\controlled vocab\control_vocab_niti.yaml"
OUTPUT_FILE = "niti_keywords.xlsx"

DEFAULT_MODEL = "gpt-5.4-nano"

DEFAULT_WORKERS = 5

SAVE_EVERY = 5000

MAX_RETRIES = 3

USE_LLM_FALLBACK = False

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

SEARCH_COLUMNS = [

    "Title",
    "Description",
    "Abstract",
    "Note",

    "Coverage",
    "Jurisdiction",

    "Relation[Catalog Title]",

    "Subject[sector_resource]",

    "Publisher[ministry_department]",

    "High Value Dataset Category"

]
from rapidfuzz import fuzz

TOKEN_MATCH_THRESHOLD = 0.75

FUZZY_MATCH_THRESHOLD = 90

MIN_RULE_SCORE = 25
# ==========================================================
# LOGGING
# ==========================================================

def setup_logging():

    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(

        level=logging.INFO,

        format="%(asctime)s | %(levelname)s | %(message)s",

        handlers=[

            logging.StreamHandler(),

            logging.FileHandler(

                "logs/keyword_generation.log",

                encoding="utf-8"

            )

        ]

    )

    return logging.getLogger(__name__)


logger = setup_logging()
# ==========================================================
# UTILITY FUNCTIONS
# ==========================================================

def clean(value):

    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.lower() == "nan":
        return ""

    return value


def normalize_text(text):

    text = clean(text)

    if not text:
        return ""

    text = text.lower()

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        c
        for c in text
        if not unicodedata.combining(c)
    )

    text = re.sub(
        r"[-_/\\|]",
        " ",
        text
    )

    text = re.sub(
        r"[^\w\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()
def collapse_text(text):
    """
    Collapse spaces after normalization.

    Example

    Blue Dart  -> bluedart
    Go Air     -> goair
    PM Kisan   -> pmkisan
    """

    return normalize_text(text).replace(" ", "")


def deduplicate_keep_order(values):

    seen = set()

    output = []

    for value in values:

        if not value:
            continue

        key = normalize_text(value)

        if key in seen:
            continue

        seen.add(key)

        output.append(value)

    return output

# ==========================================================
# MATCHING HELPERS
# ==========================================================

def tokenize(text):
    """
    Convert text into a unique token set.
    """

    text = normalize_text(text)

    if not text:
        return set()

    return set(text.split())
# ==========================================================
# TOKEN WEIGHTING
# ==========================================================

STOPWORDS = {

    "the","of","for","to","and","or","on","in","by",

    "from","during","under","over","with",

    "annual","monthly","yearly","year","wise",

    "statement","comparative","selected",

    "statistics","statistical","statistic",

    "report","reports",

    "information","details",

    "total",

    "all",

    "series",

    "data"

}


def important_tokens(tokens):
    """
    Remove common words that shouldn't influence matching.
    """

    return {

        t

        for t in tokens

        if (

            len(t) > 2

            and

            t not in STOPWORDS

        )

    }

def token_overlap_score(pattern_tokens, text_tokens):
    """
    Weighted token overlap.

    Common words like

        annual
        statement
        report

    are ignored.
    """

    pattern_tokens = important_tokens(pattern_tokens)

    text_tokens = important_tokens(text_tokens)

    if not pattern_tokens:
        return 0.0

    overlap = len(pattern_tokens & text_tokens)

    return overlap / len(pattern_tokens)

def fuzzy_pattern_score(pattern, searchable_text):
    """
    RapidFuzz partial ratio.

    Returns
    -------
    Integer 0-100
    """

    return fuzz.partial_ratio(
        pattern,
        searchable_text
    )


def score_pattern(
    
    pattern,

    collapsed_pattern,

    regex,

    pattern_tokens,

    searchable_text,

    searchable_tokens
):
    """
    Hybrid matcher.

    Returns

    {
        matched: bool
        method: regex/token/fuzzy
        score: int
    }
    """

    # -------------------------
    # EXACT REGEX
    # -------------------------
    collapsed_text = collapse_text(searchable_text)

    if (
    regex.search(searchable_text)
    or
    collapsed_pattern in collapsed_text
):

        return {

            "matched": True,

            "method": "regex",

            "score": 100 + len(pattern_tokens)

        }

    # -------------------------
    # TOKEN OVERLAP
    # -------------------------

    overlap = token_overlap_score(

        pattern_tokens,

        searchable_tokens

    )

    if overlap >= TOKEN_MATCH_THRESHOLD:

        return {

            "matched": True,

            "method": "token",

            "score": int(overlap * 80)

        }

    # -------------------------
    # FUZZY
    # -------------------------

    fuzzy = fuzzy_pattern_score(

        pattern,

        searchable_text

    )

    if fuzzy >= FUZZY_MATCH_THRESHOLD:

        return {

            "matched": True,

            "method": "fuzzy",

            "score": fuzzy

        }

    return {

        "matched": False,

        "method": None,

        "score": 0

    }
# ==========================================================
# FIELD WEIGHTS
# ==========================================================

FIELD_WEIGHTS = {

    "Title": 5,

    "Relation[Catalog Title]": 4,

    "Subject[sector_resource]": 3,

    "High Value Dataset Category": 3,

    "Description": 2,

    "Abstract": 2,

    "Coverage": 1,

    "Jurisdiction": 1,

    "Publisher[ministry_department]": 1,

    "Note": 1

}


def get_searchable_fields(row):
    """
    Return normalized text for every searchable field.

    Example

    {
        "Title":
            "...",

        "Description":
            "...",

        ...
    }
    """

    fields = {}

    for column in SEARCH_COLUMNS:

        value = normalize_text(
            row.get(column)
        )

        if value:

            fields[column] = value

    return fields
# ==========================================================
# LOAD CONTROLLED VOCABULARY
# ==========================================================

# ==========================================================
# LOAD CONTROLLED VOCABULARY
# ==========================================================

def load_yaml(yaml_path=YAML_FILE):
    """
    Load controlled vocabulary.

    Pre-computes:
        - normalized patterns
        - compiled regex
        - token sets
        - longest pattern length

    This makes matching much faster.
    """

    logger.info(f"Loading vocabulary: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        vocabulary = yaml.safe_load(f)

    if not isinstance(vocabulary, list):
        raise ValueError(
            "Controlled vocabulary must be a list."
        )

    total_patterns = 0

    for rule in vocabulary:

        normalized_patterns = []

        compiled_patterns = []

        token_patterns = []
        collapsed_patterns = []

        max_pattern_words = 1

        for pattern in rule.get("patterns", []):

            normalized = normalize_text(pattern)
            collapsed = collapse_text(pattern)

            if not normalized:
                continue

            normalized_patterns.append(normalized)
            collapsed_patterns.append(collapsed)

            compiled_patterns.append(
                re.compile(
                    rf"\b{re.escape(normalized)}\b",
                    flags=re.IGNORECASE
                )
            )

            tokens = set(normalized.split())

            token_patterns.append(tokens)

            max_pattern_words = max(
                max_pattern_words,
                len(tokens)
            )

            total_patterns += 1

        rule["normalized_patterns"] = normalized_patterns
        rule["collapsed_patterns"] = collapsed_patterns

        rule["compiled_patterns"] = compiled_patterns

        rule["token_patterns"] = token_patterns
        

        rule["max_pattern_words"] = max_pattern_words

    logger.info(
        f"Loaded {len(vocabulary)} rules "
        f"({total_patterns} patterns)"
    )

    return vocabulary
# ==========================================================
# LOAD INPUT EXCEL
# ==========================================================

def load_excel(
    input_path=INPUT_FILE,
    output_path=OUTPUT_FILE
):
    """
    Load the input Excel file.

    Also determines which datasets
    have already been processed.
    """

    logger.info(f"Loading input file: {input_path}")

    df = pd.read_excel(input_path)

    logger.info(f"Loaded {len(df)} datasets.")

    processed = set()

    if os.path.exists(output_path):

        logger.info(
            "Previous output found. Resuming..."
        )

        try:

            old_df = pd.read_excel(output_path)

            if "nid" in old_df.columns:

                processed = set(
                    old_df["nid"]
                    .astype(str)
                    .str.strip()
                )

            logger.info(
                f"{len(processed)} datasets already processed."
            )

        except Exception as e:

            logger.warning(
                f"Unable to load previous output: {e}"
            )

    return df, processed
# ==========================================================
# SAVE CHECKPOINT
# ==========================================================

def save_checkpoint(
    results,
    output_path=OUTPUT_FILE
):
    """
    Save processed datasets.

    Supports resume by merging with any
    previous output and removing duplicates.
    """

    if not results:
        return

    new_df = pd.DataFrame(results)

    if os.path.exists(output_path):

        try:

            old_df = pd.read_excel(output_path)

            new_df = pd.concat(
                [old_df, new_df],
                ignore_index=True
            )

        except Exception as e:

            logger.warning(
                f"Unable to merge previous output: {e}"
            )

    if "nid" in new_df.columns:

        new_df["nid"] = (
            new_df["nid"]
            .astype(str)
            .str.strip()
        )

        new_df = (
            new_df
            .drop_duplicates(
                subset="nid",
                keep="last"
            )
            .reset_index(drop=True)
        )

    new_df.to_excel(
        output_path,
        index=False
    )

    logger.info(
        f"Checkpoint saved ({len(new_df)} rows)"
    )
# ==========================================================
# FIND MATCHING RULES
# ==========================================================

# ==========================================================
# FIND MATCHING RULES
# ==========================================================

def find_matching_rules(row, vocabulary):

    searchable_fields = get_searchable_fields(row)

    matched_rules = []

    for rule in vocabulary:

        best_score = 0

        matched_patterns = []

        matched_by = []

        for pattern, collapsed_pattern, regex, pattern_tokens in zip(

    rule["normalized_patterns"],

    rule["collapsed_patterns"],

    rule["compiled_patterns"],

    rule["token_patterns"]

):

            pattern_best = 0

            pattern_method = None

            matched = False

            for field_name, text in searchable_fields.items():

                tokens = tokenize(text)

                result = score_pattern(

                    pattern,

                collapsed_pattern,

                    regex,

                    pattern_tokens,

                        text,

                        tokens


                )

                if result["matched"]:

                    weight = FIELD_WEIGHTS.get(

                        field_name,

                        1

                    )

                    score = result["score"] * weight

                    if score > pattern_best:

                        pattern_best = score

                        pattern_method = result["method"]

                        matched = True

            if matched:

                best_score += pattern_best

                matched_patterns.append(pattern)

                matched_by.append(pattern_method)

        if matched_patterns:

            best_score += len(matched_patterns) * 10

            matched_rules.append({

                "rule": rule,

                "score": best_score,

                "matched_patterns": matched_patterns,

                "matched_by": matched_by

            })

    matched_rules.sort(

        key=lambda x: x["score"],

        reverse=True

    )

    return matched_rules
# ==========================================================
# BUILD KEYWORDS FROM YAML
# ==========================================================

def keywords_from_yaml(
    matched_rules,
    generic_max=4,
    sponsored_max=2
):
    """
    Build final keyword lists.

    Strategy

    1. Highest scoring rules first
    2. Remove duplicate categories
    3. Remove duplicate keywords
    4. Stop once keyword limit reached
    """

    generic = []

    sponsored = []

    matched_categories = []

    matched_patterns = []

    matched_by = []

    # Highest confidence first
    matched_rules = sorted(
        matched_rules,
        key=lambda x: x["score"],
        reverse=True
    )

    for match in matched_rules:

        rule = match["rule"]

        category = rule.get("category", "")

        if category and category not in matched_categories:
            matched_categories.append(category)

        for pattern in match.get("matched_patterns", []):

            if pattern not in matched_patterns:
                matched_patterns.append(pattern)

        for method in match.get("matched_by", []):

            if method not in matched_by:
                matched_by.append(method)

        # -------------------------
        # Generic keywords
        # -------------------------

        for keyword in rule.get("generic", []):

            keyword = clean(keyword)

            if not keyword:
                continue

            if normalize_text(keyword) not in {

                normalize_text(k)

                for k in generic

            }:

                generic.append(keyword)

            if len(generic) >= generic_max:
                break

        # -------------------------
        # Sponsored keywords
        # -------------------------

        for keyword in rule.get("sponsored", []):

            keyword = clean(keyword)

            if not keyword:
                continue

            if normalize_text(keyword) not in {

                normalize_text(k)

                for k in sponsored

            }:

                sponsored.append(keyword)

            if len(sponsored) >= sponsored_max:
                break

        if (
            len(generic) >= generic_max
            and
            len(sponsored) >= sponsored_max
        ):
            break

    return {

        "generated_keywords":
            generic,

        "generated_sponsored_keywords":
            sponsored,

        "matched_categories":
            matched_categories,

        "matched_patterns":
            matched_patterns,

        "matched_by":
            matched_by

    }
# ==========================================================
# BUILD SYSTEM PROMPT
# ==========================================================

def build_system_prompt(vocabulary):
    """
    Build a generic system prompt for the LLM fallback.
    """

    rules_text = []

    for rule in vocabulary:

        rules_text.append(

            f"""
Category: {rule.get("category","")}

Patterns:
{", ".join(rule.get("patterns", []))}

Allowed Generic Keywords:
{", ".join(rule.get("generic", []))}

Allowed Sponsored Keywords:
{", ".join(rule.get("sponsored", []))}
"""
        )

    rules_text = "\n".join(rules_text)

    return f"""
You are a metadata curator.

Generate keywords ONLY from the controlled vocabulary.

Rules

1. Never invent keywords.

2. Use only keywords present in the vocabulary.

3. Return maximum 4 generic keywords.

4. Return maximum 2 sponsored keywords.

5. Remove duplicates.

Return ONLY JSON.

{{
    "generated_keywords":[...],
    "generated_sponsored_keywords":[...]
}}

Controlled Vocabulary

{rules_text}
"""
# ==========================================================
# BUILD USER PROMPT
# ==========================================================

def build_user_prompt(row):
    """
    Build dataset metadata for LLM fallback.
    """

    prompt = []

    for column in SEARCH_COLUMNS:

        value = clean(row.get(column))

        if value:

            prompt.append(

                f"{column}:\n{value}"

            )

    prompt.append(

        "\nGenerate metadata keywords."

    )

    return "\n\n".join(prompt)
# ==========================================================
# CALL OPENAI
# ==========================================================

def call_llm(
    system_prompt,
    user_prompt,
    model=DEFAULT_MODEL
):
    """
    Call the OpenAI model.

    Automatically retries.
    """

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = client.chat.completions.create(

                model=model,

                response_format={
                    "type":"json_object"
                },

                messages=[

                    {

                        "role":"system",

                        "content":system_prompt

                    },

                    {

                        "role":"user",

                        "content":user_prompt

                    }

                ]

            )

            return json.loads(

                response.choices[0].message.content

            )

        except Exception as e:

            last_error = str(e)

            logger.warning(

                f"Attempt {attempt} failed : {e}"

            )

            if attempt < MAX_RETRIES:

                wait = 2 ** attempt

                logger.info(

                    f"Retrying in {wait} sec..."

                )

                time.sleep(wait)

    raise RuntimeError(last_error)
# ==========================================================
# PROCESS SINGLE DATASET
# ==========================================================

def process_single_row(
    row,
    vocabulary,
    model=DEFAULT_MODEL
):

    try:

        matched_rules = find_matching_rules(
            row,
            vocabulary
        )

        # --------------------------------------------------
        # YAML MATCH FOUND
        # --------------------------------------------------

        if matched_rules:

            result = keywords_from_yaml(
                matched_rules
            )

        # --------------------------------------------------
        # OPTIONAL LLM FALLBACK
        # --------------------------------------------------

        elif USE_LLM_FALLBACK:

            logger.info(
                f"No YAML match for nid={row.get('nid')}. Using LLM."
            )

            result = call_llm(

                build_system_prompt(vocabulary),

                build_user_prompt(row),

                model=model

            )

            result.setdefault(
                "matched_categories",
                []
            )

            result.setdefault(
                "matched_patterns",
                []
            )

        # --------------------------------------------------
        # NO MATCH
        # --------------------------------------------------

        else:

            result = {

                "generated_keywords": [],

                "generated_sponsored_keywords": [],

                "matched_categories": [],

                "matched_patterns": []

            }

        output = row.to_dict()

        output["generated_keywords"] = "; ".join(
            result.get(
                "generated_keywords",
                []
            )
        )

        output["generated_sponsored_keywords"] = "; ".join(
            result.get(
                "generated_sponsored_keywords",
                []
            )
        )

        output["matched_categories"] = "; ".join(
            result.get(
                "matched_categories",
                []
            )
        )

        output["matched_patterns"] = "; ".join(
            result.get(
                "matched_patterns",
                []
            )
        )
        output["matched_by"] = "; ".join(
            result.get(
                "matched_by",
                []
            )
        )
        

        output["matched_rule_count"] = len(
            matched_rules
        )

        output["status"] = "success"

        output["error"] = ""

        return output

    except Exception as e:

        logger.exception(e)

        output = row.to_dict()

        output["generated_keywords"] = ""

        output["generated_sponsored_keywords"] = ""

        output["matched_categories"] = ""

        output["matched_patterns"] = ""
        output["matched_by"] = ""

        output["matched_rule_count"] = 0

        output["status"] = "failed"

        output["error"] = str(e)

        return output
    # ==========================================================
# PROCESS COMPLETE DATAFRAME
# ==========================================================

def process_dataframe(

    df,

    processed,

    vocabulary,

    output_path=OUTPUT_FILE,

    model=DEFAULT_MODEL,

    workers=DEFAULT_WORKERS

):

    results = []

    if os.path.exists(output_path):

        try:

            old = pd.read_excel(output_path)

            results = old.to_dict("records")

        except Exception:

            pass

    rows = []

    for _, row in df.iterrows():

        nid = str(row.get("nid")).strip()

        if nid in processed:

            continue

        rows.append(row)

    logger.info(

        f"Remaining datasets : {len(rows)}"

    )

    completed = 0

    with ThreadPoolExecutor(

        max_workers=workers

    ) as executor:

        futures = [

            executor.submit(

                process_single_row,

                row,

                vocabulary,

                model

            )

            for row in rows

        ]

        for future in tqdm(

            as_completed(futures),

            total=len(futures),

            desc="Generating Keywords"

        ):

            result = future.result()

            results.append(result)

            completed += 1

            if completed % SAVE_EVERY == 0:

                save_checkpoint(

                    results,

                    output_path

                )

    save_checkpoint(

        results,

        output_path

    )

    logger.info("Processing completed.")
# ==========================================================
# MAIN
# ==========================================================

def main():

    logger.info("Starting keyword generation...")

    vocabulary = load_yaml()

    df, processed = load_excel()

    process_dataframe(

        df=df,

        processed=processed,

        vocabulary=vocabulary,

        output_path=OUTPUT_FILE,

        model=DEFAULT_MODEL,

        workers=DEFAULT_WORKERS

    )

    logger.info("Done.")


if __name__ == "__main__":

    main()