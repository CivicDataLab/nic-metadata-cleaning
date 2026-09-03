# nic-metadata-cleaning

Tooling to clean, standardise and enrich the dataset metadata published on
[data.gov.in](https://www.data.gov.in), India's Open Government Data platform, along with
the AIKosh catalogue.

Raw metadata from the portal is messy: titles carry information that should be in fields,
coverage is undeclared, the same dataset series is split into thousands of separate
entries, and vocabularies are non-standard. This repo fixes that, one concern at a time.

---

## What it does


### Maps metadata to Dublin Core and DCAT v3

Takes the portal's own field names and maps them onto standard vocabularies. Dates are
normalised along the way. The Dublin Core mapping is a real transformation into new
tables; the DCAT v3 layer sits on top as a view that renames each column to its DCAT term,
so both vocabularies are available without duplicating the data.

`transformation/metdata_transform_dublin.py`, `transformation/build_dcat_mapping.py`

### Enriches metadata with an LLM

Generates cleaner titles, descriptions and themes for datasets that have poor or missing
ones, using the OpenAI Batch API. Runs at both individual dataset and collection level.

`transformation/llm_batch_classifier.py`, `transformation/llm_collection_classifier.py`

### Groups datasets into collections and merges them

The portal publishes one dataset per state, per district, per year — the same series
fragmented into thousands of entries. This detects those families by fuzzy-matching
normalised titles, then works out how each family can be recombined: some can be merged
byte-for-byte, some need a state or year column added first, and some have headers that
changed over time and have to be split into eras or reunited into a single series.

`transformation/dataset_merge.py`, and the merge-method scripts in `transformation/utils/`

### Works out spatial coverage

Determines which states, districts and sub-districts a dataset actually covers. Two
sources of evidence: the dataset title, and the file contents themselves — columns whose
headers name a geography contribute their distinct values, and a wide file with one column
per state contributes its headers.

`transformation/temporal/Spatial_script.py`,
`transformation/utils/extract_coverage_from_title.py`

### Works out temporal coverage

Derives the period a dataset covers — start and end dates — again from both titles and
file contents. Handles Indian fiscal years (April–March), and records coverage at whatever
precision the source supports, whether that's a day, a month or a year.

`transformation/temporal/Temporal_script.py`,
`transformation/utils/extract_temporal_from_title.py`

### Scores High Value Datasets

Rates each dataset's candidacy as a High Value Dataset, and separately checks whether it is
actually being refreshed at the cadence it publicly declares. Read-only: it produces a CSV
for humans to act on, and never flips the portal's own HVD flag itself.

`hvd_scoring/hvd_score.py` — see [`hvd_scoring/README.md`](hvd_scoring/README.md)

### Detects PII

Scans downloaded dataset files for personal information before publication. Built on
Presidio, extended for Indian identifiers — mobile numbers, PAN, portal registration IDs —
and for Hindi/English mixed-script text.

`pii_test/` — see [`pii_test/README.md`](pii_test/README.md)

### Publishes the result

Exports the finished metadata to S3 as Parquet snapshots, to Excel for review, and uploads
the dataset files themselves.

`transformation/update_metadata_s3.py`, `transformation/upload_datasets_s3.py`,
`transformation/utils/export_dublin_metadata.py`

---

## Getting started

Python 3.12+.

```bash
uv sync                      # pyproject.toml is the dependency source of truth
```

Everything runs against a local DuckDB database, `transformation/metadata.db`, which is not
in the repo. Build it with `transformation/import_csv.py` (imports the source ministry
spreadsheet) or restore the latest S3 snapshot with
`transformation/utils/update_local_db.py`.


## Further reading

- [`transformation/readme.md`](transformation/readme.md) — pipeline notes
- [`hvd_scoring/README.md`](hvd_scoring/README.md) — the HVD scoring model
- [`pii_test/README.md`](pii_test/README.md) — the PII pipeline
- [`notebooks/metadata_transformation_architecture.md`](notebooks/metadata_transformation_architecture.md) — architecture write-up
