"""Assign controlled keywords to the AIKosh resource-catalogue datasets.

Deterministic, rule-based pass over
``AIKosh_ResourceCatalogMappingWithdata.gov.in_withResouceNID.xlsx`` using the
controlled vocabulary in ``ai_kosh_vocabulary.yaml``. Adds a single ``keywords``
column (comma-separated) describing WHAT each dataset is about.

Unlike the data.gov.in health pass (``assign_controlled_keywords.py``) this is:
  * single-tier  — one ``keywords`` column, no generic/sponsored split;
  * content-only — keywords describe the indicator/subject, never the state
    ("state-wise"), the year, or the reporting periodicity;
  * plain words  — every keyword is 1 or 2 words (enforced at load time);
    acronyms are translated to layman terms in the YAML, not emitted raw.

It reads the source xlsx, writes an annotated copy to a NEW file (the source is
never overwritten) and emits a review CSV for human spot-checking.

Run:
    python ai_kosh_assign_keywords.py              # full run -> *_with_keywords.xlsx
    python ai_kosh_assign_keywords.py --limit 50   # preview, CSV only, no xlsx
"""

from __future__ import annotations

import argparse
import logging
import os
import re

import pandas as pd
import yaml

logging.basicConfig(
    format="%(asctime)s : %(levelname)s - %(message)s", level=logging.INFO
)

BASE_DIR = "/home/aakash/NIC/Newfolder"
SOURCE_XLSX = os.path.join(
    BASE_DIR, "AIKosh_ResourceCatalogMappingWithdata.gov.in_withResouceNID.xlsx"
)
SOURCE_SHEET = "raw sheet"
OUTPUT_XLSX = os.path.join(
    BASE_DIR,
    "AIKosh_ResourceCatalogMappingWithdata.gov.in_withResouceNID_with_keywords.xlsx",
)
OUTPUT_DIR = os.path.dirname(__file__)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "ai_kosh_keyword_assignments.csv")
VOCAB_PATH = os.path.join(OUTPUT_DIR, "ai_kosh_vocabulary.yaml")

KEYWORD_COL = "keywords"
# Fields combined into the match text. full_description is deliberately excluded:
# its boilerplate paragraph over-triggers rules. Catalog is high-signal.
TEXT_FIELDS = ["dataset_name", "Catalog", "short_description"]


def _compile(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


def load_vocab(path: str = VOCAB_PATH):
    """Load rules. Reject any keyword longer than 2 words (the constraint)."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    max_keywords = int(data.get("limits", {}).get("max_keywords", 8))
    rules = []
    for r in data.get("rules", []):
        clean_kw = []
        for kw in r.get("keywords", []) or []:
            kw = kw.strip()
            if len(kw.split()) > 2:
                logging.warning(
                    f"Dropping >2-word keyword '{kw}' in rule '{r.get('category')}'"
                )
                continue
            clean_kw.append(kw)
        rules.append((_compile(r["patterns"]), clean_kw))
    logging.info(f"Loaded {len(rules)} rules from {os.path.basename(path)}")
    return rules, max_keywords


def build_text(row: dict) -> str:
    parts = []
    for f in TEXT_FIELDS:
        v = row.get(f)
        if v is not None and str(v).strip().lower() not in ("", "nan", "none"):
            parts.append(str(v))
    return " | ".join(parts)


def assign_keywords(row: dict, rules, max_keywords: int) -> list[str]:
    text = build_text(row)
    seen: set[str] = set()
    out: list[str] = []
    for pattern, keywords in rules:
        if pattern.search(text):
            for kw in keywords:
                k = kw.lower()
                if k not in seen:
                    seen.add(k)
                    out.append(kw)
        if len(out) >= max_keywords:
            break
    return out[:max_keywords]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign controlled keywords to AIKosh datasets"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N rows (preview: CSV only, no xlsx)")
    args = parser.parse_args()

    rules, max_keywords = load_vocab()

    df = pd.read_excel(SOURCE_XLSX, sheet_name=SOURCE_SHEET)
    if args.limit is not None:
        df = df.head(args.limit)
    logging.info(f"Loaded {len(df)} rows from {os.path.basename(SOURCE_XLSX)}")

    assigned = [
        ", ".join(assign_keywords(row, rules, max_keywords))
        for row in df.to_dict("records")
    ]
    df[KEYWORD_COL] = assigned

    # Review CSV: id, name, sector, keywords.
    review = pd.DataFrame({
        "dataset_id": df.get("dataset_id", ""),
        "dataset_name": df.get("dataset_name", ""),
        "sector": df.get("sector", ""),
        KEYWORD_COL: assigned,
    })
    review.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    logging.info(f"Wrote review CSV -> {OUTPUT_CSV} ({len(review)} rows)")

    # Coverage summary, overall + per sector (the real quality signal).
    total = len(df)
    covered = sum(1 for k in assigned if k)
    logging.info(f"Coverage: {covered}/{total} rows tagged "
                 f"({100*covered/total:.1f}%); "
                 f"{total-covered} empty.")
    if "sector" in df.columns:
        tmp = pd.DataFrame({"sector": df["sector"].fillna("(none)"),
                            "has_kw": [bool(k) for k in assigned]})
        per = tmp.groupby("sector")["has_kw"].agg(["sum", "count"])
        per["pct"] = (100 * per["sum"] / per["count"]).round(1)
        logging.info("Per-sector coverage:\n" +
                     per.sort_values("count", ascending=False).to_string())

    if args.limit is not None:
        logging.info("Preview run (--limit) — xlsx not written.")
        return

    df.to_excel(OUTPUT_XLSX, sheet_name=SOURCE_SHEET, index=False)
    logging.info(f"Wrote annotated workbook -> {OUTPUT_XLSX}")


if __name__ == "__main__":
    main()
