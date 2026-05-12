# ============================================================
# STEP 1 — SIGNATURE GENERATION
# ============================================================

# pip install pandas nltk

import re
import pandas as pd

# ============================================================

INPUT_FILE = "dublin_core_metadata_.csv"

OUTPUT_FILE = "dataset_signatures.csv"

# ============================================================

df = pd.read_csv(INPUT_FILE)

df = df.fillna("")

# ============================================================

STOPWORDS = {

    "number",
    "rate",
    "wise",
    "state",
    "states",
    "district",
    "india",
    "year",
    "years",
    "data",
    "report",
    "as",
    "on",
    "for",
    "from",
    "upto"
}

# ============================================================

YEAR_REGEX = re.compile(
    r"(?:19|20)\d{2}"
)

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

def remove_years(text):

    return YEAR_REGEX.sub(
        "",
        str(text)
    )

# ============================================================

def tokenize(text):

    return [

        w for w in normalize(text).split()

        if w not in STOPWORDS
    ]

# ============================================================

def build_metric(title):

    title = remove_years(title)

    tokens = tokenize(title)

    metric = " ".join(tokens[:6])

    return metric.strip()

# ============================================================

def build_alt_metrics(title):

    tokens = tokenize(title)

    ngrams = []

    for n in [2, 3]:

        for i in range(len(tokens)-n+1):

            ngrams.append(

                " ".join(
                    tokens[i:i+n]
                )
            )

    return "|".join(
        list(dict.fromkeys(ngrams))[:10]
    )

# ============================================================

df["metric"] = df["Title"].apply(
    build_metric
)

df["alternative_metrics"] = df["Title"].apply(
    build_alt_metrics
)

df["modifiers"] = ""

df["conditions"] = ""

# ============================================================

df.to_csv(
    OUTPUT_FILE,
    index=False
)

print(f"Saved: {OUTPUT_FILE}")