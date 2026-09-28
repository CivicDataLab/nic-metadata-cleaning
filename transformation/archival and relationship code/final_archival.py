# ============================================================
# SAFE 200K DATASET RELATION PIPELINE
# WINDOWS SAFE
# LOW RAM
# LAPTOP SAFE
# INPUT COLUMN = Title
# ============================================================

# pip install pandas sentence-transformers faiss-cpu rapidfuzz tqdm networkx

import os
import re
import gc
import argparse
import faiss
import numpy as np
import pandas as pd
import networkx as nx

from tqdm import tqdm
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer

# ============================================================
# CONFIG
# ============================================================

DEFAULT_INPUT_FILE = "dataset_signatures.csv"

DEFAULT_RELATION_OUTPUT = "dataset_relations.csv"

DEFAULT_CANONICAL_OUTPUT = "canonical_datasets.csv"

DEFAULT_TOP_K = 5

DEFAULT_SIM_THRESHOLD = 0.84

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def parse_args():

    parser = argparse.ArgumentParser(
        description="Detect duplicate / longitudinal / related dataset families from title signatures."
    )

    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_FILE,
        help="Signature CSV produced by signature.py."
    )

    parser.add_argument(
        "--relations-output",
        default=DEFAULT_RELATION_OUTPUT,
        help="Where to write the pairwise relations CSV."
    )

    parser.add_argument(
        "--canonical-output",
        default=DEFAULT_CANONICAL_OUTPUT,
        help="Where to write the canonical-group CSV."
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Neighbours retrieved per dataset. Raise it when families are larger than TOP_K."
    )

    parser.add_argument(
        "--sim-threshold",
        type=float,
        default=DEFAULT_SIM_THRESHOLD,
        help="Minimum cosine similarity for a neighbour to be considered."
    )

    parser.add_argument(
        "--embeddings-cache",
        default=None,
        help="Optional .npy path. Reused if it matches the input row count, "
             "written otherwise -- lets a re-run at a different --top-k skip the embedding pass."
    )

    return parser.parse_args()

# ============================================================
# REGEX
# ============================================================

YEAR_REGEX = re.compile(
    r"(?:19|20)\d{2}"
)

NUMBER_REGEX = re.compile(
    r"\d+(?:\.\d+)?"
)

# ============================================================
# GENERIC WORDS
# ============================================================

GENERIC_WORDS = {

    "india",
    "state",
    "states",
    "wise",
    "district",
    "number",
    "rate",
    "total",
    "data",
    "report",
    "year",
    "years",
    "march",
    "april",
    "january",
    "february",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "as",
    "on",
    "for",
    "from",
    "upto"
}

# ============================================================
# VARIANT TERMS
# ============================================================

VARIANT_TERMS = {

    "tribal",
    "rural",
    "urban",
    "male",
    "female",
    "sex",
    "residence"
}

# ============================================================
# NORMALIZE
# ============================================================

def normalize(text):

    text = str(text).lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text

# ============================================================
# TOKENIZE
# ============================================================

def tokenize(text):

    return [

        w for w in normalize(text).split()

        if w not in GENERIC_WORDS
    ]

# ============================================================
# YEARS
# ============================================================

def extract_years(text):

    years = YEAR_REGEX.findall(
        str(text)
    )

    return sorted(
        list(set(
            map(int, years)
        ))
    )

# ============================================================
# NUMBERS
# ============================================================

def extract_numbers(text):

    nums = NUMBER_REGEX.findall(
        str(text)
    )

    cleaned = []

    for n in nums:

        if re.match(
            r"(19|20)\d{2}",
            n
        ):
            continue

        cleaned.append(n)

    return sorted(cleaned)

# ============================================================
# REMOVE YEARS
# ============================================================

def remove_years(text):

    text = YEAR_REGEX.sub(
        "",
        str(text)
    )

    return normalize(text)

# ============================================================
# FAMILY TYPE
# ============================================================

def detect_family_type(

    source_title,
    target_title,

    source_metric,
    target_metric,

    source_years,
    target_years,

    source_numbers,
    target_numbers,

    fuzzy_score
):

    s_tokens = set(
        tokenize(source_title)
    )

    t_tokens = set(
        tokenize(target_title)
    )

    # ========================================================
    # ANALYTICAL VARIANT
    # ========================================================

    s_variant = len(
        s_tokens & VARIANT_TERMS
    )

    t_variant = len(
        t_tokens & VARIANT_TERMS
    )

    if s_variant != t_variant:

        if (

            len(source_years) > 0

            and len(target_years) > 0
        ):

            sy = max(source_years)

            ty = max(target_years)

            if abs(sy - ty) <= 1:

                return "ANALYTICAL_VARIANT"

    # ========================================================
    # EXACT DUPLICATE
    # ========================================================

    if (

        source_metric == target_metric

        and source_years == target_years

        and source_numbers == target_numbers

        and fuzzy_score > 0.99
    ):

        return "EXACT_DUPLICATE"

    # ========================================================
    # LONGITUDINAL
    # ========================================================

    if (

        source_metric == target_metric

        and source_numbers == target_numbers

        and len(source_years) > 0

        and len(target_years) > 0

        and fuzzy_score > 0.92
    ):

        return "LONGITUDINAL"

    # ========================================================
    # RELATED
    # ========================================================

    overlap = len(
        s_tokens & t_tokens
    )

    if overlap >= 3:

        return "RELATED"

    return None

# ============================================================
# EMBEDDING TEXT
# ============================================================

def embedding_text(row):

    return " | ".join([

        str(row["metric"]),

        str(row["alternative_metrics"]),

        str(row["modifiers"]),

        str(row["conditions"])
    ])

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    args = parse_args()

    INPUT_FILE = args.input

    RELATION_OUTPUT = args.relations_output

    CANONICAL_OUTPUT = args.canonical_output

    TOP_K = args.top_k

    SIM_THRESHOLD = args.sim_threshold

    EMBEDDINGS_CACHE = args.embeddings_cache

    print("\n===================================")
    print("SAFE 200K PIPELINE STARTING")
    print("===================================\n")

    print(f"Input          : {INPUT_FILE}")
    print(f"Relations out  : {RELATION_OUTPUT}")
    print(f"Canonical out  : {CANONICAL_OUTPUT}")
    print(f"TOP_K          : {TOP_K}")
    print(f"SIM_THRESHOLD  : {SIM_THRESHOLD}")

    # ========================================================
    # LOAD DATA
    # ========================================================

    print("Loading datasets...")

    df = pd.read_csv(
        INPUT_FILE
    )

    df = df.fillna("")

    # ========================================================
    # HANDLE TITLE COLUMN
    # ========================================================

    if "Title" in df.columns:

        df["title"] = df["Title"]

    print(f"Datasets loaded: {len(df)}")

    # ========================================================
    # EMBEDDINGS
    # --------------------------------------------------------
    # Reuse the cache only when its row count matches the
    # input; a stale cache would silently pair the wrong
    # vectors with the wrong nids.
    # ========================================================

    embeddings = None

    if EMBEDDINGS_CACHE and os.path.exists(EMBEDDINGS_CACHE):

        cached = np.load(EMBEDDINGS_CACHE)

        if cached.shape[0] == len(df):

            print(f"\nReusing cached embeddings: {EMBEDDINGS_CACHE} {cached.shape}")

            embeddings = cached.astype(np.float32)

        else:

            print(
                f"\nIgnoring cache {EMBEDDINGS_CACHE}: "
                f"{cached.shape[0]} rows vs {len(df)} in input."
            )

        del cached

    if embeddings is None:

        print("\nLoading embedding model...")

        model = SentenceTransformer(
            MODEL_NAME
        )

        print("\nGenerating embeddings...")

        texts = [

            embedding_text(r)

            for _, r in df.iterrows()
        ]

        embeddings = model.encode(

            texts,

            batch_size=512,

            normalize_embeddings=True,

            show_progress_bar=True
        )

        embeddings = np.array(
            embeddings,
            dtype=np.float32
        )

        # free memory
        del texts
        gc.collect()

        if EMBEDDINGS_CACHE:

            np.save(EMBEDDINGS_CACHE, embeddings)

            print(f"Cached embeddings -> {EMBEDDINGS_CACHE}")

    # ========================================================
    # FAISS
    # ========================================================

    print("\nBuilding FAISS index...")

    index = faiss.IndexFlatIP(
        embeddings.shape[1]
    )

    index.add(embeddings)

    # ========================================================
    # SEARCH
    # ========================================================

    print("\nFinding nearest neighbors...")

    similarities, neighbors = index.search(

        embeddings,

        TOP_K
    )

    # ========================================================
    # TOP_K SATURATION
    # --------------------------------------------------------
    # A row is "saturated" when every neighbour returned still
    # clears SIM_THRESHOLD, i.e. TOP_K -- not similarity -- is
    # what cut the family short. A high rate means the family
    # sizes exceed TOP_K and recall is being truncated.
    # ========================================================

    above = (similarities >= SIM_THRESHOLD).sum(axis=1)

    saturated = int((above >= TOP_K).sum())

    print(
        f"\nTOP_K saturation: {saturated}/{len(df)} rows "
        f"({100.0 * saturated / max(len(df), 1):.2f}%) returned "
        f"{TOP_K}/{TOP_K} neighbours above the threshold."
    )

    if saturated > 0.02 * len(df):

        print(
            "  -> TOP_K is truncating recall for these rows; "
            "consider re-running with a larger --top-k."
        )

    # ========================================================
    # CLEANUP
    # ========================================================

    del embeddings
    gc.collect()

    # ========================================================
    # RELATIONS
    # ========================================================

    print("\nGenerating relations...")

    relations = []

    graph_edges = []

    seen_pairs = set()

    # diagnostic: true detected pair count per family_type, counted
    # BEFORE the LONGITUDINAL direction gate drops rows (see HANDOVER 6).
    detected_counts = {}

    # ========================================================

    for i in tqdm(range(len(df))):

        source = df.iloc[i]

        source_nid = source["nid"]

        source_title = str(
            source["title"]
        )

        source_metric = normalize(
            source["metric"]
        )

        source_years = extract_years(
            source_title
        )

        source_numbers = extract_numbers(
            source_title
        )

        source_no_year = remove_years(
            source_title
        )

        # ====================================================

        for score, nbr in zip(

            similarities[i],

            neighbors[i]
        ):

            if i == nbr:
                continue

            if score < SIM_THRESHOLD:
                continue

            target = df.iloc[nbr]

            target_nid = target["nid"]

            target_title = str(
                target["title"]
            )

            target_metric = normalize(
                target["metric"]
            )

            target_years = extract_years(
                target_title
            )

            target_numbers = extract_numbers(
                target_title
            )

            target_no_year = remove_years(
                target_title
            )

            # =================================================

            pair = tuple(sorted([
                source_nid,
                target_nid
            ]))

            if pair in seen_pairs:
                continue

            seen_pairs.add(pair)

            # =================================================

            fuzzy = fuzz.token_sort_ratio(

                source_no_year,

                target_no_year

            ) / 100

            # =================================================

            family_type = detect_family_type(

                source_title,
                target_title,

                source_metric,
                target_metric,

                source_years,
                target_years,

                source_numbers,
                target_numbers,

                fuzzy
            )

            if family_type is None:
                continue

            detected_counts[family_type] = detected_counts.get(family_type, 0) + 1

            # =================================================
            # GRAPH EDGES
            # =================================================

            if family_type in {

                "EXACT_DUPLICATE",
                "LONGITUDINAL"
            }:

                graph_edges.append((
                    source_nid,
                    target_nid
                ))

            # =================================================
            # LONGITUDINAL
            # =================================================

            if family_type == "LONGITUDINAL":

                sy = max(source_years)

                ty = max(target_years)

                if abs(sy - ty) <= 2:

                    if sy < ty:

                        relations.append({

                            "source_nid":
                                source_nid,

                            "source_title":
                                source_title,

                            "relation":
                                "dcterms:hasVersion",

                            "target_nid":
                                target_nid,

                            "target_title":
                                target_title,

                            "family_type":
                                family_type,

                            "confidence":
                                round(score, 4)
                        })

                        relations.append({

                            "source_nid":
                                target_nid,

                            "source_title":
                                target_title,

                            "relation":
                                "dcterms:isVersionOf",

                            "target_nid":
                                source_nid,

                            "target_title":
                                source_title,

                            "family_type":
                                family_type,

                            "confidence":
                                round(score, 4)
                        })

            # =================================================
            # OTHER RELATIONS
            # =================================================

            else:

                relations.append({

                    "source_nid":
                        source_nid,

                    "source_title":
                        source_title,

                    "relation":
                        "dcterms:relation",

                    "target_nid":
                        target_nid,

                    "target_title":
                        target_title,

                    "family_type":
                        family_type,

                    "confidence":
                        round(score * 0.75, 4)
                })

        # ====================================================
        # PERIODIC MEMORY CLEANUP
        # ====================================================

        if i % 10000 == 0:

            gc.collect()

    # ========================================================
    # BUILD GRAPH
    # ========================================================

    print("\nDetected pairs by family_type (pre-direction-gate):")
    for _ft in sorted(detected_counts):
        print(f"  {_ft:<20} {detected_counts[_ft]}")

    print("\nBuilding canonical graph...")

    G = nx.Graph()

    G.add_edges_from(graph_edges)

    # ========================================================
    # CANONICAL GROUPS
    # ========================================================

    print("\nGenerating canonical groups...")

    canonical_rows = []

    # nid -> title, built once. The previous
    # df[df["nid"] == nid] inside the loop below was a full
    # table scan per member per component.

    nid_to_title = dict(
        zip(df["nid"], df["title"])
    )

    components = list(
        nx.connected_components(G)
    )

    canonical_counter = 1

    assigned = set()

    # ========================================================

    for component in tqdm(components):

        component = list(component)

        rows = []

        for nid in component:

            title = str(
                nid_to_title[nid]
            )

            years = extract_years(title)

            rows.append({

                "nid": nid,

                "title": title,

                "years": years
            })

        rows = sorted(

            rows,

            key=lambda x:

            max(x["years"])

            if len(x["years"]) > 0

            else 0,

            reverse=True
        )

        canonical = rows[0]

        canonical_id = f"canon_{canonical_counter}"

        canonical_counter += 1

        unique_titles = len(set([

            normalize(x["title"])

            for x in rows
        ]))

        # ====================================================

        for r in rows:

            assigned.add(
                r["nid"]
            )

            is_canonical = (

                r["nid"]

                == canonical["nid"]
            )

            archival_flag = False

            if (

                not is_canonical

                and unique_titles == 1
            ):

                archival_flag = True

            canonical_rows.append({

                "nid":
                    r["nid"],

                "title":
                    r["title"],

                "canonical_id":
                    canonical_id,

                "canonical_nid":
                    canonical["nid"],

                "canonical_title":
                    canonical["title"],

                "is_canonical":
                    is_canonical,

                "archival_flag":
                    archival_flag
            })

    # ========================================================
    # SINGLETONS
    # ========================================================

    print("\nAdding singleton datasets...")

    for _, row in tqdm(df.iterrows(), total=len(df)):

        nid = row["nid"]

        if nid in assigned:
            continue

        canonical_rows.append({

            "nid":
                nid,

            "title":
                row["title"],

            "canonical_id":
                f"canon_{canonical_counter}",

            "canonical_nid":
                nid,

            "canonical_title":
                row["title"],

            "is_canonical":
                True,

            "archival_flag":
                False
        })

        canonical_counter += 1

    # ========================================================
    # DATAFRAMES
    # ========================================================

    print("\nCreating output files...")

    relations_df = pd.DataFrame(
        relations
    )

    relations_df = relations_df.drop_duplicates()

    canonical_df = pd.DataFrame(
        canonical_rows
    )

    # ========================================================
    # SAVE
    # ========================================================

    relations_df.to_csv(

        RELATION_OUTPUT,

        index=False
    )

    canonical_df.to_csv(

        CANONICAL_OUTPUT,

        index=False
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n===================================")
    print("PIPELINE COMPLETE")
    print("===================================")

    print(f"\nRelations: {len(relations_df)}")

    print(f"Canonical Groups: {len(components)}")

    print(f"Canonical Rows: {len(canonical_df)}")

    print("\nSaved Files:")

    print(f"- {RELATION_OUTPUT}")

    print(f"- {CANONICAL_OUTPUT}")