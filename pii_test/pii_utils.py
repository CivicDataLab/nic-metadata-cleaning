"""
Shared PII detection utilities.
Extracted from pii-pipeline-prototype.py for reuse across scripts.
"""

import logging
import re

import pandas as pd
import spacy
from presidio_analyzer import (
    AnalyzerEngine,
    BatchAnalyzerEngine,
    EntityRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine, NerModelConfiguration
from transformers import pipeline as hf_pipeline

logger = logging.getLogger(__name__)


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


def keep_result(res: RecognizerResult, text: str) -> bool:
    if res.entity_type not in KEEP:
        return False
    if res.entity_type == "PERSON" and len(text[res.start:res.end].strip()) < 3:
        return False
    return True


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
            sample_str, errors="coerce", format="mixed").notna().mean()
        if datetime_ratio > 0.9:
            continue

        selected.append(col)

    return selected


def build_analyzer(include_transformer_recognizer=True, device="cpu"):
    """Build a Presidio AnalyzerEngine with Spacy + optional IndicNER.

    Returns: (analyzer, indic_recognizer | None)
    When device != "cpu", spaCy GPU is activated so en_core_web_trf runs on GPU.
    """
    if device != "cpu":
        try:
            spacy.require_gpu()
            logger.info("spaCy GPU activated for transformer model.")
        except Exception as exc:
            logger.warning("spacy.require_gpu() failed (%s); spaCy will fall back to CPU.", exc)

    models = [
        {"lang_code": "en", "model_name": "en_core_web_trf"},
        {"lang_code": "hi", "model_name": "xx_sent_ud_sm"},
    ]
    ner_config = NerModelConfiguration(labels_to_ignore=["CARDINAL"])
    nlp_engine = SpacyNlpEngine(models, ner_model_configuration=ner_config)
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en", "hi"],
    )
    indic_recognizer = None
    if include_transformer_recognizer:
        indic_recognizer = IndicNerRecognizer(device=device)
        analyzer.registry.add_recognizer(indic_recognizer)
    return analyzer, indic_recognizer


def batch_analyze_cells(
    cell_info,
    analyzer,
    indic_recognizer,
    spacy_batch_size=32,
    ner_batch_size=32,
):
    """Run batched IndicNER + Presidio/spaCy on all cells at once.

    Parameters
    ----------
    cell_info : list[tuple[Any, str, str, str]]
        (row_key, col, text, language) tuples; language is "hi" or "en".
    analyzer : AnalyzerEngine
    indic_recognizer : IndicNerRecognizer | None
    spacy_batch_size : int
        Batch size for BatchAnalyzerEngine (spaCy nlp.pipe).
    ner_batch_size : int
        Batch size for the IndicNER HF pipeline.

    Returns
    -------
    dict[(row_key, col), list[RecognizerResult]]
        All deduped detections per cell from spaCy + IndicNER.
    """
    cache: dict = {}
    if not cell_info:
        return cache

    hi_cells = [(rk, c, t) for rk, c, t, lang in cell_info if lang == "hi"]
    en_cells = [(rk, c, t) for rk, c, t, lang in cell_info if lang == "en"]

    # 1. Batched IndicNER on Hindi texts (single HF pipeline call).
    if hi_cells and indic_recognizer is not None:
        ner_texts = [t for _, _, t in hi_cells]
        indic_recognizer._pipe.tokenizer.model_max_length = 512
        all_outputs = indic_recognizer._pipe(ner_texts, batch_size=ner_batch_size)
        for (rk, col, _t), outputs in zip(hi_cells, all_outputs):
            results = []
            for out in outputs:
                label = out.get("entity_group") or out.get("entity")
                if label not in indic_recognizer._label_map:
                    continue
                results.append(
                    RecognizerResult(
                        entity_type=indic_recognizer._label_map[label],
                        start=int(out["start"]),
                        end=int(out["end"]),
                        score=float(out.get("score", 0.0)),
                        analysis_explanation=None,
                    )
                )
            cache.setdefault((rk, col), []).extend(results)

    # 2. Batched spaCy via Presidio's BatchAnalyzerEngine. Hindi cells are run
    # twice (hi + en) so English-registered pattern recognizers still fire.
    batch_engine = BatchAnalyzerEngine(analyzer_engine=analyzer)
    for cells, lang in [(en_cells, "en"), (hi_cells, "hi"), (hi_cells, "en")]:
        if not cells:
            continue
        texts = [t for _, _, t in cells]
        results_list = batch_engine.analyze_iterator(
            texts, language=lang, batch_size=spacy_batch_size
        )
        for (rk, col, _t), cell_results in zip(cells, results_list):
            cache.setdefault((rk, col), []).extend(cell_results)

    # 3. Dedup per cell on (entity_type, start, end).
    for key, items in cache.items():
        seen = set()
        deduped = []
        for r in items:
            k = (r.entity_type, r.start, r.end)
            if k not in seen:
                seen.add(k)
                deduped.append(r)
        cache[key] = deduped

    return cache
