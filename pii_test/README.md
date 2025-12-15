
# **PII Detection Pipeline – Prototype Overview**


## **1. Input Data**

* The script accepts either:

* Each CSV must include at least one column containing textual transcriptions or mixed-language content.

---

## **2. Text Processing Workflow**

1. **Iterate through each row** of the CSV to process text fields.
2. **Language detection**:

   * The pipeline checks for Devanagari script and classifies text as Hindi (`hi`) or English (`en`).
   * For mixed-language content, both are applied (`[hi, en]`).
3. **Presidio Analyzer** runs with these models:

   * Default recognizers for PII entities such as:

     * `PHONE_NUMBER`
     * `EMAIL_ADDRESS`
     * `PERSON`
     * `LOCATION`
   * Extended to support multilingual detection (Hindi + English).

---

## **3. Regex-Based Enhancements**

In addition to Presidio’s entities, regex detection is used for:

* **Indian mobile numbers**: e.g., `^[6-9]\d{9}$`
* **Portal registration IDs**: alphanumeric codes like `BR259782384`

These supplement the analyzer results, ensuring entities embedded in hybrid text blocks are not missed.

---

## **4. Entity Aggregation and Row-Level Flagging**

For each text row:

* Extracted entities are appended to a `pii_rows` list with:

  * Dataset name
  * Column name
  * Detected value
  * Entity label
* A **row-level flag** (`person_phone_same_row`) is set to `True` if both a `PERSON` and a `PHONE_NUMBER` appear in the same record.

---

## **5. Output**

### 5.1 Annotated CSV (primary output)
For each input CSV, the script writes an annotated file alongside it:

- `<original_stem>_pii_annotated.csv`

This file contains the **original columns** plus these additional columns:

- `HAS_PERSON`
- `HAS_PHONE_NUMBER`
- `HAS_EMAIL_ADDRESS`
- `HAS_AADHAAR_NUMBER`
- `HAS_PAN_NUMBER`
- `HAS_FARMER_REGISTRATION_ID`
- `PERSON_PHONE_SAME_CELL` (row-level: true if any cell had person+phone together)
- `PII_DETECTED` (row-level: true if any cell triggered the PII rule)
- `PII_TYPES` (semicolon-separated entity types detected in the row)
- `PII_TRIGGER_COLUMNS` (semicolon-separated column names that triggered/contained PII)

### 5.2 Combined detections (entity-level logs)
Across all processed CSV files, the script also produces:

- `pii_detections_combined.csv`

Columns:
- `csv_file`, `column`, `pii_flag`, `entity`, `score`, `person_phone_same_cell`

### 5.3 Presidio detections (entity-level logs)
Additionally:

- `pii_presidio_detections.csv`

Columns:
- `csv_file`, `column`, `pii_flag`, `entity`, `score`, `person_phone_same_cell`


## **6. Example Use Case**

When analyzing **Kisan Call Center data**, a row such as:

```
"किसान रजिस्ट्रेशन आईडी BR259782384 है, संपर्क करें 9876543210"
```

will output:

| Dataset | Column        | Entity       | Value       | Language |
| ------- | ------------- | ------------ | ----------- | -------- |
| 2023_Q4 | transcription | PHONE_NUMBER | 9876543210  | hi       |
| 2023_Q4 | transcription | REG_ID       | BR259782384 | hi       |

---

## **7. Design Principles**

* No CLI arguments required (pure script execution).
* Modular structure for quick replacement of language models or regex patterns.
* Works seamlessly on bilingual or portal-extracted datasets.
* Built for **offline runs** and **iterative testing** without changing the CLI interface.

---

Would you like me to add a small diagram (data flow visual) and include it in this `.md` file? It can make the process clearer if you plan to show this to others.
