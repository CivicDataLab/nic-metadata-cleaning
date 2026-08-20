# Plan amendment: T4-GPU tier for batch-2 collection detection

> **STATUS 2026-08-11 — the GPU tier was NOT built, and this file's two central
> factual claims did not hold up. Corrections first, original text below.**
>
> 1. **The T4 is on THIS box.** This file says "on an EC2 instance, not this WSL2
>    box — no local NVIDIA driver, torch is CPU-only". Measured here: `nvidia-smi`
>    reports Tesla T4 15360 MiB / driver 535.230.02, `torch 2.7.1+cu118` with
>    `cuda.is_available() == True`, and the host is `Linux 5.15.0-1084-aws`, not
>    WSL2. The parquet handoff, `requirements-gpu.txt` and rsync/scp boundary were
>    therefore struck — no `transformation/gpu/` directory was created.
> 2. **The batch-1 numbers are not reproducible.** This file reports 5,664
>    collections (curate 172,329 rows / 5,627 colls). The database holds **413**;
>    re-running the current `dataset_merge.py` over all 206,946 batch-1 titles
>    produces **886**. No run reproduces 5,664. Batch 1 is over-merged — "Item-wise
>    report" alone holds 131,014 rows — so it was treated as a defect to avoid,
>    not a template.
> 3. **The ~134M-pair residual never materialised.** That estimate came from titles
>    alone, before headers were considered. With headers grouping 93% of rows, the
>    unmatched residual is 15,449 rows (18.6% of non-RS), diffuse across ministries
>    and mostly genuine singletons. The embedding gate was not met.
>
> The one piece of this amendment that proved valuable — its third GPU output,
> flagging groups the deterministic tier merged that do not look alike — was built
> **without a model** as `audit_collections.py`, and found a real defect class
> (57 collections stacking an SC/ST subset on its own superset).
>
> The "GPU only proposes, never decides" hard rule was kept and generalised: every
> guard in the pipeline is deterministic and auditable.

Amends `we-are-detecting-datasets-sprightly-lightning.md` (batch-2 / `remaining-raw-datasets`
collection detection). That plan's decisions, phases 0/2/3/5, and verification stand; this file
records (a) how batch-1 collections are actually built, (b) what the T4 changes, and (c) the
concrete phase amendments.

## Context

User has a T4 GPU (on an **EC2 instance**, not this WSL2 box — no local NVIDIA driver, torch is
CPU-only) and asked whether a model on it can boost collection detection. Also asked to re-review
how `dublin_core_metadata.Collection` was built and adjust the plan accordingly.

## How batch-1 collections are made (reviewed, measured)

Mechanism in `transformation/dataset_merge.py` — **fully deterministic, no ML**:
1. `normalize_title()` — iterated regex strip of trailing temporal slots (quarters, "upto MONTH-YEAR",
   FY ranges…), then geographic slots from a closed STATE_ALT list; dangling-preposition cleanup.
2. `_normalize_key()` — case/plural/separator collapse → group key.
3. `_merge_into_parent()` — folds "PREFIX for/of X" into an existing larger "PREFIX" group
   (catches multi-word districts).
4. `_fuzzy_merge()` — thefuzz `token_sort_ratio ≥ 92` union-find **over group keys** (not titles),
   with a hard `_CONTRASTING_PAIRS` block (rural/urban, boys/girls, sc/st…).
5. `apply()` writes `Collection` + `dataset_merge` (≥2 members); `split_temporal_collections`
   splits (for)/(upto).

Result in DB: 206,972 rows → 205,151 with Collection, **5,664 collections** (curate 172,329 rows /
5,627 colls; Minor-change 28,881/13; major-changes 2,807/20; direct 1,134/4; non-mergeable 1,778).
`merge_add_columns` is dominated by `month, financial year` (141K) and `state,year,month` (30K).

**Why it worked, and why batch 2 is harder**: batch 1 is HMIS-template-dominated, so the regex pass
collapsed ~207K distinct titles into ~6K keys — the O(k²) fuzzy pass was tiny. Batch 2 (now
**116,111 rows / 115,947 distinct titles / 6,149 catalogs**; MHA-Census 36K, Rajya Sabha 33K,
Education 14.6K, NCRB 10.4K, MoSPI/RTH/Jal Shakti…) has far more template diversity; where the
regexes miss, keys stay numerous and within-catalog pairwise comparison is ~**134M pairs**
(20 catalogs >1000 titles account for 109M). That quadratic residual is precisely what the GPU fixes.

Data drift noted vs the original plan: table grew 115,846 → 116,111; NCRB now split from Census;
`spatial_states/districts/subdistricts/level/source` + `file_present` columns already exist
(Spatial_script ran) — the staging transform must carry them.

## What the T4 buys (and doesn't)

**Yes — use the T4 for:**
- **Embedding candidate generation**: encode all distinct normalized title bases
  (`BAAI/bge-small-en-v1.5`, fp16) — ~1–2 min for 116K on a T4. Per-(ministry, catalog) block
  top-k (k≈20) neighbor search via GPU matmul (largest block ≪ 16GB). Replaces the infeasible
  O(n²) fuzzy pass on residual keys.
- **Cross-encoder verification** (`BAAI/bge-reranker-base`): rescore the ambiguous cosine band;
  ~1M pairs ≈ 30–60 min on T4, infeasible on CPU.
- This **promotes research-doc Stage 2 from contingency to default** — it now costs minutes, so it
  runs as both a residual-grouper and a QA cross-check on deterministic groups.

**No — don't use the T4 for:**
- The deterministic tier, downloads, header extraction (I/O + CPU bound).
- **LLM judging** (user asked for the comparison): ~50–100K borderline pairs ≈ 50–100M tokens.
  OpenAI batch on gpt-5.4-nano with the ≥2048-token cached prompt ≈ **$5–10 total**, infra already
  exists (`llm_batch_classifier`, temp 0 / seed 42, enqueue-cap lessons learned). Local
  Qwen2.5-7B-AWQ on the T4 ≈ $5–8 of g4dn time (10–15 h; Turing → no flash-attn) with *lower*
  judgment quality and new vLLM setup work. **Verdict: OpenAI batch**; Phase 4's gold set
  (~200–400 labeled pairs) doubles as an empirical check — optionally run the local 7B on just the
  gold set for a concrete accuracy comparison before committing.

**Hard rule**: GPU similarity only *proposes*, never *decides*. Embeddings deliberately ignore
exactly the tokens we strip (geo/temporal) — good — but also under-weight contrasting tokens
(boys/girls, SC/ST). Every proposed pair passes the `_CONTRASTING_PAIRS` guard + slot check
(differing tokens must be geo/temporal/known-slot to auto-accept; else `needs_review`), and
merge_method is still only confirmed by headers (Phase 3).

## Phase amendments (deltas to the original plan)

**Phase 0 (staging)** — unchanged, plus: carry the new `spatial_*` / `file_present` columns into
the staging mapping.

**Phase 1 (title-first grouping)** — unchanged deterministic pass (extend regexes, block per
ministry+catalog), then add:

- **1b. GPU candidate tier** (new, portable to EC2 — this box has no GPU):
  - `transformation/gpu/export_titles_parquet.py` (runs here): dump
    `(nid, title, catalog_title, ministry_department, norm_base, proposed_collection)` from staging
    to parquet after the deterministic pass.
  - `transformation/gpu/embed_candidates.py` (runs on EC2; **DB-free**, parquet in → parquet out;
    pinned `requirements-gpu.txt`; rsync/scp handoff): embed bases → per-block top-k cosine pairs →
    three outputs: (i) high-confidence new pairs (cos ≥ ~0.95 and passes guards), (ii) ambiguous
    band rescored by cross-encoder, (iii) QA flags where the deterministic pass co-collected but
    cosine is low (< ~0.75) — likely over-merge.
  - `transformation/gpu/apply_candidate_pairs.py` (runs here): union-find accepted pairs into
    proposed collections, apply contrasting-pair + slot guards, write
    `gpu_candidate_collection` / `gpu_flag` columns to staging + review xlsx. Never writes
    `Collection` directly.
- Rajya Sabha stays excluded from dataset-level grouping (catalog-consolidation only), so the
  worst 33K-title block never enters the pair search.

**Phase 3 (headers confirm)** — unchanged; headers remain the arbiter that upgrades proposals to
`direct`/`curate`.

**Phase 4 (residual + judge)** — reworded: Stage 2 is already done (Phase 1b). Remaining:
- Borderline band after cross-encoder → **OpenAI batch judge** via existing `llm_batch_classifier`
  infra (fix the `OFFSET 500` no-ORDER-BY bug first, as in original plan).
- Gold set (~200–400 pairs, Education + MHA): measure deterministic-tier and GPU-tier precision
  (target ≥0.95); run the OpenAI judge on it, and optionally Qwen2.5-7B on the T4 on the same set
  for the requested accuracy/cost comparison table.

**Phase 5 (catalog consolidation / review / merge-in)** — unchanged.

## Key files
- Modify (as in original plan): `dataset_merge.py`, `metdata_transform_dublin.py`,
  `dataset_headers.py`, `utils/{title_components,set_merge_method,detect_merge_add_columns,
  extract_temporal_from_title,add_header_count,split_collections_by_header_group}.py`.
- New: `transformation/gpu/{export_titles_parquet,embed_candidates,apply_candidate_pairs}.py`,
  `transformation/gpu/requirements-gpu.txt` (torch-cu121, sentence-transformers, pyarrow).

## Verification
- Original plan's per-phase sanity SQL + dry-runs stand.
- GPU tier: `embed_candidates.py --self-test` on a 1K-title sample locally (CPU fallback path) before
  shipping to EC2; on return, assert every accepted pair is same-(ministry,catalog), no
  contrasting-pair violations, and spot-check 40 proposed collections + all QA over-merge flags.
- Gold-set precision gates any auto-acceptance; judge-model comparison reported from the same set.
