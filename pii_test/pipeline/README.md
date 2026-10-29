# PII pipeline (`pipeline/`)

The PII test scripts, merged into eight files. They replace 15 files (about 9,300 lines) in
`pii_test/` with 6,351 lines here, and import nothing from the old files.

**Status (2026-10-29): built and checked against the old scripts, not signed off.** The old
scripts in `pii_test/` are unchanged and still produced every result of record. `pii_service/`
still imports the old modules, so those stay until it is switched over.

How detection, Tier 1 and Tier 3 work is in [../README.md](../README.md); this file covers
only what is in this folder and how to run it.

## Files

| File | What it does | Replaces |
|---|---|---|
| `run.py` | One command for every run: `run.py RUN STEP`, e.g. `run.py lot3 scan` | `run_lot2_pii.py`, `run_lot3_pii.py`, `run_kcc_scan.py`, `run_kcc_full_scan.py`, `pii_classify_pipeline.py`, `kcc_public_contact_override.py` |
| `scan.py` | Reads a table, picks the columns worth scanning, finds PII in them (Presidio, two NER models, regex) | `pii_utils.py` (models, column selection, overlap resolution), the local-file scan of `run_pii_s3.py` |
| `filters.py` | Header rules, regex detectors, the filters that drop false hits, the dataset flag. No models | `pii_filters.py`, the header and regex rules of `pii_utils.py` |
| `classify.py` | Tier 1: labels each (dataset, column) `false_positive`, `permissible`, `present` or `undecided` | `pii_classify.py` (without its DB and snapshot code) |
| `judge.py` | Tier 3: asks the local Qwen judge about the columns Tier 1 left `undecided` | `pii_tier3.py` (without its DB code) |
| `redact.py` | Redacted copies of the columns classified `present` | the local-folder part of `generate_redacted.py` |
| `report.py` | The 2026-10-12 final review, the test timestamps, the Excel workbooks | `build_final_review.py`, `export_pii_test_timestamps.py`, `export_results_excel.py` |
| `selftest.py` | 247 self-checks: 132 for the filters, 65 for Tier 1, 50 for Tier 3 | the self-tests in `pii_filters.py`, `pii_classify.py --test`, `pii_tier3.py --test` |

## Running

```bash
.venv/bin/python pii_test/pipeline/run.py RUN STEP [options]
```

| RUN | What it scans | Steps |
|---|---|---|
| `lot2` | the files of `dublin_core_remaining` (`data/lot2_*`) | `stage`, `scan`, `repair`, `classify`, `result`, `redact` |
| `lot3` | the files of `dublin_core_lot3` (`data/lot3_downloads`, `data/lot3_s3_downloads`) | `stage`, `scan`, `repair`, `classify`, `result`, `redact` |
| `kcc` | the KCC call-centre transcripts, first 250 rows of each file | `stage`, `scan`, `classify`, `override`, `redact` |
| `kccfull` | the same transcripts, every row | `stage`, `scan`, `merge` |
| `folder` | any folder of tables, given with `--path` | `scan`, `classify`, `redact` |

| STEP | What it does |
|---|---|
| `stage` | builds the folder the scan reads (symlinks under the right extension, JSON written out as CSV) |
| `scan` | scans it, one shard or state at a time; a rerun skips finished ones unless `--force` |
| `repair` | restages the files the scan could not parse, padded to one width, in a shard of their own |
| `classify` | Tier 1, then Tier 3 on what Tier 1 left `undecided` |
| `result` | one row per catalogue row with its final class |
| `override` | stopgap: moves KCC columns whose phone numbers are all public contacts from `present` to `permissible` |
| `merge` | puts the `kccfull` scan workers' summaries together |
| `redact` | writes redacted copies of the columns classified `present` |

**Where it writes.** A lot or KCC run writes under `--out`, laid out like the repo. `--out`
defaults to `pii_test/pipeline/out`, so a test run touches nothing real; pass the repo root to
write the real files. The downloads, `metadata.db` and the KCC transcripts are always read from
the repo and never written. A `folder` run writes its detections beside the data in `--path`
and everything else to `--out-dir`.

Examples:

```bash
.venv/bin/python pii_test/pipeline/run.py lot3 stage
.venv/bin/python pii_test/pipeline/run.py lot3 scan --gpu
.venv/bin/python pii_test/pipeline/run.py lot3 repair      # then scan again, if it moved any
.venv/bin/python pii_test/pipeline/run.py lot3 classify
.venv/bin/python pii_test/pipeline/run.py lot3 result
.venv/bin/python pii_test/pipeline/run.py kccfull scan --gpu --worker w1   # and w2, w3 beside it
.venv/bin/python pii_test/pipeline/run.py folder scan --path DATA_DIR --out-dir OUT
.venv/bin/python pii_test/pipeline/run.py folder classify --path DATA_DIR --out-dir OUT --no-llm
```

Options, by step:

| Step | Option | Meaning |
|---|---|---|
| all | `--out` | root the lot and KCC runs write under (default `pii_test/pipeline/out`) |
| folder | `--path`, `--out-dir` | the folder to scan; where the summary, log and classification go |
| scan | `--gpu` | NER models on the GPU (about 7x faster per file); off by default because the judge holds the card |
| | `--workers N` | scan or redaction processes, about 3.3 GB RAM each; 3 is this box's ceiling |
| | `--max-rows N` | rows scanned per file (default 250; `kccfull` reads every row) |
| | `--ner-batch-size N` | NER batch size (default 64) |
| | `--folders A,B` | only these shards or states |
| | `--force` | rescan folders already in the summary |
| | `--worker w1` | `kccfull`: this worker's name, for its summary and log |
| | `--max-files N` | `folder`: scan only the first N files, for a trial |
| classify | `--no-llm` | stop after Tier 1; `undecided` pairs stay `undecided` |
| | `--no-catalog` | lots: classify without the catalogue titles, as a plain folder run would |
| | `--per-folder` | Tier 3 judges each (folder, column, header row) once; on for `kcc` |
| | `--judge-workers N` | pairs sent to the judge at once (default 8) |
| | `--limit N` | Tier 3 judges only the first N pairs (dry run) |
| | `--endpoint`, `--model`, `--max-tokens`, `--presence-penalty` | the judge server and its settings |
| override | `--dry-run` | report, write nothing |
| redact | `--redact-dir`, `--redact-classes`, `--redact-max-rows`, `--redact-copy-clean` | where the copies go; which classes to redact (default `present`); stop each file after N rows (0 = all); also copy the files that needed no redaction |

Reports and self-tests:

```bash
.venv/bin/python pii_test/pipeline/report.py review
.venv/bin/python pii_test/pipeline/report.py stamps
.venv/bin/python pii_test/pipeline/report.py excel --lot1-snapshot PATH/lot1_snapshot.parquet
.venv/bin/python pii_test/pipeline/selftest.py      # no GPU, no server, no files written
```

`report.py` reads the real folders and writes under `--out` (same default). `--final` points
`stamps` and `excel` at another `final_review/` folder.

## Old command to new command

| Old command | New command |
|---|---|
| `run_lot3_pii.py stage` / `scan --gpu` / `repair` / `classify` / `result` | `pipeline/run.py lot3 stage` / `scan --gpu` / `repair` / `classify` / `result` |
| `run_lot2_pii.py ...` | `pipeline/run.py lot2 ...` |
| `run_kcc_scan.py --gpu` | `pipeline/run.py kcc scan --gpu` |
| `run_kcc_full_scan.py stage` / `scan --gpu --worker w1` / `merge` | `pipeline/run.py kccfull stage` / `scan --gpu --worker w1` / `merge` |
| `kcc_public_contact_override.py --run-dir ... --scan-dir ... --summary ...` | `pipeline/run.py kcc override` |
| `pii_classify_pipeline.py --path DIR --out-dir OUT` | `pipeline/run.py folder scan --path DIR --out-dir OUT`, then `folder classify` with the same two options |
| `pii_classify_pipeline.py --csv DIR --summary S --out-dir OUT` | `pipeline/run.py folder classify --path DIR --out-dir OUT` (the summary is `OUT/scan_summary.csv`) |
| `... --redact` / `generate_redacted.py --run-dir ...` | `pipeline/run.py RUN redact` |
| `build_final_review.py`, `export_pii_test_timestamps.py`, `export_results_excel.py --lot1-snapshot F` | `pipeline/report.py review`, `stamps`, `excel --lot1-snapshot F` |
| `pii_filters.py`, `pii_classify.py --test`, `pii_tier3.py --test` | `pipeline/selftest.py` |

The old scripts' DB and S3 modes (`--db ... --write`, `run_pii_s3.py --batch`, the S3 mode of
`generate_redacted.py`) have no counterpart here: this pipeline writes CSV only.

## How it was checked

Each step was run beside the old script on the same input and the outputs compared.

| Part | Result |
|---|---|
| `filters.py` | 0 differences on real lot 2 and 3 data: 291,523 detections, 21,471 headers, 975,726 cells |
| `scan.py` | detections and summary byte-identical on a CPU test corpus, both directly and through `run.py folder scan`. A lot 3 shard scan writes its summary per shard and a rerun skips finished shards |
| Tier 1 | rows identical on both lots |
| `run.py classify` | all 7 output files identical to the old `run_lot2_pii.py` / `run_lot3_pii.py classify`, both lots. The judge was replayed from a stored `tier3_judged.jsonl` |
| `run.py result` | byte-identical to the real `lot2_pii_result.csv` and `lot3_pii_result.csv` |
| `run.py kcc override` | all 7 files identical; 454 columns moved, as in the real run |
| `stage`, `repair` | identical for both lots on test files, including lot 2's add-only second stage |
| `kccfull stage`, `merge` | same links as the real `data/kcc_full_stage` (1,890 links in 509 folders); merge identical |
| `redact.py` | identical to `generate_redacted.py` (191 cells in 3 files) |
| `report.py` | `review` and `stamps` byte-identical to the real `final_review/final_results.csv`, `kept_columns.csv` and both `pii_test_timestamps_lots_2_3.csv`. The `excel` workbooks were not compared byte for byte (they hold timestamps) |
| `selftest.py` | all 247 checks pass |

**Not checked:** `--workers` above 1 (this box had about 4 GB free), and a GPU scan against the
old one.

## What behaves differently

- `classify` sends 8 pairs to the judge at once by default (`--judge-workers`); the old folder
  and KCC runs sent one at a time, so the judge server carries more load.
- Every `classify` keeps `tier3_judged.jsonl`, so an interrupted run resumes where it stopped.
- `kcc classify` also writes `pii_result.csv`.
- Pool and folder runs log in a new format.

## Watch out

- **Most lot 2 and lot 3 source files are now on S3 only.** Most staged symlinks dangle (lot 3
  shard `t00`: 789 of 1,199; lot 2 shard `s000`: 1,138 of 1,201), so a lot 2 or 3 scan cannot
  be redone from this box, and `classify` cannot reproduce the 8 Oct outputs exactly: Tier 1
  reads header rows from the source files. The old scripts give the same differences.
- **`lot3 stage` deals every shard out again.** Never run it on a scanned lot.
- **Don't pass the repo root as `--out` for `classify`** unless you mean to replace the real
  outputs. It rewrites the real `classification/` files: the KCC public-contact override is
  lost, and the 2026-10-12 review decisions are not carried forward.
- **Redaction reads CSV as UTF-8 only.** Windows-1252 files fail; the old
  `generate_redacted.py` has the same bug.
- **`out/` is gitignored and holds PII.** The test runs left copies of the review files and the
  `results_excel/` workbooks there. Keep it on this server.
