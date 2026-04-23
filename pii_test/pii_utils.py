"""
Shared PII detection utilities.
Extracted from pii-pipeline-prototype.py for reuse across scripts.
"""

import re

import pandas as pd
from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from transformers import pipeline as hf_pipeline


class IndicNerRecognizer(EntityRecognizer):

    SUPPORTED_ENTITIES = ["PERSON", "LOCATION", "ORGANIZATION", "MISC"]

    def __init__(self, model_name="ai4bharat/IndicNER", device="cpu", **kwargs):
        super().__init__(
            supported_entities=self.SUPPORTED_ENTITIES,
            supported_language="hi",
            **kwargs,
        )
        self.name = "IndicNerRecognizer"
        self._pipe = hf_pipeline(
            "token-classification",
            model=model_name,
            aggregation_strategy="simple",
            device=device,
        )
        self._label_map = {
            "PER": "PERSON",
            "LOC": "LOCATION",
            "ORG": "ORGANIZATION",
            "MISC": "MISC",
        }

    def load(self):
        pass

    def supported_entities(self):
        return self.SUPPORTED_ENTITIES

    def analyze(self, text, entities, nlp_artifacts=None):
        if not text:
            return []

        outputs = self._pipe(text)
        results = []

        for out in outputs:
            label = out.get("entity_group") or out.get("entity")
            if label not in self._label_map:
                continue

            entity_type = self._label_map[label]
            start = int(out["start"])
            end = int(out["end"])
            score = float(out.get("score", 0.0))

            results.append(
                RecognizerResult(
                    entity_type=entity_type,
                    start=start,
                    end=end,
                    score=score,
                    analysis_explanation=None,
                )
            )

        return results


# --- Constants ---

Hindi_RE = re.compile(r"[\u0900-\u097F]")

skip_column_keyword = [
    "date", "time", "month", "year", "s.no", "sno", "serial", "sr no",
    "id", "code", "status", "sector", "blockname", "districtname",
    "state", "district", "village", "pincode",
]

aadhaar_pattern = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
pan_pattern = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
phone_pattern = re.compile(
    r"(?<!\d)(?:\+?91[\s\-]?)?(?:[6-9]\d{9}|[6-9]\d{4}[\s\-]\d{5})(?!\d)"
)
farmer_reg_pattern = re.compile(r"(?i)\b[a-z]{2}\d{9}\b")

KEEP = {
    "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS",
    "AADHAAR_NUMBER", "PAN_NUMBER", "FARMER_REGISTRATION_ID",
}


# --- Functions ---

def detect_language(text):
    return "hi" if Hindi_RE.search(text or "") else "en"


def regex_pii_matches(text):
    matches = []
    patterns = (
        (aadhaar_pattern, "AADHAAR_NUMBER"),
        (pan_pattern, "PAN_NUMBER"),
        (phone_pattern, "PHONE_NUMBER"),
        (farmer_reg_pattern, "FARMER_REGISTRATION_ID"),
    )
    for pat, label in patterns:
        for m in pat.finditer(text or ""):
            raw = (m.group(0) or "").strip()
            if not raw:
                continue
            if label == "FARMER_REGISTRATION_ID":
                raw = re.sub(r"[\s\-/]+", "", raw).upper()
            start, end = m.span()
            matches.append((label, raw, start, end))
    return matches


def is_phone_entity(entity_type):
    return "PHONE" in (entity_type or "").upper()


def regex_matches_to_results(regex_matches):
    """Convert regex match tuples to RecognizerResult objects."""
    results = []
    for label, _, start, end in regex_matches:
        results.append(
            RecognizerResult(
                entity_type=label,
                start=start,
                end=end,
                score=1.0,
                analysis_explanation=None,
            )
        )
    return results


def analyze_multi_language(analyzer, text, languages):
    """Run the analyzer across multiple languages and de-duplicate overlaps."""
    all_results = []
    for lang in languages:
        all_results.extend(analyzer.analyze(text=text, language=lang))
    seen = set()
    unique = []
    for r in all_results:
        key = (r.entity_type, r.start, r.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def select_detection_columns(df):
    """Select columns likely to contain PII-relevant text data."""
    selected = []
    for col in df.columns:
        lowered_name = col.lower()
        if any(kw in lowered_name for kw in skip_column_keyword):
            continue

        series = df[col]
        sample = series.dropna().head(50)
        if sample.empty:
            continue

        sample_str = sample.astype(str).str.strip()
        if sample_str.empty:
            continue

        if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
            continue

        lowered_values = sample_str.str.lower()
        bool_tokens = {"true", "false", "yes", "no", "y", "n", "0", "1"}
        if lowered_values.isin(bool_tokens).mean() > 0.9:
            continue

        numeric_ratio = pd.to_numeric(sample_str, errors="coerce").notna().mean()
        if numeric_ratio > 0.9:
            continue

        datetime_ratio = pd.to_datetime(
            sample_str, errors="coerce", infer_datetime_format=True
        ).notna().mean()
        if datetime_ratio > 0.9:
            continue

        selected.append(col)

    return selected


def build_analyzer(include_transformer_recognizer=True, device="cpu"):
    """Build a Presidio AnalyzerEngine with Spacy + optional IndicNER."""
    models = [
        {"lang_code": "en", "model_name": "en_core_web_sm"},
        {"lang_code": "hi", "model_name": "xx_sent_ud_sm"},
    ]
    nlp_engine = SpacyNlpEngine(models)
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en", "hi"],
    )
    if include_transformer_recognizer:
        analyzer.registry.add_recognizer(IndicNerRecognizer(device=device))
    return analyzer
