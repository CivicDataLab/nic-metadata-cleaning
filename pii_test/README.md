# PII test

This folder checks datasets from data.gov.in for personal data: names, phone numbers, email
addresses, Aadhaar, PAN and PM-KISAN farmer registration numbers. It has two parts:

- **The script pipeline** runs over the project's own corpus (lots 1, 2 and 3 and the Kisan
  Call Centre transcripts). It scans each file, classifies every flagged column and can write
  redacted copies.
- **The PII API** (`pii_service/`) lets anyone upload a CSV, JSON, Excel or PDF file and get the
  same answer back. Every run is stored in S3. User docs: [pii_service/README.md](pii_service/README.md)
  (a walkthrough, then the full API reference).

Detailed results are in two reports in this folder:
[PII_RESULTS_LOTS_1_2_3.md](PII_RESULTS_LOTS_1_2_3.md) (technical, with the source of every
number) and [PII_RESULTS_LOTS_1_2_3_v2.md](PII_RESULTS_LOTS_1_2_3_v2.md) (short, for readers new
to the project). If you change a number in one, change it in the other.

No detected values (names, numbers, addresses) appear in this README. Dataset titles and
column headers do.

**Contents**

1. [Status](#1-status)
2. [How it works](#2-how-it-works)
3. [Results](#3-results)
4. [Folder layout](#4-folder-layout)
5. [Setup](#5-setup)
6. [Running the script pipeline](#6-running-the-script-pipeline)
7. [Detection: the scan and its filters](#7-detection-the-scan-and-its-filters)
8. [Classification: Tier 1 rules](#8-classification-tier-1-rules)
9. [Vocabularies and the office-holder allow-list](#9-vocabularies-and-the-office-holder-allow-list)
10. [Classification: the Tier 3 LLM judge](#10-classification-the-tier-3-llm-judge)
11. [The final review](#11-the-final-review)
12. [Redaction](#12-redaction)
13. [The PII API](#13-the-pii-api)
14. [Known limits and open work](#14-known-limits-and-open-work)
15. [Approaches tried and rejected](#15-approaches-tried-and-rejected)
16. [Sources](#16-sources)

---

## 1. Status

As of 2026-10-29:

| Part | State |
|---|---|
| Scan (`run_pii_s3.py`) + filters (`pii_filters.py`) | Built. Used for lots 1-3 and KCC |
| Tier 1 rules (`pii_classify.py`) | Built |
| Tier 2 (trained classifier) | Designed, **not built**. Tier 3 takes the Tier 1 residual directly |
| Tier 3 LLM judge (`pii_tier3.py` + vLLM `tier3-judge`) | Built. Runs as a systemd unit |
| Office-holder allow-list + rejection gazetteers | Built (`gazetteer/`) |
| Labelled gold set | **Not built.** `labels.csv` has 201 rows and an empty answer column, so no accuracy figure exists |
| Lot 1 | Closed on 2026-10-08 as holding no PII. The September re-scan covered 59.7% of it |
| Lots 2 and 3 | Scanned and classified, and the verdicts reviewed on 2026-10-12 |
| KCC | Every row scanned on 2026-10-09; **not classified yet** |
| PII API | Deployed on this host behind nginx and an ngrok tunnel |
| Merged scripts (`pipeline/`) | Built on 2026-10-29 and checked against the old scripts; **not signed off**. See [pipeline/README.md](pipeline/README.md) |

## 2. How it works

```
 file ──► scan ─────────────► Tier 1 rules ──► Tier 3 LLM judge ──► final review ──► redaction
          run_pii_s3.py        pii_classify.py   pii_tier3.py        build_final_       generate_redacted.py
          detectors+filters    false_positive /  decides only what   review.py          (scripts) or
          -> detections        permissible /     Tier 1 left         (lots 2 and 3)     pii_service/redact.py
                               present /         undecided                              (API)
                               undecided
```

`pii_classify_pipeline.py` runs the scan, both tiers and (optionally) redaction in one command.

### The three classes

Every verdict is made per **(dataset, column)**, never per value. "Ram Singh" is the same
string whether it names an MP or a farmer who phoned a call centre. The column and the dataset
it sits in decide which, so a single span cannot be classified. There are also far fewer pairs
than detections: lot 1's 14,042 detections sit in 3,997 pairs under 36 headers.

```
                 ┌─ Q1: is the column really a roster of identifiable people,
                 │  or personal contact channels?          ── no ──► false_positive
  (dataset, col) ┤
                 │  yes
                 └─ Q2: are those people named in a public-office or
                    organisational capacity, or is the channel an
                    institutional one?                      ── yes ─► permissible
                                                            ── no ──► present
```

- `false_positive`: not personal data. A crop list, place names, health indicators, numbers
  read as phone numbers.
- `permissible`: people in a public, official or professional role (MPs, officials,
  principals, scientists, award winners, advocates on a register), and the contact details of
  offices, institutions and businesses.
- `present`: personal data of private individuals (beneficiaries, patients, victims, accused,
  owners, next of kin), or a register that gives relatives' names, date of birth or community.

**Legal anchor.** Section 3(c)(ii) of the DPDP Act 2023 excludes personal data "made publicly
available ... by any other person under any obligation under any law". The names and contact
details of MPs, heads of institutions and RTI or nodal officers fall under it. A farmer's
mobile number in a call transcript does not, and nor does a household member's mother's name.
NDSAP's guidelines say sensitive personal information must not go on the platform, which is
the `present` class.

**File verdict.** The script pipeline gives a file the most serious class among its columns:
`present` over `permissible` over `false_positive`. The API ranks an unresolved column higher
than the script pipeline does: `present` > `undecided` > `permissible` > `false_positive` >
`no_pii_found`.

**The scan flag is a different thing.** `pii_detected` (lot 1) and `pii_found` are the scan's
own yes/no, set before any classification. The flag is cruder than the verdict, and the two
often disagree.

## 3. Results

These are the final counts after the review of 2026-10-12. The full breakdown is in
[PII_RESULTS_LOTS_1_2_3.md](PII_RESULTS_LOTS_1_2_3.md).

| | Lot 1 | Lot 2 | Lot 3 | All |
|---|---|---|---|---|
| Table | `dublin_core_metadata` | `dublin_core_remaining` | `dublin_core_lot3` | |
| Rows | 206,972 | 117,721 | 29,598 | 354,291 |
| Scanned | 123,578 (59.7%) | 111,638 (94.8%) | 28,832 (97.4%) | 264,048 |
| Files with a detection | 3,917 | 5,878 | 2,387 | 12,182 |
| **`present`** | **0** | **32** | **27** | **59** |
| **`permissible`** | **8** | **330** | **300** | **638** |
| False detections removed | 3,909 | 5,518 | 2,060 | 11,487 |

- **94% of the files with a detection held no personal data.** Typical false detections:
  - HMIS indicator labels (three headers made up 95% of lot 1's flagged columns);
  - Census village names, crime heads, routes and project names (lot 2);
  - crops, diseases and local bodies (lot 3);
  - money amounts, coordinates and tender numbers read as phone or Aadhaar numbers.

  No Aadhaar hit in any lot was a real Aadhaar number.
- **The pipeline's `present` verdict was right for 58 of 468 files (12%)**, and its
  `permissible` verdict for 351 of 384 (91%). Most of the wrong `present` verdicts came from
  two rules, `R11-personal-channel` and `R10-individual-records` (see
  [section 8](#8-classification-tier-1-rules)).
- **The most serious finds** are four Smart Cities Mission files about COVID patients, missing
  children and traffic-accident victims. The rest of the 59 are:
  - Minor Irrigation Census schedules;
  - Rajya Sabha answer tables (accused persons, encroachers, the dead and their next of kin,
    beneficiaries);
  - state scheme beneficiary lists, including 16 fishermen's relief payments;
  - five advocate rolls that give family or birth details;
  - two property and merchant files.
- **71 of the 638 `permissible` datasets are judgment calls**, marked as sets so each can be
  moved in one step:
  - 16 parliamentary member directories that also give relatives' names and home addresses
    (nine of them under an unrelated title, which is an upload error);
  - 40 advocate and notary registers;
  - 15 smaller lists.

  If all 71 were moved to `present`, the total would be 130.
- **KCC holds farmers' personal data in at least 408 files**: PM-KISAN status records pasted
  into `KccAns` from 2019 onwards. The full scan is not classified yet.
- **59 is a floor.** The review removed false detections. It did not look for misses (see
  [section 14](#14-known-limits-and-open-work)).

## 4. Folder layout

### Scripts

| Stage | Script | What it does |
|---|---|---|
| Scan | `run_pii_s3.py` | Detectors, filters and dataset flag. S3 batch mode for lots 1 and 2, or `--path` for a local folder |
| | `pii_utils.py` | NER models, recognizers, column selection, overlap resolution |
| | `pii_filters.py` | Per-detection and per-column filters, dataset flag; running it runs its self-tests |
| Classify | `pii_classify.py` | Tier 1 rules |
| | `pii_tier3.py` | Tier 3 LLM judge |
| | `pii_classify_pipeline.py` | Scan, Tier 1, Tier 3 and redaction in one command |
| Lot drivers | `run_lot2_pii.py`, `run_lot3_pii.py` | Stage, scan, repair, classify and join results back to the table, per lot |
| KCC | `run_kcc_scan.py` | First-250-rows scan, one state at a time, resumable |
| | `run_kcc_full_scan.py` | Scan of every row, staged as state-year folders, several workers |
| | `kcc_public_contact_override.py` | Stopgap: moves KCC columns from `present` to `permissible` when every phone number in them is a public contact |
| Review and export | `build_final_review.py` | The 2026-10-12 review decisions -> `final_review/` |
| | `export_results_excel.py` | Workbooks per class -> `results_excel/` |
| | `export_pii_test_timestamps.py` | Per-dataset test timestamp and flags for lots 2 and 3 |
| Redaction | `generate_redacted.py` | Presidio-anonymised copies of `present` columns |
| History | `pii-test-sample-files/` | The first prototype's notebook; not used by the pipeline |

Eight scripts that were not part of the pipeline were removed on 2026-10-29: the vocabulary
builders (`build_gazetteer.py`, `build_frequency_blocklist.py`,
`build_public_office_gazetteer.py`), the measurement scripts (`evaluate_filters.py`,
`rescan_sample.py`, `reset_lot2_run.py`), `export_detections_lot2.py` and the first prototype
`pii-pipeline-prototype.py`. Their outputs (`gazetteer/`, `labels.csv`) stay where they are,
because the filters read them. To get a script back, take it from git:

```bash
git show f149890:pii_test/build_gazetteer.py > pii_test/build_gazetteer.py
```

### The merged scripts (`pipeline/`, under verification)

The same pipeline in eight files, built beside the scripts above, which stay untouched until
it is signed off. `pii_service/` still imports the old modules. The files, how to run them,
the old-to-new command map and how each was checked are in
[pipeline/README.md](pipeline/README.md).

### Data and outputs

Folders marked **PII** hold real detected values, sample values or judge reasoning about real
people. Keep them on this server or a reviewer's own machine, and do not pass them on.

- **Already in git:** `pii-test-sample/`, `EDA/` and `kcc/classification/`.
- **Gitignored:** `lot2/`, `lot3/`, `results_excel/` and `pipeline/out/`.

| Path | Contents |
|---|---|
| `gazetteer/` | Generated vocabularies and the allow-list (see [section 9](#9-vocabularies-and-the-office-holder-allow-list)) |
| `pii-test-sample/` **PII** | Labelled sample in three folders: `pii-present`, `pii-permissible`, `pii-false-postive` (sic). Its 489 MB AHS file is gitignored |
| `labels.csv` | Gold-set template: 200 sampled datasets plus one reference dataset, `has_pii` not filled in |
| `lot2/`, `lot3/` **PII** | Lot run outputs: `lot*_pii_result.csv` (one row per table row), `classification/` (Tier 1, Tier 3, final per column and per file), scan summaries, logs |
| `kcc/` **PII** | `kcc-transcripts/` (the corpus; gitignored), `classification/` (September verdicts, `*.before_override.csv`, `public_contact_override.csv`), `full/` (full-scan summary and logs) |
| `final_review/` | The review's result of record: `final_results.csv` (one row per reviewed dataset: title, pipeline and final verdict, what it holds), `kept_columns.csv`, `pii_test_timestamps_lots_2_3.csv`. Titles and verdicts only, no detected values |
| `results_excel/` **PII** | Five workbooks with every flagged value. `export_results_excel.py` says they must not be committed |
| `EDA/` **PII** | Exploration scripts, lot 1 re-scan extracts, Tier 3 audit files (`tier3_prewrite_pii_column_class.csv` reverts the Tier 3 write exactly; `tier3_penalty_compare.csv`) |
| `pii_s3.log`, `pii_s3_lot2.log` | Scan logs for lots 1 and 2 (column names only, no cell values) |
| `pii_service/` | The API (see [section 13](#13-the-pii-api)) |
| `pipeline/out/` **PII** | Test outputs of `pipeline/run.py` and `pipeline/report.py`, including copies of the `results_excel/` workbooks |

Outside this folder:

- `transformation/metadata.db` holds `pii_detections_lot1`, `pii_detections_lot2` (the August
  scan), `pii_column_class` and the view `pii_dataset_class`.
- `data/lot2_downloads/` holds the 76,527 lot 2 files fetched on 2026-10-08. They exist on this
  server only.
- `data/kcc_full_stage/` holds the full KCC scan's detections.

## 5. Setup

Run everything from the repo root with the repo's `.venv`. Scripts put `pii_test/` on
`sys.path` themselves, and the gazetteers load relative to it.

- **Install packages with `uv pip install`, never `uv sync`.** The lock pins a cu118
  torchvision. This box runs torch 2.7.1+cu126, and `uv sync` breaks the torch stack.
- **Keep `transformers` at 4.53.x.** Pin it whenever you add a Hugging Face dependency: an
  unpinned install moves it to 5.x, which breaks the NER pipeline.
- **Models:**
  - Hugging Face: `Davlan/xlm-roberta-base-ner-hrl` (Latin script) and `ai4bharat/IndicNER`
    (Devanagari). Both download on first use.
  - spaCy: `en_core_web_lg` and `xx_sent_ud_sm` (`python -m spacy download ...`). spaCy stays
    on CPU, because running CuPy beside torch in one process broke the batched path.
- **Memory limits the worker count, not the GPU.**
  - A scan worker takes about 2.4-3.3 GB of RAM, and that grows over a long run.
  - This box (15 GB, no swap) fits three workers at most.
  - With the judge and the API loaded, one GPU worker fits.
  - SIGTERM to a driver can orphan its workers, so check `ps` afterwards.
- **The GPU is shared.** The T4 (15 GB) holds:
  - the judge, at `--gpu-memory-utilization 0.65` (about 10 GB);
  - the API's scan models (about 0.65-3 GB);
  - any scan you start.

  A CUDA OOM inside vLLM's engine loop kills the whole judge server. It is not a request you
  can retry.
- **Lot runs write CSV only.** The lot 2, lot 3 and KCC drivers and `pii_classify_pipeline.py`
  write nothing to `metadata.db` or S3. Only these do:
  - `run_pii_s3.py --batch` / `--iterate` / `--lot2`;
  - `pii_classify.py --write` and `pii_tier3.py --write`;
  - `generate_redacted.py` in its default S3 mode.

Self-tests (no GPU, no server, no S3):

```bash
.venv/bin/python pii_test/pii_filters.py           # filter self-tests; exits non-zero on failure
.venv/bin/python pii_test/pii_classify.py --test   # Tier 1 rules
.venv/bin/python pii_test/pii_tier3.py --test      # Tier 3 prompt and parser; no judge needed
.venv/bin/python pii_test/pipeline/selftest.py     # the same checks for pipeline/
.venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v
```

## 6. Running the script pipeline

### A folder, start to finish

```bash
# scan + Tier 1 + Tier 3 (+ redacted copies of `present` columns)
.venv/bin/python pii_test/pii_classify_pipeline.py --path DATA_DIR --out-dir OUT --redact

# classify a scan that already ran
.venv/bin/python pii_test/pii_classify_pipeline.py --csv SCAN_DIR \
    --summary SCAN_DIR/summary.csv --output OUT/pii_result.csv

# Tier 1 only, when the judge is not up
.venv/bin/python pii_test/pii_classify_pipeline.py --csv SCAN_DIR --out-dir OUT --no-llm
```

- `--path` writes `pii_detections.csv` into the scanned folder, beside the data, because the
  next run looks for it there. Everything else goes to `--out-dir`:
  - `tier1_column_class.csv` and `tier1_report.txt`;
  - `tier3_verdicts.csv` (verdict and reasoning per undecided pair);
  - `column_class.csv` and `dataset_class.csv` (final, after both tiers);
  - `file_summary.csv`, `scan_summary.csv` and `scan.log`.
- If the judge is down, the Tier 1 outputs are still written and the script exits with code 2.
  Re-run once the judge is up, or pass `--no-llm`.
- `--judge-per-folder` judges each (folder, column, header row) once. Use it only where a
  folder holds one dataset split into files, like KCC's state folders.

Scan only:

```bash
.venv/bin/python pii_test/run_pii_s3.py --path DIR --max-rows 250 --summary-out DIR/scan_summary.csv
```

### Lots 2 and 3

```bash
.venv/bin/python pii_test/run_lot3_pii.py stage      # build the folder the scan reads
.venv/bin/python pii_test/run_lot3_pii.py scan --gpu # resumes per shard
.venv/bin/python pii_test/run_lot3_pii.py repair     # restage ragged CSVs; then scan again
.venv/bin/python pii_test/run_lot3_pii.py classify   # Tier 1 + Tier 3 with catalogue metadata
.venv/bin/python pii_test/run_lot3_pii.py result     # join the final class back to table rows
```

`run_lot2_pii.py` takes the same subcommands. The drivers exist for four reasons:

- **Formats.** The scan reads `.csv`, `.xls` and `.xlsx`. 4,777 lot 3 files are JSON, and 207
  ".xls" files are CSV text. `stage` symlinks each file under the extension its content
  actually has, and writes the first 250 JSON records out as CSV.
- **Resuming.** Results land per shard, and a restart skips the finished shards. In lot 2,
  `stage` only adds files, so a file keeps its shard as new downloads arrive.
- **Ragged CSVs.** `repair` pads every row to one width.
- **Titles.** Files are named by UUID, so `classify` gives the tiers the title, catalogue
  title, description, publisher and sector from the lot's table.

Re-classifying reads each flagged file's header row, so the files must be on this server.

- **Lot 3.** The 20,781 files in `data/lot3_downloads` were moved to S3 on 2026-10-08 (list
  in `data/lot3_downloads_moved_to_s3_20261008.csv`). The 8,073 in `data/lot3_s3_downloads`
  are still local.
- **Lot 2.** The downloads exist only in `data/lot2_downloads/`, so do not delete it before
  it is uploaded.

### Lot 1 and the old S3 batch flow

`run_pii_s3.py --batch N` (or `--iterate`) scans lot 1 from S3. `--lot2 [--ministry M]` is the
August lot 2 flow. Both skip rows already marked tested, write to `metadata.db`, and re-upload
the table to `s3://nic-ogdp-datasets/pii-results/dublin_core_metadata_snapshot.parquet` after
each batch.

> **Do not re-run lot 1 as things stand.** The local table's `pii_tested` reads `'0'` on every
> row since the lake sync of 29 Sep. A run would redo all 206,972 files, and its first batch
> would overwrite the S3 snapshot, which is the only per-row record of the September flags.
> The safe order:
>
> 1. Copy the snapshot aside.
> 2. Restore the September flags from it into the local table.
> 3. Run.
>
> That is about 10 hours with three workers, or about 30 with the one worker that fits beside
> the judge and the API.

### KCC

```bash
.venv/bin/python pii_test/run_kcc_scan.py --gpu                    # first 250 rows per file
.venv/bin/python pii_test/pii_classify_pipeline.py --csv pii_test/kcc/kcc-transcripts \
    --out-dir OUT --summary pii_test/kcc/kcc_scan_summary.csv --judge-per-folder
.venv/bin/python pii_test/kcc_public_contact_override.py --run-dir OUT \
    --scan-dir pii_test/kcc/kcc-transcripts --summary pii_test/kcc/kcc_scan_summary.csv --dry-run

.venv/bin/python pii_test/run_kcc_full_scan.py stage               # every row
.venv/bin/python pii_test/run_kcc_full_scan.py scan --gpu --worker w1   # and w2, w3 beside it
.venv/bin/python pii_test/run_kcc_full_scan.py merge
```

- **The override is a stopgap.** KCC answers quote officers', research stations' and
  helplines' numbers, and `R11` reads each of them as a personal number. The override moved
  454 columns to `permissible` when every phone number in them was:
  - an STD landline;
  - a number that recurs in 3+ files;
  - or introduced by an officer cue.

  **Re-running the pipeline drops it.** A proper KCC rule in Tier 1 has not been written yet.
- **The full scan keeps the 250-row results intact.** It reads a staged copy, so the
  per-folder `pii_detections.csv` files the September verdicts were built on are not
  overwritten.

### Standalone tiers and vocabularies

```bash
.venv/bin/python pii_test/pii_classify.py --db transformation/metadata.db --write   # Tier 1 -> pii_column_class
.venv/bin/python pii_test/pii_classify.py --csv SCAN_DIR --out classes.csv          # Tier 1 over a --path scan
.venv/bin/python pii_test/pii_tier3.py --db transformation/metadata.db --write      # Tier 3 on the undecided rows
.venv/bin/python pii_test/build_final_review.py
.venv/bin/python pii_test/export_results_excel.py --lot1-snapshot PATH/lot1_snapshot.parquet
```

`pii_classify.py --write` and `pii_tier3.py --write` need the DuckDB lock, so they exit if a
scan holds it.

The vocabulary builders were removed on 2026-10-29 (see [section 4](#4-folder-layout)). To
rebuild a list, restore its builder from git first, then run it as before:

```bash
git show f149890:pii_test/build_gazetteer.py > pii_test/build_gazetteer.py
.venv/bin/python pii_test/build_gazetteer.py --all-families --stats
# likewise build_frequency_blocklist.py --stats, build_public_office_gazetteer.py --all
```

## 7. Detection: the scan and its filters

### What the scan reads

- **Rows.** The first `--max-rows` rows (default 250). In lot 1, 77% of files are longer than
  that. The KCC full scan lifted the limit.
- **Columns.** Only columns that could hold text about people. A purely numeric table is
  "no scannable columns", which was 70% of lot 2's files. Column selection
  (`pii_utils.classify_column_name`, `_column_skip_reason`) works on header tokens:
  - **Skip tokens** (geography, organisations, time, codes) mark a column as not personal.
    Organisation tokens such as `university`, `college` and `bank` were added because
    organisation names were the largest PERSON false positive left once geography was
    excluded.
  - **Person tokens.** A token from `PERSON_NAME_TOKENS` together with `name` overrides the
    skip tokens (`Name of Vice-Chancellor/Director/Head`). `NEGATIVE_PERSON_BIGRAMS` cancel
    that reading in compounds where it is always wrong: `head quarter`, `mother tongue`,
    `crime head`, `head office`. In the August lot 2 scan those compounds caused 35% of all
    detections.
  - **Force-scan tokens** (`email`, `mobile`, `phone`, `contact`, `aadhaar`, `pan`, ...) force
    a scan and bypass the dtype checks, because a phone column parses as integers. A
    person-token force still gets the cardinality check.
  - **Low cardinality.** A column with few distinct values over many rows is an enum and is
    skipped.
  - **Substring matching** is used only for single-token headers, and only for tokens of 5+
    characters. So `fathername` matches, but the `id` inside `Guide_Name` cannot.

### Detectors

Each distinct cell text is analysed once (`batch_analyze_cells`). That deduplication is what
made 12.4 million KCC rows affordable.

1. **Hugging Face NER on GPU.**
   - `Davlan/xlm-roberta-base-ner-hrl` reads Latin-script text and `ai4bharat/IndicNER`
     reads Devanagari.
   - Aggregation is `"average"`, through `WordAwareTokenClassificationPipeline`, which
     recomputes word boundaries. Both models are SentencePiece, where a word-start token
     absorbs the whitespace before it. The upstream fallback heuristic therefore glued the
     next field label onto names ("NAME\nAddress") and pulled real names under the score
     floor.
   - Spans are trimmed of whitespace, and whitespace-only spans are dropped.
2. **Presidio with spaCy `en_core_web_lg`** for PERSON, plus Presidio's pattern recognizers.
   spaCy's PERSON score is a flat 0.85 (see [section 15](#15-approaches-tried-and-rejected)).
3. **Regex recognizers:**
   - Indian mobile numbers;
   - Aadhaar, which must pass the Verhoeff checksum, with repeated-digit fillers rejected;
   - PAN;
   - PM-KISAN farmer registration IDs: two letters and nine digits.
4. **Field-label name patterns** (`FIELD_NAME_PATTERNS`) for pasted PM-KISAN blocks ("Name Of
   Farmer", "Father/Spouse/Guardian Name"). These run in the local `--path` scan only, not in
   the S3 flow.

`pii_utils.resolve_overlaps` reduces overlapping spans of the same type to the best one: the
highest score wins, and the shorter span breaks a tie. It runs again after the field-label
names are merged in.

### Filters (`pii_filters.py`)

Filters only ever remove detections. Each rejection carries a reason, so it can be traced.

**PERSON:**

| Filter | Rule | Why |
|---|---|---|
| Closed vocabularies + gazetteers | Reject a value found in a rejection list. Multi-word entries match as whole-token subsequences, not substrings | Substring matching rejected a real first name for containing the crop "rice" |
| Cross-dataset frequency | Reject a value seen in more than `CROSS_DATASET_MAX` (3) datasets (`cross-dataset-common`) | A personal name stays in the dataset about that person; "Dacoity" appeared in 584 |
| Score floor | `PERSON_SCORE_FLOOR` = 0.68 | Works only under `average` aggregation; see [section 15](#15-approaches-tried-and-rejected) |
| Digit | Reject a value containing a digit | Removes survey IDs and crop varieties; no real name was lost on the reference set |
| Name shape | `looks_like_person_name`: 2-5 alphabetic tokens. A column is mononymic, and lets single tokens through, when `MONONYM_COLUMN_SHARE` (60%) of its values are single tokens | 5 tokens, because Hindi honorific stacking produces five |
| Repetition | Reject a value holding more than 5% of its column's PERSON detections (`MAX_VALUE_SHARE_OF_COLUMN`), once the column has 20 or more (`MIN_COLUMN_DETECTIONS`) | A dropdown label repeated 60 times is not 60 people. Needs no lexicon and works in any language |
| Cell context | A span covering less than half (`FRAGMENT_COVERAGE`) of a cell longer than 40 characters needs a naming cue within 48 characters to its left: `name`, `s/o`, `shri`, `smt`, `dr`, or the Devanagari नाम, श्री, पुत्र | Every false PERSON in free text was a fragment of running prose; real names in prose are introduced |
| Categorical column | Drop non-regex PERSON detections in a column whose distinct-value ratio is at or below `NAME_LIKE_CARDINALITY_RATIO` (0.5) | `Crop` and `QueryText` are categories, not rosters |

**PHONE_NUMBER** (`classify_phone_number`, Indian numbering plan):

- A **mobile** (10 digits starting 6-9, optional +91/0091) is kept and can flag a dataset.
- A **landline** (0 + STD code) is kept but needs corroboration (`PERSONAL_PHONE_KINDS`),
  because it can be a home.
- **Toll-free and short codes** (1800, 1860, 155, 180) are dropped: no one's personal number
  is in that range.
- **Anything else** is dropped. A match must also be written like a number. Presidio's
  "toll-free" test had turned an evapotranspiration volume into a helpline.

**Email, Aadhaar, PAN and farmer ID** come from structurally constrained regexes and are kept
as they are.

**Devanagari.** Python's `\w` does not match combining marks (matras, virama). The
normalisation used to shatter every Hindi name into fragments and make the shape rule reject
all of them. Combining marks are now excluded from the punctuation class. Devanagari cues are
matched as substrings, because `\b` does not work around matras.

### Dataset flag

`evaluate_dataset_flag` sets the scan's `pii_found`:

- High-precision entities can flag a dataset on their own: email, Aadhaar, PAN, farmer ID and
  mobile numbers.
- PERSON hits need corroboration: a name-shaped, distinct, corpus-rare column.

## 8. Classification: Tier 1 rules

`pii_classify.py`. Rules fire in order, and the first match decides.

| Rule | Verdict | What it tests |
|---|---|---|
| `R1-skip-header` | `false_positive` | The header cannot hold personal data |
| `R1-controlled-vocab` | `false_positive` | The header marks a closed category list, and only PERSON was detected |
| `R2-column-shape` | `false_positive` | Values not name-shaped, or low cardinality, or corpus-common *and* not uniformly name-shaped |
| `R3-not-a-number` | `false_positive` | The "phone numbers" fit no numbering-plan slot, or are bare digit runs in a column that names no contact channel |
| *(gate)* | -> `R12` | No person or contact signal in the column itself: context alone may not convict |
| `R4-institutional-channel` | `permissible` | Every contact value is toll-free, a landline, or an institutional email domain (`.gov.in`, `.nic.in`, `.ac.in`, `.edu.in`, `.res.in`, `.org.in`) |
| `R5-private-absolute` | `present` | The header says beneficiary, patient, victim or accused. Overrides any context |
| `R6-office-allowlist` | `permissible` | At least 30% of distinct values (minimum 3) are known public office holders |
| `R7-directory-context` | `permissible` | The dataset is an office-bearer directory |
| `R8-office-header` | `permissible` | The header names a public office (MP, CPIO, chancellor, ...) |
| `R9-private-contextual` | `present` | The header names a relative or a private role, outside a directory |
| `R10-individual-records` | `present` | The dataset holds individual records |
| `R11-personal-channel` | `present` | A subscriber mobile number or a personal email address |
| `R12-residual` | `undecided` | No rule applies: goes to Tier 3 |
| `T3-judge` | any | Tier 3 LLM judge |
| `T4-reviewer` | any | Set by a human reviewer; no rule or model re-judges it |

Ordering decisions:

- **Q1 before Q2.** A column that is not personal data cannot be "permissible". Asking about
  publication first would launder every crime-head list into a legal category.
- **Dataset context outranks most header role words (R7 above R9).** In a member directory,
  `Father Name` holds a real relative of an MP, published in the member's official biography.
- **Some header words outrank any context (R5 above R7).** A dataset calling itself a
  directory does not make its patients public.
- **The column schema outranks the title.** Some files do not match their catalogue entry:
  - six lot 1 files titled "Data Item Comparison Report ..." are the Lok Sabha member
    directory;
  - three lot 2 files carry tourism and NREGA titles.

  So context is derived from the column schema too (`schema_context`,
  `DIRECTORY_SCHEMA_MARKERS`), and the schema wins.
- **Frequency alone never rejects a column.** The parliamentary directories are republished
  about six times, so a real MP has a median cross-dataset frequency of 6. Real controlled
  vocabularies sit at a median of 17. The ranges overlap, so frequency rejects only together
  with weak name shape.
- **Address columns count as personal data.** That is what makes an MP's listed address
  `permissible` and a respondent's address `present`.
- **No confidence number.** A rule verdict carries a `rule_id` and an ordinal `rule_strength`.
  Inventing a float would repeat the mistake that makes the detector's 0.85 useless.

**How the `present` rules held up** in the lots 2 and 3 review:

- `R11` alone was right for 2 of 61 lot 2 files and 1 of 44 lot 3 rows. Office, depot, hotel
  and helpline numbers are mobile-shaped too.
- `R10` alone was right for 16 of 81 and 2 of 32. A title match plus a header called `name`
  also convicts college, company and disease lists.

`R10` also caught the Minor Irrigation Census files, so it cannot simply be switched off.

**Output.** In the database these go to `pii_column_class` (`uuid, lot, column, entity_types,
n_detections, pii_class, rule_id, tier, evidence_json, ...`), rolled up by the view
`pii_dataset_class`. In a folder run they go to the CSVs listed in
[section 6](#6-running-the-script-pipeline).

## 9. Vocabularies and the office-holder allow-list

Everything under `gazetteer/` is generated by script, never hand-edited. Change the script and
re-run it. The builders are no longer in the tree; [section 6](#standalone-tiers-and-vocabularies)
shows how to restore one from git.

### Rejection lists

These hold things that are categorically not people. There is one file per vocabulary, so a
rejection names its list and any list can be dropped on its own.

| File | Entries | Built from |
|---|---|---|
| `place_names.txt` | 16,562 | The catalogue's own spatial fields (`remain_raw_metadata.spatial_*`); entries under 4 characters dropped |
| `cross_dataset_common.txt` | 4,648 | Counted: `count<TAB>value` for every PERSON value seen in 2+ datasets |
| `settlements.txt` | 1,026 | Block and locality name columns, 600 datasets |
| `commodities.txt` | 520 | Commodity columns, 60 datasets |
| `occupations.txt` | 486 | `NCO Name`, 40 datasets |
| `crime_heads.txt` | 278 | NCRB `Crime Head`, 40 datasets |
| `languages.txt` | 256 | Census `Mother Tongue Name`, 18 datasets |
| `species.txt` | 113 | `Species`, 9 datasets |

- **Value families are harvested from the corpus**, not typed. For each family the script
  finds columns whose header matches, downloads those files and takes their distinct values.
  This captures the corpus's own spellings ("MAKKI", "ATTA CHAKKI", "C.H. Not Amounting to
  Murder").
- **Two guards keep real names out.** Header patterns are narrow, because free text must never
  feed a rejection list. And a value must appear in at least 2 harvested datasets (3 for
  free-text families). A name typed into a commodity column does not recur, so it is not put
  beyond detection.
- **The frequency list has a feedback loop.** It is built from post-filter detections that
  were themselves produced using it, so each rebuild can only remove more. Datasets known to
  hold real names are left out of the counts.
- `place_names.txt` contains 123 inert `(+N more)` truncation markers copied from the
  catalogue.

### The office-holder allow-list

`public_office_holders.txt` holds 26,512 names. Three sources build it:

- `--local`: the Lok Sabha former-member directories in the sample;
- `--corpus`: directory datasets found by **column schema** on S3, which supply the current
  members;
- `--wikidata`: Indian politicians and holders of India-located positions, in English and
  Hindi.

This is the only list that makes the pipeline quieter about **real people**, so a bad entry
marks a private person publishable. It has four guards:

- No mononyms, counted after honorifics are stripped.
- No collision with any rejection list.
- Nothing seen in more than 3 datasets.
- A single match never decides: `R6` needs 30% of a column's distinct values, minimum 3.

The guards showed their worth in testing:

- **The local source alone was not enough.** Built from former members only, the list matched
  2% of the current-member names. The `--corpus` source closed that gap.
- **The bigger list did not mean more matches.** With all 26,512 names, `R6` fires on exactly
  the six `Member Name` columns, at a 92% match rate. The extra 18,000 names swept no private
  column into `permissible`.
- **The list refuses relatives.** `Mother Name` and `Spouse Name` matched 0%, and relative
  columns are deliberately not harvested. They are `permissible` only inside a directory,
  which is `R7`'s job.
- **Wikidata is incomplete.** Its endpoint was rate-limiting during the build, so only the
  first page of the politician query landed. A re-run needs no code change.

## 10. Classification: the Tier 3 LLM judge

`pii_tier3.py`. The judge is vLLM serving Qwen3-8B-AWQ as model `tier3-judge` on
`127.0.0.1:8000`, with `max_model_len` 4096. It runs as the systemd unit `tier3-judge` (see
[section 13](#13-the-pii-api)).

**Scope.** The judge decides only `undecided` pairs. It never revisits a pair a rule decided:
the rules are the high-precision layer, and an 8B model is not entitled to overrule them.
Everything stays on this box, because the values being judged are, by hypothesis, PII.

**Input.** The judge sees:

- the dataset title, catalogue title and description;
- the file's full header row (from `Conforms To` where present);
- the flagged column, its entity type and up to 15 flagged values.

Tier 1's arithmetic (cardinality, name shape, frequency) is deliberately left out. Tier 1
already weighed it and abstained, and feeding it back invites the model to re-derive a rule
that declined to fire.

**Design decisions, each forced by a probe:**

- **Reasoning on, class only.** With reasoning off, a Lok Sabha member column came back as
  `present` with role `public_office`, which contradicts itself. With reasoning on, it is
  correctly `permissible`. The trace is stored in `evidence_json.llm_reasoning` for a human.
  The pipeline does not parse it. The model reports no role and no confidence.
- **Publication is not evidence.** Without this rule the model reasoned "it is on data.gov.in,
  so publishing it was lawful" and passed scheme beneficiaries as `permissible`. The system
  prompt therefore says:
  - being published is the thing under audit, not evidence about it;
  - `permissible` means only the person's own public office;
  - beneficiaries are private however public the scheme is;
  - ties go to `present`.
- **No guided decoding.** vLLM accepted `response_format: json_schema` and `guided_json` and
  ignored both. The reply ends in a `CLASS: <label>` line, read by a tolerant parser.

**Safety rails:**

- A reply that does not parse is never a verdict. The pair keeps `undecided` and its Tier 1
  rule, and the failure goes to `evidence_json.llm_error`.
- A bare class token counts only if exactly one of the three appears.
- Classes named inside `<think>` are stripped, and an unclosed think block is refused, so
  truncation cannot pass as ambiguity.
- A run of consecutive transport failures aborts the run. Otherwise one OOM would mark every
  remaining pair `undecided (connection refused)`.
- Write-back sets `tier='llm'` and `rule_id='T3-judge'`, and keeps the Tier 1 rule in
  `evidence_json.tier1_rule_id`.

**Decoding:**

- `temperature=0` gives byte-identical replies within one server session. Near-ties can still
  move across sessions.
- Use `--max-tokens 2500`. At 1200 the think block did not close on some pairs.
- Thinking mode under greedy decoding can loop, and Qwen's model card warns about this.
  `--presence-penalty 1.5` breaks the loop and stays deterministic. In a full dry re-run it
  left 162 of 164 verdicts unchanged. It is used to re-ask columns that came back unfinished,
  not as the default.

**Known weak spots:**

- The judge is weak on phone-number columns.
- It is swayed by titles. When the API has no title, the file name becomes the title, and
  "synthetic_people" was judged `false_positive` as "probably synthetic". Callers should send a
  real title.
- Its `present` verdicts were right for 9 of 57 lot 2 files and 19 of 73 lot 3 rows. Most of
  its errors were people in public roles, not false detections.

## 11. The final review

The pipeline's verdicts over-call `present`. So on 2026-10-12 every dataset judged `present`
or `permissible` in lots 2 and 3 (852 in all) was read again:

- title, all headers, each flagged column with sample values;
- the cells themselves where that did not settle it.

**The review was done by the AI assistant** working on the project. No second reviewer
has checked it. It works per dataset and column, not per value, so a kept column can still hold
single false values.

- **Where the decisions are.** `build_final_review.py` holds them and writes
  `final_review/final_results.csv` and `kept_columns.csv`. The latter lists six columns the
  pipeline had rejected that do hold personal data.
- **No pipeline output was changed.** `column_class.csv`, `dataset_class.csv` and
  `lot*_pii_result.csv` are as the pipeline left them. **A pipeline re-run does not carry the
  review forward.**
- **Judgment calls** are datasets that are `permissible` by the rule but arguable. Each is
  marked with its set and reason, so a set can be moved to `present` in one change.
- **Lot 1's eight `permissible` files** were not reviewed again.
- **The 852 reviewed verdicts are labels** for the `present` and `permissible` classes. About
  200 `false_positive` and no-detection files read the same way would give the first accuracy
  figures for the whole pipeline.

## 12. Redaction

There are two implementations:

- **`generate_redacted.py`** (script side) runs Presidio's anonymizer over the columns a run
  called `present`. Use `--run-dir` for a classified folder run; the default S3 mode redacts
  every file with the scan flag set. `pii_classify_pipeline.py --redact` calls it.

  It replaces only the values that survive the full filters, which leaves gaps:
  - On lot 3's real name columns the detector flagged only 48-73% of the cells.
  - The cell-context filter drops names in free text that no "Shri" or "Name:" introduces.

  So names leak through.
- **`pii_service/redact.py`** (API side) works around both gaps:
  - it replaces every filled cell of a short-value column;
  - it re-searches free text without the column filter;
  - it falls back to replacing the whole column when in doubt.

  See [section 13](#13-the-pii-api).

Use `generate_redacted.py --run-dir` on its own for KCC. Its verdicts carry the hand-applied
override, and re-running the pipeline would drop it.

## 13. The PII API

Upload a CSV, JSON, Excel or PDF file, ideally with what the dataset is, and get back whether
it holds personal data: detection, Tier 1 rules, then the Tier 3 LLM judge. On request it also
returns a redacted copy. Every run is stored in its own S3 folder.

**Using it:**

- [pii_service/README.md](pii_service/README.md) has the user docs in two parts. Part 1 is the
  walkthrough for people outside the team: the web page, a minimal client, how to describe a
  dataset and how to read the answer. Part 2 is the full reference: endpoints, fields, the
  result object, errors, limits and data handling.
- `GET /docs` serves FastAPI's interactive docs, generated from the code.

```bash
curl -F file=@hospitals.csv -F title="Directory of District Hospitals" http://localhost/scan
# -> 202 {"run_id": "..."}; then poll GET /jobs/<run_id> until status is done/error
```

### Separate from the script pipeline

`pii_classify_pipeline.py` classifies *our* corpus, with metadata from `metadata.db`. Uploads
are unrelated datasets, so the API has its own orchestration, `pii_service/api_pipeline.py`. It
imports the building blocks unchanged. None of `run_pii_s3.py`, `pii_filters.py`,
`pii_classify.py`, `pii_tier3.py` or `pii_classify_pipeline.py` is edited to serve the API.

| Step | Building block (unchanged) | API-specific input |
|---|---|---|
| Scan | `run_pii_s3.scan_local_file` via `scanner.scan_one` | Corpus name blocklist (`CROSS_DATASET_COUNTS`) cleared for this process |
| Tier 1 | `pii_classify.classify_detections` | Title, catalogue title and description **from the request**; header row read from the upload |
| Tier 3 | `pii_tier3.build_prompt`, `judge`, `to_rows`, `apply_verdicts` | The request's catalogue title and description go into the prompt |
| Decide | The API's own order | `present` > `undecided` > `permissible` > `false_positive` > `no_pii_found` |

Deliberate differences from the script run:

- The cross-dataset blocklist is off. It would drop a private person who shares a name with
  someone frequent in our data.
- Metadata comes from the request.
- Tier 1's corpus-frequency test sees one dataset, so it never fires.
- Tier 1's vocabularies and the gazetteers are kept, because they are general knowledge.
- Redaction differs from `generate_redacted.py` (see below).

**Output** is kept simple:

- one `final_class` per file;
- a fixed one-line `message`;
- a table of flagged columns (column, class, types, `decided_by`, reason);
- plain-language `warnings`: judge did not run, no metadata sent, nothing scanned, NER
  degraded.

Full evidence goes to `detail/` in S3.

**If the judge is down, the run still finishes.** It finishes on Tier 1, the columns the judge
would have decided stay `undecided`, and `tier3` reads `unavailable` (or `skipped` /
`aborted`). At most 40 columns per run go to the judge, which bounds how long one wide file can
hold the single worker.

### Design

- **Job queue, not a synchronous request.** A 250-row free-text file takes about 9 s and a
  large one takes minutes. A job ID plus polling avoids every timeout in the chain.
- **One worker, one run thread.** One GPU, one model copy of about 2.5 GB per process, and the
  job store and queue live in process memory. **`workers = 1` is load-bearing**: a second
  worker would answer polls for jobs it has never heard of. Runs execute one at a time on a
  single `pii-run` thread.
- **Uploads are PII.**
  - Local run folders (`pii_test/pii_service/jobs/`) are deleted after 6 h.
  - `jobs/`, logs, pid and socket files are gitignored.
  - Logs never hold cell values.
- **Logging.** `run_pii_s3.py` reconfigures the root logger at import, pointing it at
  `pii_s3.log`. The service re-configures logging after importing it.
- **A worker crash loses queued and running jobs** from memory. Finished runs are already in
  S3, and the uploader resubmits the rest.

### S3: one folder per run

```
s3://nic-ogdp-datasets/pii-service-runs/
  README.txt
  <YYYY-MM-DD>/<run_id>/            run_id = <UTC time>_<uuid4 hex>
    input/<file>                    the upload as received (contains PII)
    converted/<name>.csv            the table scanned: JSON uploads, text files named as Excel,
                                    and a PDF's text (page, line, text)
    request.json                    metadata, options, timings
    result.json                     the answer
    columns.csv                     the flagged columns as a table
    results.csv                     every detection with Tier 1's and the judge's verdict
    redacted.csv                    only when a redacted copy was asked for and made
    detail/detections.csv           per detection
    detail/tier1_column_class.csv   Tier 1 rows with their evidence
    detail/tier3_verdicts.csv       judge verdict + reasoning (when it ran)
    detail/column_class.csv         final rows after both tiers
    run.log                         that run's log lines (no cell values)
```

- Folders are kept forever. There is no lifecycle rule on the prefix.
- Failed runs are uploaded too, with `status: "error"` in `result.json`.
- If the upload fails, the service retries once. After that the run still finishes, with
  `s3_folder: null` and `s3_error` set, and the full error goes to `pii_service.log`.
- Credentials come from the instance role. The bucket encrypts at rest (SSE-S3).
- `PII_RUNS_BUCKET` / `PII_RUNS_PREFIX` override the destination.

### File formats

The format and redaction code lives in two API modules that sit on either side of the
unchanged pipeline.

**`convert.py`** runs first and hands the scan a table it can read:

- `.csv` passes through untouched.
- `.json` is written out as `converted/<name>.csv`, every record. It can be a list of records,
  or an object holding one (`rows`, `records` or `data` when it holds several).
- `.xlsx` and `.xls` go to `run_pii_s3.read_tabular`, which reads the **first sheet only**. The
  other sheet names go into a warning. A workbook that unpacks to over 500 MB is refused
  before it is opened.
- A workbook name is checked against the file's first bytes. Lot 3 has 207 ".xls" files that
  are CSV text, and those are read as CSV.

**`pdf_text.py`** is what `convert.py` hands a `.pdf` to. It writes the PDF's text as
`converted/<name>.csv`, one row per line (`page, line, text`).

- **Text or OCR.** A page's own text is used when it has some. Three kinds of page are
  rendered and read by **pytesseract** instead (`eng+hin`, `--psm 1`):
  - a page with no text;
  - a scan with a line typed over it;
  - a page whose Hindi is in a pre-Unicode font (Kruti Dev and its kin), which extracts as
    gibberish.
- **Isolation.** It all runs in a **child process** with a memory limit and a 30-minute clock,
  so a broken or hostile PDF ends its own run and not the worker. At most `MAX_PDF_PAGES` (200)
  pages are read, and OCR runs on 3 threads.
- **Install.** It needs `sudo apt-get install tesseract-ocr tesseract-ocr-hin` and the
  `pytesseract` and `pypdfium2` packages (`uv pip install`, never `uv sync`).
- **Scanning.** A PDF is scanned by `scanner.scan_text`, not the table scan. On a scanned list
  of 120 people, the table scan found 3 of the names and `scan_text` found 112. The table
  scan's column pass drops a name that covers under half of a long cell.
- **Classification.** The tiers run unchanged on one pseudo-column, `text`, and are given no
  header row. The answer names pages. `redact=true` on a PDF answers `not_supported`.
- **Not verified.** The Kruti Dev check has not been tried on a real file.

**Not covered:** a CSV whose data rows have one more field than the header. pandas reads the
first column as row labels, so the scan never looks at it. Redaction refuses such a file, but
the check itself gives no warning.

### Redaction (`redact.py`)

`redact.py` runs last, only when `redact=true` was sent, and writes `redacted.csv` from the
columns classified `present`.

- **Short-value columns.** In a column whose median filled cell is 40 characters or fewer,
  **every filled cell** is replaced. Cutting detected values alone would publish the 27-52% of
  cells the detector misses.
- **Free-text columns.** The flagged values are cut out of each cell. Every row goes back
  through the detectors via `scanner.find_values`, which skips the column filter
  (`pii_filters.filter_column_context`). That filter is right for classifying a column and
  wrong for redacting one.
- **Fallback to the whole column.** The whole column is replaced:
  - if the text cannot be searched;
  - if a reported value is not in its cell;
  - if the column is past `MAX_SEARCH_CELLS` (200,000 cells of free text per run). The search
    runs at about 150 cells a second, and nothing else bounds it.
- **Check.** The written file is read back and checked before it is offered.

### Tier 3 judge unit

```bash
sudo cp pii_test/pii_service/tier3-judge.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now tier3-judge
curl -s 127.0.0.1:8000/v1/models        # lists tier3-judge once warm (~1 min)
```

- It runs at `--gpu-memory-utilization 0.65` (about 10 GB), not the 0.80 used by hand, so the
  API's scan models fit beside it.
- `pii-scan.service` has `Wants=` on it. If the judge is down, runs still finish on Tier 1.
- `PII_JUDGE_ENDPOINT` / `PII_JUDGE_MODEL` point the API at another judge.

### Run (production: gunicorn)

```bash
.venv/bin/gunicorn -c pii_test/pii_service/gunicorn.conf.py app:app
```

- **Supervision.** Gunicorn respawns a crashed worker, writes a pidfile and stops gracefully.
  The app runs on uvicorn inside it (`uvicorn_worker.UvicornWorker`).
- **Restart cost.** A worker respawn reloads the models. `systemctl restart pii-scan` costs
  about 15 s: about 10 s with no socket (nginx answers 502), then a few seconds of
  `{"model_loaded": false}`.
- **Unix socket, not a TCP port.** A manual run binds
  `pii_test/pii_service/gunicorn.sock`; under systemd it is `/run/pii-scan/gunicorn.sock`.
  nginx connects to that, and nothing reaches the app any other way.
- **Stale socket.** One left by a SIGKILLed master needs no cleanup: gunicorn removes it
  before binding.

```bash
curl --unix-socket pii_test/pii_service/gunicorn.sock http://localhost/healthz
```

Environment variables:

```
PII_SERVICE_BIND=127.0.0.1:8080        # back to a TCP port (not 8000: that's the judge)
PII_SERVICE_BIND=unix:/run/pii-scan/gunicorn.sock   # what the unit sets
PII_SERVICE_DEVICE=cpu                 # leave the GPU to a corpus run (~10x slower)
PII_JUDGE_ENDPOINT, PII_JUDGE_MODEL    # Tier 3 judge (default 127.0.0.1:8000, tier3-judge)
PII_RUNS_BUCKET, PII_RUNS_PREFIX       # S3 run folders (default nic-ogdp-datasets, pii-service-runs)
```

To survive reboots, install the shipped unit (needs sudo):

```bash
sudo cp pii_test/pii_service/pii-scan.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now pii-scan
```

The unit runs as `ubuntu` with `Group=www-data`, so the socket comes out `ubuntu:www-data`
mode 0770: nginx can connect and other users cannot. `RuntimeDirectory=pii-scan` creates
`/run/pii-scan` at start and removes it at stop, so no socket can outlive the process. If nginx
runs as another user on your box (`ps -o user= -C nginx`), change `Group=`.

### nginx

`pii_service/nginx-pii-scan.conf` is a ready site config pointing at that socket. It sets
`client_max_body_size 100m` to match the app's upload cap, and its install steps are in its
header. It listens on loopback only. ngrok provides the public HTTPS endpoint, so nginx needs
neither TLS nor its own auth.

### Sharing it outside this server: ngrok

`ngrok-pii.service` runs `ngrok http 80 --inspect=false`, a tunnel to nginx with an
`https://…ngrok-free.dev` URL. ngrok connects out from this server, so it needs no open inbound
port. The binary is at `~/.local/bin/ngrok` (v3).

```bash
ngrok config add-authtoken <token>      # once, in a terminal here (dashboard.ngrok.com)
sudo cp pii_test/pii_service/ngrok-pii.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ngrok-pii
curl -s 127.0.0.1:4040/api/tunnels | grep -o 'https://[^"]*'     # the public URL
```

- **Stable URL.** The unit uses the account's static domain
  (`--url https://skilled-machine-juror.ngrok-free.dev`), so the address survives restarts.
- **Password.** The unit header describes a traffic policy that adds basic auth. Keep that
  file outside the repo, because it holds the credentials.
- **Inspector off.** `--inspect=false` stops ngrok's local inspector from keeping uploaded
  files in memory.
- **Browser warning.** On a free account, browsers get ngrok's warning page once. API clients
  are not affected; see [pii_service/README.md](pii_service/README.md#base-url-and-access).
- **Polling.** Fast polling of the public address from this box gets TLS refused for about a
  minute. Use keep-alive with a 2 s interval, or `localhost`.

### Installed on this host

| | |
|---|---|
| Service | `pii-scan.service` -> `/etc/systemd/system/` (enabled at boot) |
| Judge | `tier3-judge.service` (enabled; deployed 2026-09-26) |
| Socket | `/run/pii-scan/gunicorn.sock`, `ubuntu:www-data` 0770 |
| nginx site | `/etc/nginx/sites-available/pii-scan`, symlinked into `sites-enabled`; the default site is removed (`server_name _` would clash) |
| nginx logs | `/var/log/nginx/pii-scan.{access,error}.log` |
| Listening | `127.0.0.1:80` only (since 2026-09-26). The public IP no longer answers HTTP, and outside users come in through the ngrok tunnel. The security group still allows port 80, but nothing listens on it publicly |

```bash
sudo systemctl status pii-scan       # service state
sudo systemctl restart pii-scan      # ~15 s, see above
curl localhost/healthz               # through nginx
```

> **No authentication in the app.** Anyone with the ngrok URL can upload a file, and can
> download any result whose run ID they hold. Run IDs end in a UUID4 and cannot be guessed,
> but that is not access control. To gate it, add the basic-auth traffic policy described in
> `ngrok-pii.service`.

### Dev run, tests and logs

```bash
.venv/bin/python pii_test/pii_service/app.py --port 8080   # --no-gpu, --host
.venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v
```

The tests stub the scan and the judge, so they need no GPU, server or S3. Tier 1 and the
Tier 3 plumbing are the real modules.

- `pii_service/pii_service.log`: the app (runs, sweeps, S3 uploads), plus stderr in dev runs.
- `pii_service/gunicorn.log`: gunicorn lifecycle and HTTP access lines.
- `pii_service/jobs/<run_id>/run.log`: one run's own lines, also uploaded to its S3 folder.

## 14. Known limits and open work

**Limits of the results:**

- **The review removed false detections. It did not look for misses.** Files the pipeline
  judged `false_positive` or found nothing in were not read again.
- **Two misses were found by chance.** Both are base64-encoded JSON saved as `.csv`, which the
  scan reads as no text. Only the local files were checked for that encoding, not the 34,983
  lot 2 and 20,781 lot 3 files that are only on S3.
- **Names inside long cells can be missed.** The missing-children and traffic-accident files
  put name, address, phone and caste in one cell. The scan found the phone number, not the
  name, so a file like that with no phone number produces no detection.
- **Only the first 250 rows** are read, outside the KCC full scan. Sparse records can sit
  later in a file: in one KCC file the first farmer ID is at row 26 and the second at row 382.
- **Unscanned rows:**
  - lot 1's 83,359 rows carry only a May 2026 result, which found nothing and is not reliable;
  - 6,039 lot 2 rows have no downloadable file.
- **The scan looks for direct identifiers only.** Unit-level survey records with no names,
  such as the Annual Health Survey files, carry re-identification risk that the scan does not
  assess.
- **Nothing is scored against hand labels.**

**Open work, in order:**

1. Act on the 59 `present` datasets, starting with the four Smart Cities files: withdraw,
   redact or keep.
2. Decide the judgment-call sets. Report the mistitled member directories (6 in lot 1, 3 in
   lot 2) to the catalogue owners as an upload error.
3. Look for misses where the finds were:
   - Smart Cities files with a free-text `Name and Address` column;
   - the S3-only files, for encoded content.
4. Fix `R11` so it tells an office or business number from a private one. Fix `R10` so a title
   match plus a header called `name` is not enough. Write a KCC rule to replace the override.
   Lots 2 and 3 can then be re-classified without re-scanning.
5. Build the gold set: the 852 reviewed verdicts plus about 200 `false_positive` and
   no-detection files. Freeze it before tuning anything.
6. Classify the KCC full scan, which gives the per-file result and the rows to redact.
7. Upload `data/lot2_downloads/` (76,527 files, 15 GB) to the lot 2 S3 folders.
8. Persist `rows_scanned` and full header rows in `run_pii_s3.py`. Today the sibling headers
   come from columns that produced a detection, so a clean quasi-identifier column is
   invisible.
9. Rebuild `cross_dataset_common.txt` from a clean re-scan (restore `build_frequency_blocklist.py`
   from git first, see section 6). It still holds subword fragments
   from before the aggregation fix, and one Devanagari entry in the old shattered form. Both
   are inert.
10. Not yet addressed:
    - Business names (a tailor's shop named after its owner, say) are structurally identical
      to person names and need an organisation signal.
    - Train Tier 2 once the gold set exists.

## 15. Approaches tried and rejected

- **Thresholding Presidio's score.** It cannot work, because there is no signal to threshold:
  - 22,461 stored PERSON detections carry exactly 0.85, which is Presidio's hard-coded
    `SpacyRecognizer` default;
  - 0.4 on phone numbers is the weak-regex constant.

  The score floor in [section 7](#7-detection-the-scan-and-its-filters) applies to the Hugging
  Face models only.
- **`aggregation_strategy="simple"`.** It splits one word into several entities when its
  subword tags disagree ("JHUNJHUNUN" became two). The fragments then missed every gazetteer:
  0 of the top 400 false strings matched. Its inflated scores also made scores look useless.
  `"max"` saturates near 1.0, and `"first"` keeps trailing punctuation. `"average"` is the only
  strategy that discriminates.
- **Word-frequency filtering (`wordfreq`).** It loses more real names than it removes false
  ones at every threshold, because Indian personal names are ordinary Hindi and Sanskrit words
  (Amar, Kumar, Prasad, Lal). The English-only variant is safe but catches almost nothing.
- **Cardinality as name evidence.** Wide-format tables (one row per crime head) score a ratio
  of 1.0 and look maximally name-like. Cardinality now only rejects low-cardinality columns. It
  never confirms a column.
- **A cell-level LLM check (RECAP-style).** Right idea, wrong granularity: a live re-scan is
  millions of cells. The judge works per column.
- **Swapping the NER model.** That could improve Q1 slightly, but it cannot answer Q2.
- **Case-invariance (not implemented, still promising).** Re-run NER on lower-cased text and
  score the share of a column's PERSON hits that survive. A genuine name column kept 84%; the
  KCC query column kept 9%. It would cost one extra NER pass over candidate columns.

## 16. Sources

- Presidio default score: [issue #1190](https://github.com/microsoft/presidio/issues/1190), [issue #1372](https://github.com/microsoft/presidio/issues/1372), [context enhancement](https://microsoft.github.io/presidio/tutorial/06_context/), [FAQ](https://microsoft.github.io/presidio/faq/)
- Column-level personal-data classification with table context: [arXiv 2506.22305](https://arxiv.org/html/2506.22305v1)
- RECAP hybrid multilingual PII pipeline: [arXiv 2510.07551](https://arxiv.org/html/2510.07551v1)
- LLM-as-judge for NER labels (JudgeWEL): [arXiv 2601.00411](https://arxiv.org/pdf/2601.00411)
- Industry column classification: [Grab](https://engineering.grab.com/llm-powered-data-classification), [Databricks LogSentinel](https://www.databricks.com/blog/logsentinel-how-databricks-uses-databricks-llm-powered-pii-detection-and-governance), [NVIDIA NeMo](https://docs.nvidia.com/nemo/microservices/25.10.0/generate-private-synthetic-data/synthesize/replace-pii/llm-classification.html)
- Contextual semantic type detection: [Sato, VLDB 2020](https://www.vldb.org/pvldb/vol13/p1835-zhang.pdf)
- Weak supervision: [Stanford SAIL](https://ai.stanford.edu/blog/weak-supervision/)
- Capitalisation and NER false positives: [arXiv 1911.05241](https://arxiv.org/pdf/1911.05241)
- Office-holder lists: [Wikidata every politician](https://www.wikidata.org/wiki/Wikidata:WikiProject_every_politician), [OpenSanctions wd_peps](https://www.opensanctions.org/datasets/wd_peps/)
- India phone number formats: [dial91.com](https://dial91.com/india-phone-number-formats/)
- Legal: [DPDP Act 2023](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf), [s.3(c)(ii) analysis](https://lawschoolpolicyreview.com/2026/01/13/publicly-available-data-under-the-dpdp-act-the-limits-of-exemptions-in-ai-driven-processing/), [NDSAP Implementation Guidelines 2.4](https://www.data.gov.in/sites/default/files/NDSAP%20Implementation%20Guidelines%202.4.pdf), [NIST SP 800-122](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-122.pdf)
