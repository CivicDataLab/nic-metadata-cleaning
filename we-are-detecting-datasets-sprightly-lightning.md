# Plan: Collection / merge detection for batch 2 (`remaining-raw-datasets`)

> **STATUS 2026-08-11 — implemented. This plan's premise was wrong in three ways;
> corrections below, then the original text is kept for reference.**
>
> 1. **Batch 2 already has headers.** The plan is built on "No headers yet … only
>    ~2,770 of ~115K files downloaded", which drives the whole title-first /
>    downloads-in-parallel design. In fact `Conforms To` holds real header lists
>    for **108,362 of 116,111 rows (93%)**, straight from source metadata. Headers
>    became the PRIMARY grouping signal; downloads never entered the critical path.
> 2. **The temporal axis is in metadata, not titles.** `data_time_period_from/to`
>    is populated on **all** 116,111 rows, so the "UDISE case" the plan treats as a
>    special fallback is the general case.
> 3. **The staging table is `dublin_core_remaining`**, not `dublin_core_metadata_b2`,
>    and it already existed. Batch-1 scripts named here as needing only a `--table`
>    argument mostly did not exist and had to be written.
>
> Also: batch 1 is **not** a template to copy. It stores 413 collections, one of
> which ("Item-wise report") holds 131,014 rows — 63% of the table. See the
> amendment file for the reconciliation.
>
> Final batch-2 state (116,111 rows): direct 48,867 · curate 18,658 (3,361
> collections) · non-mergeable 33,137 (Rajya Sabha) · unmatched 15,449. All nine
> sanity checks pass. Code in `transformation/dataset_merging/`, reports in
> `transformation/dataset_merging/reports/`.

## Context

Batch 1 (206,972 rows in `dublin_core_metadata`, HMIS/health-dominated) went through a collection-detection
pipeline: title normalization stripped temporal/geographic slots to group datasets into `Collection`s
(`dataset_merge.py`), exact header groups got `merge_method='direct'`, collections got `'curate'`
(`utils/set_merge_method.py`), `utils/detect_merge_add_columns.py` computed which dimension columns
(year/state/district) a curate merge must add, and 365 catalogs were consolidated into 14 `new_catalog_title`s.
Header-variation edge cases were handled by split/unflag/minor-change utils.

Batch 2 is the `remaining-raw-datasets` table in `transformation/metadata.db` (DuckDB): **115,846 rows, zero
nid overlap with batch 1**. Goal: detect vertically-mergeable datasets (same headers → direct merge; same
headers after adding a month/year/state/district/etc. column inferred from title/metadata → curate merge),
producing the same `Collection` / `merge_method` / `merge_add_columns` outputs — informed by the research
writeup (`compass_artifact_...markdown.md`).

## What batch 2 looks like (measured)

- Ministries: Home Affairs/Census 46,673 · Rajya Sabha 33,170 · Education/UDISE+ 15,412 · Housing & Urban
  Affairs 5,292 · MoSPI 2,773 · Road Transport 2,678 · Jal Shakti 2,249 · rest <2K each.
- `catalog_title` is a strong blocking key: 6,417 catalogs; 96% of rows share a catalog; 71% in catalogs >100.
- **No headers yet**: no `Conforms To`; only ~2,770 of ~115K files downloaded (`data/final_batch_downloads/`,
  log `data/final_dataset_download_log.csv`; ~91% success on attempts; 112K rows are csv/xls, rest json/xml/zip).
- New title shapes vs batch 1 (HMIS-tuned regexes won't catch these):
  - UDISE: "Enrolment … in Adilabad District of Telangana (UDISE plus)" — trailing "(UDISE plus)" defeats the
    `$`-anchored geo-strip; **FY is only in `data_time_period_from/to`** (identical titles repeat across years).
  - Census/MHA: "… for Scheduled Caste (Each Caste Separately) for Bathinda District …", "…, Census 1991 -
    India and States" — district/caste/census-year slots.
  - Rajya Sabha: catalogs are per-session ("Answers Data … Session 256") holding thousands of unrelated
    one-off answer tables.

## Decisions (confirmed with user)

1. **Title-first, headers confirm** — group now from catalog_title + title templates + temporal metadata;
   downloads run in parallel; headers later confirm/refine merge_method.
2. **Rajya Sabha: catalog-consolidation only** — default non-mergeable; recurring exact-header tables across
   sessions may surface true series later.
3. **Deterministic first, measure the residual** — embeddings/LLM-judge (research-doc Stages 2–3) only if the
   ungrouped remainder is large.
4. **New staging table** for batch 2 — do not touch `dublin_core_metadata` during detection.
5. Batch numbers are only transformation chunking, not semantic.

## Architecture

Staging table `dublin_core_metadata_b2` mirroring the full current `dublin_core_metadata` schema (77 cols,
incl. Collection / merge_method / merge_add_columns / needs_review / Conforms To / Temporal cols /
new_catalog_title / exact_merge_group_name). All batch-1 scripts get a `--table` (and where relevant
`--download-dir`) argument defaulting to their current constants — this also removes the foot-gun that
`detect_merge_add_columns.py` and `set_merge_method.py` run whole-table UPDATEs (a global reset would have
clobbered batch-1 values).

## Phases

### Phase 0 — Staging setup
1. Back up `metadata.db` (corruption history — memory note).
2. Adapt `transformation/metdata_transform_dublin.py`: add `--source-table/--target-table`; pre-rename shim
   (`Access_Type→Access Type`, `Reference_url→Reference Url`, `field_high_value_dataset_value→field_high_value_dataset`);
   map `data_time_period_from/to → Temporal Coverage`; create staging with full dublin schema
   (`INSERT … BY NAME`, missing cols NULL).
3. Add `--table` args to: `dataset_merge.py`, `utils/set_merge_method.py`, `utils/detect_merge_add_columns.py`,
   `dataset_headers.py` (+ `--download-dir data/final_batch_downloads/`), `utils/extract_temporal_from_title.py`,
   `utils/add_header_count.py`.

### Phase 1 — Title-first grouping (starts immediately; no headers needed)
1. **Extend the shared regex layer** (`dataset_merge.py` constants + `utils/title_components.py`):
   - STATE_ALT: add Ladakh, merged "Dadra and Nagar Haveli and Daman and Diu", NCT of Delhi variants.
   - New district patterns: "in/for <DISTRICT> District of <STATE>"; state-suffix before a trailing
     parenthetical (handle "(UDISE plus)" by stripping known constant suffixes before geo-strip, then
     re-appending to the collection base).
   - New temporal shapes: "Census <YEAR>", "As On <date>", "from <FY> to <FY>", "Session <N>" (session
     treated as a slot for RS titles only), "(in reply to … Question on <date>)".
   - Keep the contrasting-pair guard; extend with batch-2 pairs (e.g. Scheduled Caste vs Scheduled Tribe already
     covered by sc/st; add boys/girls variants seen in UDISE if needed).
2. **Blocking**: run `build_collection_map` per `(ministry_department, catalog_title)` block instead of
   globally — keeps the O(n²) fuzzy pass tiny and prevents cross-catalog false merges. (Catalog-level
   consolidation happens later in Phase 5, as batch 1 did with `new_catalog_title`.)
3. **Temporal columns**: run `extract_temporal_from_title` logic into staging; **add fallback: derive
   Financial_Year/Year from `data_time_period_from/to`** when the title has no temporal phrase (the UDISE case).
4. **Rajya Sabha**: excluded from dataset-level grouping; rows default `merge_method='non-mergeable'`
   (revisited in Phase 3.4).
5. Output: per-ministry dry-run reports (collections, sizes, singletons) + review xlsx like batch 1's
   `curate_datasets.xlsx` workflow.

### Phase 2 — Downloads + header extraction (parallel, ongoing)
- Continue `scripts/dataset-download.py` / `scripts/retry_failed_downloads.py` over remaining ~110K csv/xls
  uuids into `data/final_batch_downloads/`.
- Wave order = review priority: Education (UDISE) → MHA/Census → Jal Shakti/MoSPI/others → RS last.
- As files land per wave: `dataset_headers.py --table … --download-dir …` → `Conforms To`, `headers_cleaned`;
  `add_header_count.py` → `header_count`.

### Phase 3 — Headers confirm / refine (per wave, once headers exist)
1. **Exact track**: reuse `transformation/dataset_vertical_merge_exact.py` (add `--table`) — exact
   `Conforms To` equality + matching normalized title base + standalone temporal column in the signature →
   `exact_merge_group_id/name`; then `set_merge_method.py --table` (`direct` supersedes and clears Collection;
   `curate` = has Collection; NULL otherwise). `utils/dataset_headers.py::header_signature()` (normalized,
   serial-column-dropped) is the shared signature helper for the fuzzy-equality checks.
   Before this: recover `unflag_varying_header_collections.py` — it is referenced as an ordering-critical
   step in `set_merge_method.py`'s docstring but absent from the tree (check `git log --diff-filter=D`,
   backups); reconstruct if unrecoverable (memory: it removes dataset_merge from schema-incoherent
   collections, runs after dataset_merge.py).
2. `detect_merge_add_columns.py --table` → `merge_add_columns` + `needs_review`; **extend its axis detection
   so the year axis can come from the staging Fiscal_Year/Year columns** (UDISE: identical titles, temporal
   axis only in metadata), not only `parse_title_components`.
3. Header-variation handling, same order as batch 1: unflag varying-header collections → split-by-header-era
   (`utils/split_collections_by_header_group.py`) → minor-change-in-header union (strip FY from headers,
   keep ONE collection).
4. **RS exception scan**: exact normalized header-sets recurring across ≥2 sessions → candidate real series →
   flip those from non-mergeable to curate with a Collection.

### Phase 4 — Measure the residual, then decide on ML stages
- Metrics per ministry: % rows in multi-member collections, direct/curate/non-mergeable split, singleton count.
- Spot-check gold set (~200–400 pairs, per research doc) on Education + MHA; target precision ≥0.95 on the
  deterministic tier.
- Only if the residual is large / precision poor: add research-doc Stage 2 (bge-small embeddings, MinHashLSH,
  Leiden) and Stage 3 (LLM-judge on borderline pairs). Otherwise skip.
- LLM naming pass as in batch 1: `llm_collection_classifier.py` (needs `--table`; reads
  `WHERE Collection IS NOT NULL`) for collection titles/descriptions/themes; `run_nids_classifier.py` for
  leftover nid subsets (sequential, enqueue-cap lesson from memory).
  **Fix first**: `llm_batch_classifier.load_rows()` appends `OFFSET 500` without ORDER BY whenever `--batch`
  is set — silently drops 500 rows (batch-1 artifact).

### Phase 5 — Catalog consolidation, review, merge into main
- `catalog_title → new_catalog_title` consolidation: all RS session catalogs → one "Rajya Sabha Questions and
  Answers"; UDISE / Census / habitation families grouped like batch 1's 365→14.
- Curation round-trip as in batch 1: `utils/export_dublin_metadata.py --where "merge_method='curate'"
  --sheet-by merge_add_columns` → human edits (values like `group based on state` and `non-mergeable` were
  human-entered in batch 1, not scripted) → sync back via the (currently commented) Curate-sheet block in
  `transformation/import_csv.py` (~L146-220), pointed at the staging table.
- After review of split-by-header-era output (`utils/split_collections_by_header_group.py` reads the
  `collection` table prepared by `extract_temporal_from_title.py`): apply renames.
- Final: fresh backup, then `INSERT … BY NAME` staging → `dublin_core_metadata` with new batch numbers.

## Verification
- Every script has/keeps `--dry-run`; run dry first per ministry and eyeball top-40 collections.
- Sanity SQL after each phase: no collection spans ministries; every `direct` row shares an identical
  normalized header set with its group; every `curate` collection has ≥2 members and merge_add_columns or
  needs_review set; RS rows outside rescued series stay non-mergeable.
- Compare batch-2 distribution shape against batch 1 (curate-dominant expected).
- Gold-set precision measured in Phase 4 before any auto-merge is trusted.

## Key files
Modify: `transformation/dataset_merge.py`, `transformation/metdata_transform_dublin.py`,
`transformation/dataset_headers.py`, `transformation/utils/{title_components, set_merge_method,
detect_merge_add_columns, extract_temporal_from_title, add_header_count, split_collections_by_header_group}.py`.
New: staging-load wrapper, per-ministry report script, RS catalog-consolidation + exception-scan script.
