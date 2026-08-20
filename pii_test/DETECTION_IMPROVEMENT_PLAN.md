# Improving PII Detection Precision (LOT 2)

Plan to fix the false-positive rate in the LOT 2 PII scan, written against
evidence from the 1,120,818 detections currently in `pii_detections_lot2`.

Reference case: `00215472-af1c-48c3-8009-2f524dd22a19`
(`ministry-of-education`) — an aggregate table of school infrastructure counts
per district/block. It contains **no personal data of any kind**, yet produced
21 detections, all false.

---

## 1. What the evidence says

### 1.1 The reference dataset

The file is 65 rows of counts keyed by administrative unit. Columns are
academic year, state/district/block codes and names, school category,
management type, location, and ~30 integer facility counts. Its 21 detections:

| column | entity | text | score | count |
|---|---|---|---|---|
| `Location` | PERSON | `Urban` | 0.997 | 17 |
| `Udise_Block_Name` | PERSON | `KHIMYANG` | 0.694 | 4 |

`Urban` is a two-valued category. `KHIMYANG` is a census block. Neither is a
person, and no filter in the current pipeline is positioned to reject either.

### 1.2 The corpus-wide picture

| metric | value |
|---|---|
| Total detections | 1,120,818 |
| PERSON, from Presidio/NER | 1,120,530 (**99.97%**) |
| PHONE_NUMBER / EMAIL_ADDRESS | 288 (0.03%) |
| Distinct `entity_text` values | 7,429 |
| Detections from the top 1,000 strings | 1,064,069 (**94.9%**) |
| Detections from the single string `Urban` | 525,497 (**46.9%**) |

Top offenders, all false:

| text | detections | datasets | avg score |
|---|---|---|---|
| `Urban` | 525,497 | 8,762 | 0.997 |
| `B.El` | 94,400 | 3,367 | 0.850 |
| `M.Phil` | 45,908 | 3,033 | 0.996 |
| `Ph.D` | 30,715 | 2,814 | 0.676 |
| `Kendriya Vidyalaya / Central School` | 18,024 | 4,150 | 0.850 |
| `Jawahar Navodaya Vidyalaya` | 8,715 | 3,726 | 0.850 |
| `RAJGARH`, `SHAHBAD`, `KALOL`, `DADRI`, … | ~1,000 each | | 0.850 |

These are location categories, academic qualifications, school-scheme names,
and place names — four closed vocabularies, not people.

### 1.3 Detections are concentrated in structurally non-PII columns

| column | detections | % of total | distinct values |
|---|---|---|---|
| `loc_name` | 261,994 | 23.4% | **1** |
| `Location` | 261,168 | 23.3% | 475 |
| `Udise_Block_Name` | 137,453 | 12.3% | 1,111 |
| `block_name` | 121,024 | 10.8% | 1,300 |
| `Professional_Qualification_Name` | 94,398 | 8.4% | **1** |
| `Academic_Qualification_Name` | 76,621 | 6.8% | **2** |
| `School_Management_Name` | 32,735 | 2.9% | **3** |
| `Block_Name` | 28,980 | 2.6% | 1,168 |
| `udise_block_name` | 28,187 | 2.5% | 1,213 |
| `sch_mgmt_name` | 17,167 | 1.5% | **3** |

**98.7%** of all detections come from columns whose names match geography,
qualification, management, or category patterns. Several produce six-figure
detection counts from **one to three distinct values** — the definition of a
categorical column.

### 1.4 Confidence score is not a usable filter

| score band | detections | share |
|---|---|---|
| ≥ 0.95 | 625,255 | 55.8% |
| 0.85 – 0.95 | 366,507 | 32.7% |
| 0.70 – 0.85 | 66,860 | 6.0% |
| < 0.70 | 62,196 | 5.5% |

`Urban` scores **0.997**. The models are confidently wrong, so raising
`filter_person_detection`'s 0.6 threshold cannot fix this — it would discard
genuine low-confidence names while keeping the worst offenders.

---

## 2. Two concrete bugs in `select_detection_columns`

`pii_utils.py` matches skip keywords as bare substrings:

```python
if any(kw in col.lower() for kw in skip_column_keyword):
```

### Bug A — separators defeat the skip list (precision)

The list contains `blockname` and `districtname`, but real headers use
separators:

| column | intended | actual |
|---|---|---|
| `BlockName` | skip | skipped |
| `Block_Name` | skip | **scanned** |
| `block_name` | skip | **scanned** |
| `Udise_Block_Name` | skip | **scanned** |

Block-name columns alone account for ~28% of all detections. The intent to
skip them was already in the code; only the matching was wrong.

### Bug B — bare `id` silently skips real name columns (recall)

`id` matches as a substring anywhere, so these are never scanned at all:

| column | skipped via | consequence |
|---|---|---|
| `Guide_Name` | `id` (gu**id**e) | names never scanned |
| `President_Name` | `id` (pres**id**ent) | names never scanned |
| `Resident_Name` | `id` (res**id**ent) | names never scanned |
| `Bidder_Name` | `id` (b**id**der) | names never scanned |
| `Candidate_Name` | `date`, `id` | names never scanned |

This is the more serious of the two. It causes **silent false negatives** in
exactly the columns most likely to hold personal names, and nothing in the
output distinguishes "scanned, clean" from "never scanned".

---

## 3. Plan

Ordered by impact per unit of effort. Each stage is independently shippable
and independently measurable.

### Stage 1 — Fix column selection (`pii_utils.py`)

Replace substring matching with normalised token matching.

- Normalise headers: lowercase, split on `_`, `-`, `.`, whitespace, camelCase.
- Match against whole tokens, not substrings. Fixes Bug B (`guide` no longer
  contains a `id` token) and Bug A (`udise_block_name` → `{udise, block, name}`
  matches the `block` token).
- Rebuild the skip list around tokens: `block`, `district`, `state`, `village`,
  `city`, `town`, `ward`, `panchayat`, `tehsil`, `location`, `loc`,
  `qualification`, `management`, `mgmt`, `category`, `type`, `medium`,
  `stream`, `subject`, `status`, `code`, `id`, `sno`, `serial`, `year`,
  `month`, `date`, `time`, `pincode`.
- Add a **positive** list that forces scanning regardless of skip rules, so
  geography tokens can't suppress a genuine name column: `name` combined with
  a person token (`father`, `mother`, `guardian`, `candidate`, `applicant`,
  `beneficiary`, `student`, `teacher`, `employee`, `officer`, `owner`,
  `holder`, `contact`, `person`), plus `email`, `mobile`, `phone`, `aadhaar`.
- Log every skipped column and its reason, so recall loss is visible rather
  than silent.

**Expected:** removes the bulk of the ~28% from block columns and the
`loc_name`/`Location` share, and restores scanning of `*_Name` person columns.

### Stage 2 — Reject categorical columns by cardinality

A column with 1–3 distinct values repeated over thousands of rows is an enum,
never free-text names. Measured on the reference file:

| column | distinct | rows | ratio |
|---|---|---|---|
| `State_Name` | 1 | 65 | 0.015 |
| `Location` | 2 | 65 | 0.031 |
| `Udise_Block_Name` | 7 | 65 | 0.108 |
| `School_Category_Name` | 8 | 65 | 0.123 |

Genuine person-name columns approach ratio 1.0 (names rarely repeat).

Rule, applied in `select_detection_columns` on a sample of the column:
skip when `distinct <= 12` **and** `distinct/rows < 0.20` **and** `rows >= 25`.
The row floor prevents small files from being wrongly skipped. This alone
would eliminate `loc_name` (1 value / 261,994 detections),
`Professional_Qualification_Name` (1), `Academic_Qualification_Name` (2),
`School_Management_Name` (3) and `sch_mgmt_name` (3).

### Stage 3 — Gazetteer rejection for place names and closed vocabularies

Because only 7,429 distinct strings exist and 1,000 cover 94.9%, a lookup
table is both feasible and highly effective.

- Build a rejection gazetteer from authoritative lists already in the repo /
  the catalogue: Indian state, district, block, sub-district and city names
  (available from `remain_raw_metadata`'s `spatial_states` /
  `spatial_districts` / `spatial_subdistricts` columns).
- Add closed vocabularies for the observed categories: qualifications
  (`B.El`, `B.Ed`, `M.Phil`, `Ph.D`, `M.Ed`, …), school schemes
  (`Kendriya Vidyalaya`, `Jawahar Navodaya Vidyalaya`, …), management types,
  and location categories (`Urban`, `Rural`).
- Apply in `pii_filters.filter_person_detection` with normalisation
  (casefold, strip punctuation, collapse whitespace) so `URBAN`/`Urban` and
  `Ph.D`/`PhD` both match.
- Replace the KCC-specific `ENGLISH_DOMAIN_BLOCKLIST` with this structure;
  keep the existing agricultural terms as one vocabulary among several.

**Expected:** removes the remaining place-name long tail (`RAJGARH`,
`THOUBAL`, `JAISALMER`, …) that survives Stages 1–2.

### Stage 4 — Require corroboration for a dataset-level PII flag

Currently one PERSON hit sets `pii_detected = TRUE`, which is why 13,833 of
15,392 education datasets (90%) are flagged. Raise the bar for the
*dataset-level* flag while keeping all raw detections in the table:

- A PERSON-only signal flags the dataset only if the column survives Stages
  1–3 **and** the column's value cardinality looks name-like (ratio > 0.5).
- Any regex-sourced hit (AADHAAR, PAN, phone, email) flags immediately —
  these are high-precision and currently only 288 detections total.
- Store the reason for the flag so a reviewer can see what triggered it.

### Stage 5 — Measure, with a labelled set

None of the above should be trusted without a baseline.

- Hand-label ~200 datasets sampled across ministries: does it contain PII,
  yes/no. Include the reference dataset and a deliberate mix of the
  known-clean aggregate tables and any genuine name-bearing files.
- Record precision / recall before and after each stage; require that recall
  on the known-positive subset does not drop.
- Add unit tests to `pii_filters.py` (which already has a `__main__` harness)
  covering: `Urban`, `KHIMYANG`, `M.Phil`, `Kendriya Vidyalaya`, plus genuine
  names that must survive (`Rahul Kumar`, `राहुल कुमार`).

### Stage 6 — Re-run and compare

- Reset `pii_tested` and re-scan; keep the current table as
  `pii_detections_lot2_baseline` for side-by-side comparison.
- Report detections per ministry before/after and spot-check the largest
  remaining clusters — any string still appearing >1,000 times is a candidate
  for the gazetteer.

---

## 4. Also worth fixing while in here

- **`_scan_s3_csv` discards good results on NER failure.** In
  `run_pii_s3.py`, a raised exception from `batch_analyze_cells` sets
  `cache = {}`, dropping the CPU Presidio results along with the failed GPU
  NER output. It should preserve whatever succeeded and record that the file
  was scanned in degraded mode.
- **Stale per-ministry parquet files** in `pii-results-lot2/<ministry>/`
  predate the `ministry` column and are no longer refreshed. Delete or
  regenerate them so they aren't mistaken for current data.
- **The LOT 2 run is incomplete** — 5 of 11 ministries. Finish it *after* the
  filters improve, to avoid scanning ~90k datasets twice.

---

## 5. Expected outcome

98.7% of current detections come from columns that Stages 1–2 are designed to
reject outright, and the residue is dominated by a closed vocabulary that
Stage 3 targets. The reference dataset should produce **zero** detections:
`Location` is rejected by both the token skip list and the cardinality rule;
`Udise_Block_Name` by the `block` token, the cardinality rule, and the
gazetteer.

The measurement in Stage 5 is what makes this real. Until the labelled set
exists, "precision improved" is an assertion, not a result — and the recall
side (Bug B) matters more than the precision side, because a missed name is a
worse outcome here than a flagged block name.

---

## 6. Implementation status

Stages 1–4 and 6's tooling are implemented; the re-scan itself has not been
run. Results below come from replaying the existing 1,120,818 detections
through the new code (`evaluate_filters.py`) plus live scans of three real
datasets.

| stage | state | where |
|---|---|---|
| 1 — token column selection | done | `pii_utils.classify_column_name` |
| 1b — skip reasons logged | done | `select_detection_columns(return_skipped=True)`, `run_pii_s3.log_column_selection` |
| 2 — cardinality rejection | done | `pii_utils._column_skip_reason` |
| 3 — gazetteer | done | `build_gazetteer.py` → `gazetteer/place_names.txt`, `pii_filters.rejection_reason` |
| 4 — flag corroboration | done | `pii_filters.evaluate_dataset_flag`, new `remain_raw_metadata.pii_flag_reason` |
| 5 — unit tests | done | `python pii_test/pii_filters.py` (35 cases, exits non-zero on failure) |
| 5 — labelled set | **scaffolded, not labelled** | `evaluate_filters.py --write-label-template` / `--labels` |
| 6 — baseline + reset | tooling done, **not run** | `reset_lot2_run.py`, `evaluate_filters.py --compare-baseline` |

### Measured effect (replay over the existing detections)

| | detections | share |
|---|---|---|
| baseline | 1,120,818 | 100% |
| removed by column selection | 1,112,094 | 99.2% |
| removed by entity filters | 3,297 | 0.3% |
| **surviving** | **5,427** | **0.5%** |

Entity-filter rejections break down as location-category 2,476, place-name
699, qualification 121, generic 1.

**Reference dataset `00215472-…`: 21 → 0 detections.** `Location` and
`Udise_Block_Name` are both rejected at the column stage.

### Recall went up, not down

Live re-scan of `581bc9f5-1559-4e4e-bb0d-78bb3d1c9974`
(`ministry-of-education`, a university contact directory):

| column | before | after |
|---|---|---|
| `Name of Vice-Chancellor/…/Head` PERSON | 348 | 343 |
| `Name of Institution` PERSON | 107 | 0 (organisation, correctly dropped) |
| `Contact No` PHONE_NUMBER | **0** | **495** |
| `E-mail id` EMAIL_ADDRESS | **0** | **239** |

734 pieces of genuine, regex-verifiable PII in a single dataset that the old
pipeline never saw. `E-mail id` was skipped by Bug B (the bare `id`);
`Contact No` was skipped because phone numbers parse as an integer column and
the numeric-dtype check discarded it. Force-scan columns now bypass the
dtype checks for exactly this reason.

### Deviations from the plan as written

- **Organisation tokens added to the skip list** (`university`, `institution`,
  `college`, `school`, `bank`, `office`, …). Not in the original list, but
  after geography was excluded these were the largest remaining source of
  PERSON false positives, and organisation names are not personal data.
  Person tokens still override them, so `Name of Vice-Chancellor/…` survives.
- **Force-scan columns bypass the numeric/date/cardinality checks.** Needed
  for the `Contact No` case above.
- **Substring matching kept for single-token headers only**, and only for
  tokens ≥ 5 characters, so `blockname` and `fathername` still match while
  `id` inside `Guide_Name` cannot. Concatenated typos (`instituionname`)
  remain unmatchable at the token level.
- **`filter_person_detection` no longer substring-matches the blocklist.**
  The old `any(phrase in text_lower …)` rejected the real name `Maurice` for
  containing the crop `rice`. Multi-word entries are now matched as whole
  token subsequences; single-word entries only against the whole string.

### What is still outstanding

1. **The labelled set is not labelled.** `--write-label-template` produces
   201 rows (200 sampled + the reference dataset); `has_pii` has to be filled
   in by inspection before precision/recall are real numbers rather than the
   replay counts above.
2. **The re-scan has not been run.** `pii_detections_lot2_baseline`
   (1,120,818 rows) and `remain_raw_metadata_pii_baseline` (19,191 rows) are
   in place, so `reset_lot2_run.py --confirm` followed by
   `run_pii_s3.py --lot2` is safe to run whenever wanted. It is ~90k datasets
   on one T4.
3. **6 of 11 ministries were never scanned at all** — that gap is unchanged.
4. **Stale per-ministry parquet files** in `pii-results-lot2/<ministry>/`
   predate the `ministry` column; kept deliberately, but they will be
   superseded rather than updated by a re-scan.
