# ============================================================
# SAFE 200K DATASET RELATION PIPELINE
# WINDOWS SAFE
# LOW RAM
# LAPTOP SAFE
# INPUT COLUMN = Title
# ============================================================

# pip install pandas sentence-transformers faiss-cpu rapidfuzz tqdm networkx

import re
import gc
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

INPUT_FILE = "dataset_signatures.csv"

RELATION_OUTPUT = "dataset_relations.csv"

CANONICAL_OUTPUT = "canonical_datasets.csv"

TOP_K = 5

SIM_THRESHOLD = 0.84

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

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

    print("\n===================================")
    print("SAFE 200K PIPELINE STARTING")
    print("===================================\n")

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
    # MODEL
    # ========================================================

    print("\nLoading embedding model...")

    model = SentenceTransformer(
        MODEL_NAME
    )

    # ========================================================
    # EMBEDDINGS
    # ========================================================

    print("\nGenerating embeddings...")

    texts = [

        embedding_text(r)

        for _, r in df.iterrows()
    ]

    embeddings = model.encode(

        texts,

        batch_size=64,

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

    print("\nBuilding canonical graph...")

    G = nx.Graph()

    G.add_edges_from(graph_edges)

    # ========================================================
    # CANONICAL GROUPS
    # ========================================================

    print("\nGenerating canonical groups...")

    canonical_rows = []

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

            r = df[
                df["nid"] == nid
            ].iloc[0]

            title = str(r["title"])

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