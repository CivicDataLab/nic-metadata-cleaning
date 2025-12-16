import argparse
import re
from pathlib import Path

import pandas as pd
from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from transformers import pipeline



class IndicNerRecognizer(EntityRecognizer):

    SUPPORTED_ENTITIES = ["PERSON", "LOCATION", "ORGANIZATION", "MISC"]

    def __init__(self, model_name: str = "ai4bharat/IndicNER", **kwargs):
        super().__init__(
            supported_entities=self.SUPPORTED_ENTITIES,
            supported_language="hi",
            **kwargs,
        )
        self.name = "IndicNerRecognizer"
        self._pipe = pipeline(
            "token-classification",
            model=model_name,
            aggregation_strategy="simple",
        )
        self._label_map = {
            "PER": "PERSON",
            "LOC": "LOCATION",
            "ORG": "ORGANIZATION",
            "MISC": "MISC",
        }

    def load(self) -> None:
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


Hindi_RE = re.compile(r"[\u0900-\u097F]")
skip_column_keyword = [
    "date",
    "time",
    "month",
    "year",
    "s.no",
    "sno",
    "serial",
    "sr no",
    "id",
    "code",
    "status",
    "sector",
    "blockname",
    "districtname",
    "state",
    "district",
    "village",
    "pincode",
]
aadhaar_pattern = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
pan_pattern = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# India phone numbers: supports 10-digit mobiles (6-9xxxxxxxxx) with optional +91 prefix,
# and optional single separator (space/hyphen) in the middle.
phone_pattern = re.compile(
    r"(?<!\d)(?:\+?91[\s\-]?)?(?:[6-9]\d{9}|[6-9]\d{4}[\s\-]\d{5})(?!\d)"
)

# Often appears in portal responses (e.g., 'BR259782384') – treat as a potential identifier.
farmer_reg_pattern = re.compile(r"(?i)\b[a-z]{2}\d{9}\b")

KEEP = {
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "AADHAAR_NUMBER",
    "PAN_NUMBER",
    "FARMER_REGISTRATION_ID",
}



def detect_language(text: str) -> str:
    # Simple heuristic to guess whether the snippet is Hindi (default to English).
    return "hi" if Hindi_RE.search(text or "") else "en"


def regex_pii_matches(text: str) -> list[tuple[str, str, int, int]]:
    # regex for pii
    matches: list[tuple[str, str, int, int]] = []
    patterns = (
        (aadhaar_pattern, "AADHAAR_NUMBER"),
        (pan_pattern, "PAN_NUMBER"),
        (phone_pattern, "PHONE_NUMBER"),
        (farmer_reg_pattern, "FARMER_REGISTRATION_ID"),
    )
    for pattern, label in patterns:
        for m in pattern.finditer(text or ""):
            raw = (m.group(0) or "").strip()
            if not raw:
                continue
            # Canonicalize identifiers so variants (e.g., "br- 123", "BR 123") are consistent.
            if label == "FARMER_REGISTRATION_ID":
                raw = re.sub(r"[\s\-/]+", "", raw).upper()
            start, end = m.span()
            matches.append((label, raw, start, end))
    return matches


def is_phone_entity(entity_type: str) -> bool:
    return "PHONE" in (entity_type or "").upper()
     
def analyze_multi_language(analyzer: AnalyzerEngine, text: str, languages: list[str]):
    """Run the same analyzer across multiple languages and de-duplicate overlaps."""
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


def dedupe_recognizer_results(results: list[RecognizerResult]) -> list[RecognizerResult]:
    seen = set()
    unique: list[RecognizerResult] = []
    for res in results:
        key = (res.entity_type, res.start, res.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(res)
    return unique


def regex_matches_to_results(
    regex_matches: list[tuple[str, str, int, int]]
) -> list[RecognizerResult]:
    result_objects: list[RecognizerResult] = []
    for label, _, start, end in regex_matches:
        result_objects.append(
            RecognizerResult(
                entity_type=label,
                start=start,
                end=end,
                score=1.0,
                analysis_explanation=None,
            )
        )
    return result_objects



def select_detection_columns(df: pd.DataFrame) -> list[str]:
    # Heuristic to select columns likely to contain PII relevant text data.
    selected: list[str] = []
    for col in df.columns:
        lowered_name = col.lower()
        if any(keyword in lowered_name for keyword in skip_column_keyword ):
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


def build_analyzer(include_transformer_recognizer: bool = True) -> AnalyzerEngine:
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
        analyzer.registry.add_recognizer(IndicNerRecognizer())
    return analyzer


def run_demo(analyzer: AnalyzerEngine) -> None:
    text = "मेरा नाम प्रज्ञा है और मेरा फ़ोन नंबर 9783025207 है। मेरा क्रेडिट कार्ड नंबर 4481399754781234 है।"
    results = analyzer.analyze(text=text, language="hi")
    print("Analyzer results:")
    for r in results:
        print(
            f"{r.entity_type} | '{text[r.start:r.end]}' | "
            f"({r.start}, {r.end}) score={r.score:.3f}"
        )

    anonymizer = AnonymizerEngine()
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    print("\nAnonymized text:")
    print(anonymized.text)


CSV_FOLDER = Path(
    "/home/aakash/NIC/metadata/nic-metadata-cleaning/pii_test/pii-test-sample-files/pii-test-example"
)
MAX_ROWS = 250
BATCH_SIZE = 5
RUN_DEMO = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect and summarize PII content in CSV files.")
    parser.add_argument(
        "--csv-folder",
        type=Path,
        default=CSV_FOLDER,
        help="Root folder (or single CSV file) to scan. (default: %(default)s)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=MAX_ROWS,
        help="Maximum number of rows to scan from each CSV. (default: %(default)s)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="Batch size for iterating rows. (default: %(default)s)",
    )
    parser.add_argument(
        "--run-demo",
        action="store_true",
        default=RUN_DEMO,
        help="Run the built-in analyzer demo snippet before processing files.",
    )
    parser.add_argument(
        "--write-redacted-csv",
        action="store_true",
        help="Also write a copy of each CSV with detected PII redacted.",
    )
    parser.add_argument(
        "--redact-person-number-only",
        action="store_true",
        help="When redacting, only redact rows that contain PERSON plus a numeric identifier (phone/Aadhaar/PAN/Farmer ID).",
    )
    args = parser.parse_args()

    csv_folder: Path = args.csv_folder
    max_rows: int = args.max_rows
    batch_size: int = args.batch_size
    write_redacted: bool = args.write_redacted_csv
    redact_person_number_only: bool = args.redact_person_number_only
    if redact_person_number_only and not write_redacted:
        print(
            "Warning: --redact-person-number-only has no effect without --write-redacted-csv."
        )

    transformer_analyzer = build_analyzer(include_transformer_recognizer=True)
    presidio_analyzer = build_analyzer(include_transformer_recognizer=False)
    anonymizer = AnonymizerEngine() if write_redacted else None

    if args.run_demo:
        run_demo(transformer_analyzer)

    if not csv_folder.exists():
        raise SystemExit(f"Path not found: {csv_folder}")

    # Allow pointing CSV_FOLDER directly at a single CSV file (no CLI args required).
    if csv_folder.is_file() and csv_folder.suffix.lower() == ".csv":
        csv_files = [csv_folder]
    else:
        csv_files = sorted(csv_folder.rglob("*.csv"))
    if not csv_files:
        raise SystemExit(f"No CSV files discovered under {csv_folder}")

    all_detections_rows: list[dict[str, object]] = []
    all_presidio_rows: list[dict[str, object]] = []

    for idx, csv_path in enumerate(csv_files, start=1):
        print(f"\n=== [{idx}/{len(csv_files)}] Processing {csv_path} ===")

        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            print(f"Failed to read {csv_path}: {exc}")
            continue

        columns = select_detection_columns(df)
        if not columns:
            print("No eligible text columns found; skipping.")
            continue

        # Initialize per-row output columns (written back into the same CSV rows).
        bool_cols = [
            "HAS_PERSON",
            "HAS_PHONE_NUMBER",
            "HAS_EMAIL_ADDRESS",
            "HAS_AADHAAR_NUMBER",
            "HAS_PAN_NUMBER",
            "HAS_FARMER_REGISTRATION_ID",
            "PERSON_PHONE_SAME_CELL",
            "PII_DETECTED",
        ]
        for c in bool_cols:
            if c not in df.columns:
                df[c] = False
            else:
                # Ensure boolean dtype stays consistent when re-running.
                df[c] = df[c].fillna(False).astype(bool)

        for c in ["PII_TYPES", "PII_TRIGGER_COLUMNS"]:
            if c not in df.columns:
                df[c] = ""
            else:
                df[c] = df[c].fillna("").astype(str)
        if "PII_SUMMARY" not in df.columns:
            df["PII_SUMMARY"] = ""
        else:
            df["PII_SUMMARY"] = df["PII_SUMMARY"].fillna("").astype(str)

        rows_limit = min(max_rows, len(df))
        if rows_limit == 0:
            print("CSV is empty; skipping.")
            continue

        detections = 0
        samples: list[dict[str, object]] = []
        processed_rows = 0
        detections_rows: list[dict[str, object]] = []
        presidio_rows: list[dict[str, object]] = []
        redacted_updates: dict[tuple[int, str], str] = {}

        for batch_index, start in enumerate(range(0, rows_limit, batch_size), start=1):
            end = min(start + batch_size, rows_limit)
            batch_df = df.iloc[start:end]
            print(f"Batch {batch_index}: rows {start + 1}-{end}")

            for row_i, row in batch_df.iterrows():
                processed_rows += 1

                # Row-level aggregation (flag is TRUE if ANY single cell meets the rule).
                row_types: set[str] = set()
                row_trigger_cols: set[str] = set()

                row_has_person = False
                row_has_phone = False
                row_has_email = False
                row_has_aadhaar = False
                row_has_pan = False
                row_has_regid = False
                row_person_phone_same_cell = False
                row_pii_detected = False
                row_entity_details: list[str] = []
                row_entity_seen: set[tuple[str, str, str]] = set()
                row_redactions: dict[str, str] = {}

                def add_entity_detail(entity_type: str, snippet: str, column_name: str) -> None:
                    snippet = (snippet or "").strip()
                    if not snippet:
                        return
                    key = (entity_type, snippet, column_name)
                    if key in row_entity_seen:
                        return
                    row_entity_seen.add(key)
                    row_entity_details.append(f"{entity_type}: {snippet}")

                for col in columns:
                    text = str(row.get(col) or "").strip()
                    if not text:
                        continue
                    
                    language = detect_language(text)
                    try:
                        transformer_langs = [language] if language == "en" else [language, "en"]
                        transformer_results = analyze_multi_language(
                            transformer_analyzer, text, transformer_langs
                        )
                    except Exception as exc:
                        print(f"Transformer analyzer failed on '{text}': {exc}")
                        transformer_results = []

                    try:
                        # Many Presidio pattern recognizers (e.g., phone/email) are registered for English.
                        # For mixed Hindi+English transcriptions, running both improves recall.
                        presidio_langs = [language] if language == "en" else [language, "en"]
                        presidio_results = analyze_multi_language(
                            presidio_analyzer, text, presidio_langs
                        )
                    except Exception as exc:
                        print(f"Presidio analyzer failed on '{text}': {exc}")
                        presidio_results = []

                    filtered_results = [res for res in transformer_results if res.entity_type in KEEP]
                    regex_matches = regex_pii_matches(text)
                    regex_result_objects = regex_matches_to_results(regex_matches)
                    if filtered_results or regex_matches:
                        detections += 1

                    presidio_filtered = [res for res in presidio_results if res.entity_type in KEEP]

                    # Combine keep-only recognizer outputs for flag logic.
                    combined_results = filtered_results + presidio_filtered
                    person_detected = any(res.entity_type == "PERSON" for res in combined_results)

                    phone_detected = any(is_phone_entity(res.entity_type) for res in combined_results) or any(
                        label == "PHONE_NUMBER" for label, *_ in regex_matches
                    )
                    aadhaar_detected = any(label == "AADHAAR_NUMBER" for label, *_ in regex_matches)
                    pan_detected = any(label == "PAN_NUMBER" for label, *_ in regex_matches)
                    regid_detected = any(label == "FARMER_REGISTRATION_ID" for label, *_ in regex_matches)

                    person_phone_same_cell = person_detected and phone_detected
                    pii_detected_same_cell = person_phone_same_cell or aadhaar_detected or pan_detected or regid_detected
                    # Update row-level aggregates (any cell can trigger the row flag).
                    if person_detected:
                        row_has_person = True
                        row_types.add("PERSON")
                    if phone_detected:
                        row_has_phone = True
                        row_types.add("PHONE_NUMBER")
                    if any(res.entity_type == "EMAIL_ADDRESS" for res in combined_results):
                        row_has_email = True
                        row_types.add("EMAIL_ADDRESS")
                    if aadhaar_detected:
                        row_has_aadhaar = True
                        row_types.add("AADHAAR_NUMBER")
                    if pan_detected:
                        row_has_pan = True
                        row_types.add("PAN_NUMBER")
                    if regid_detected:
                        row_has_regid = True
                        row_types.add("FARMER_REGISTRATION_ID")

                    if person_phone_same_cell:
                        row_person_phone_same_cell = True

                    if pii_detected_same_cell:
                        row_pii_detected = True
                        row_trigger_cols.add(col)
                    # Persist row-level flags/types back into the dataframe (same row as input).
                    df.at[row_i, "HAS_PERSON"] = row_has_person
                    df.at[row_i, "HAS_PHONE_NUMBER"] = row_has_phone
                    df.at[row_i, "HAS_EMAIL_ADDRESS"] = row_has_email
                    df.at[row_i, "HAS_AADHAAR_NUMBER"] = row_has_aadhaar
                    df.at[row_i, "HAS_PAN_NUMBER"] = row_has_pan
                    df.at[row_i, "HAS_FARMER_REGISTRATION_ID"] = row_has_regid
                    df.at[row_i, "PERSON_PHONE_SAME_CELL"] = row_person_phone_same_cell
                    df.at[row_i, "PII_DETECTED"] = row_pii_detected
                    df.at[row_i, "PII_TYPES"] = ";".join(sorted(row_types))
                    df.at[row_i, "PII_TRIGGER_COLUMNS"] = ";".join(sorted(row_trigger_cols))

                    for res in filtered_results:
                        snippet = text[res.start : res.end]
                        add_entity_detail(res.entity_type, snippet, col)
                        detections_rows.append(
                            {
                                "pii_flag": res.entity_type,
                                "entity": snippet,
                                "column": col,
                                "score": res.score,
                                "person_phone_same_cell": person_phone_same_cell,
                            }
                        )

                    for label, snippet, _, _ in regex_matches:
                        add_entity_detail(label, snippet, col)
                        detections_rows.append(
                            {
                                "pii_flag": label,
                                "entity": snippet,
                                "column": col,
                                "score": 1.0,
                                "person_phone_same_cell": person_phone_same_cell,
                            }
                        )

                    for res in presidio_filtered:
                        snippet = text[res.start : res.end]
                        add_entity_detail(res.entity_type, snippet, col)
                        presidio_rows.append(
                            {
                                "pii_flag": res.entity_type,
                                "entity": snippet,
                                "column": col,
                                "score": res.score,
                                "person_phone_same_cell": person_phone_same_cell,
                            }
                        )

                    if filtered_results and len(samples) < 5:
                        snippets = [
                            f"{res.entity_type}:{text[res.start:res.end]}"
                            for res in filtered_results
                        ]
                        samples.append(
                            {"column": col, "text": text, "detections": snippets}
                        )

                    if write_redacted:
                        redacted_text = text
                        redaction_results = combined_results + regex_result_objects
                        if redaction_results and anonymizer is not None:
                            try:
                                deduped = dedupe_recognizer_results(redaction_results)
                                if deduped:
                                    anonymized = anonymizer.anonymize(
                                        text=text,
                                        analyzer_results=deduped,
                                    )
                                    redacted_text = anonymized.text
                            except Exception as exc:
                                print(
                                    f"Failed to redact value in {csv_path.name} -> column '{col}': {exc}"
                                )
                        row_redactions[col] = redacted_text

                summary = ""
                if row_entity_details:
                    summary = f"Number of PII entities: {len(row_entity_details)}, " + ", ".join(
                        row_entity_details
                    )
                df.at[row_i, "PII_SUMMARY"] = summary
                if write_redacted:
                    row_has_number = row_has_phone or row_has_aadhaar or row_has_pan or row_has_regid
                    row_person_with_number = row_has_person and row_has_number
                    should_store_redactions = not redact_person_number_only or row_person_with_number
                    if should_store_redactions:
                        for col, value in row_redactions.items():
                            redacted_updates[(row_i, col)] = value

        # Write annotated CSV (same rows + added PII flags/types).
        annotated_out = csv_path.with_name(f"{csv_path.stem}_pii_annotated.csv")
        df.to_csv(annotated_out, index=False)
        print(f"Annotated CSV written to {annotated_out}")

        if write_redacted:
            redacted_df = df.copy(deep=True)
            for (row_idx, column_name), value in redacted_updates.items():
                redacted_df.at[row_idx, column_name] = value
            drop_flags = [
                c
                for c in bool_cols
                if c not in {"HAS_PERSON", "HAS_PHONE_NUMBER"} and c in redacted_df.columns
            ]
            if drop_flags:
                redacted_df = redacted_df.drop(columns=drop_flags)
            redacted_out = csv_path.with_name(f"{csv_path.stem}_redacted.csv")
            redacted_df.to_csv(redacted_out, index=False)
            print(f"Redacted CSV written to {redacted_out}")

        print(
            f"Finished {csv_path} | rows scanned: {processed_rows} | "
            f"columns: {columns} | detections: {detections}"
        )
        if detections_rows:
            all_detections_rows.extend(
                [
                    {
                        "csv_file": csv_path.name,
                        "pii_flag": row["pii_flag"],
                        "entity": row["entity"],
                        "column": row["column"],
                        "score": row["score"],
                        "person_phone_same_cell": row["person_phone_same_cell"],
                    }
                    for row in detections_rows
                ]
            )
        else:
            print("No entities detected in sampled rows.")

        if presidio_rows:
            all_presidio_rows.extend(
                [
                    {
                        "csv_file": csv_path.name,
                        "pii_flag": row["pii_flag"],
                        "entity": row["entity"],
                        "column": row["column"],
                        "score": row["score"],
                        "person_phone_same_cell": row["person_phone_same_cell"],
                    }
                    for row in presidio_rows
                ]
            )

        if samples:
            print("Sample detections:")
            for sample in samples:
                print(sample)

    if all_detections_rows:
        combined_output = csv_folder / "pii_detections_combined.csv"
        combined_df = pd.DataFrame(all_detections_rows)[
            ["csv_file", "column", "pii_flag", "entity", "score", "person_phone_same_cell"]
        ]
        combined_df.to_csv(combined_output, index=False)
        print(f"\nCombined detections written to {combined_output}")
    else:
        print("\nNo detections captured across all CSV files.")

    if all_presidio_rows:
        presidio_output = csv_folder / "pii_presidio_detections.csv"
        presidio_df = pd.DataFrame(all_presidio_rows)[
            ["csv_file", "column", "pii_flag", "entity", "score", "person_phone_same_cell"]
        ]
        presidio_df.to_csv(presidio_output, index=False)
        print(f"Presidio analyzer detections written to {presidio_output}")
    else:
        print("No Presidio analyzer detections captured.")
