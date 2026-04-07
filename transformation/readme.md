# Transformation Pipeline

## Pipeline Order

```
import_csv.py
    → metdata_transform_dublin.py
    → utils/create_metadata_enhancement.py
    → llm_batch_classifier.py
    → update_metadata_s3.py
```

---

## Files

### Data Ingestion
**`import_csv.py`**
Reads the source Excel file and loads it into `raw_metadata` table in `metadata.db`. Adds a `batch` column (groups of 5000 rows).

### Transformation
**`metdata_transform_dublin.py`**
Maps OGD fields to Dublin Core / DCAT v3 names. Converts date formats. Writes to `dublin_core_metadata` table.

**`utils/create_metadata_enhancement.py`**
Creates `metadata_enhancement` table — a focused subset of `raw_metadata` fields used for LLM enrichment.

### LLM Enrichment
**`llm_batch_classifier.py`**
Sends metadata to `gpt-4.1-nano` via OpenAI Batch API to generate titles, descriptions, keywords, themes, and HVD classification. Results saved to `llm_keyword_results` table and CSV.

```bash
python llm_batch_classifier.py --batch 1 --chunk-size 500
python llm_batch_classifier.py --poll <batch_id>   # resume a submitted job
python llm_batch_classifier.py --limit 10           # test run
```

### S3 Sync
**`update_metadata_s3.py`**
Exports all tables from `metadata.db` as Parquet files and uploads to `s3://nic-ogdp-datasets/metadata/<timestamp>/`.

**`utils/update_local_db.py`**
Downloads the latest Parquet snapshot from S3 and restores it into the local `metadata.db`.

### Utilities
**`duckdb_demo.py`**
Exports `dublin_core_metadata` table to `dublin_core_metadata.csv`.

**`text_generation/token_usage.py`**
Calculates token usage and cost from batch output JSONL files.

```bash
python text_generation/token_usage.py                         # all batch output files
python text_generation/token_usage.py batch_output_xyz.jsonl  # single file
```

---

## Database — `metadata.db`

| Table | Description |
|---|---|
| `raw_metadata` | Source data from Excel |
| `dublin_core_metadata` | Dublin Core mapped fields |
| `metadata_enhancement` | Subset used for LLM input |
| `llm_keyword_results` | LLM-generated enriched metadata |
