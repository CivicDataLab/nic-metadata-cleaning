# Archival / duplicate / overlap detection on `dublin_core_remaining`

**Status:** prepared and validated locally, **not yet run to completion**. The
embedding pass was aborted at ~5% (92/1840 batches, ~2s/batch on CPU, ETA
~1h45m). Everything upstream of the embedding pass is done and on disk. Pick it
up on the GPU EC2 box.

Date: 2026-08-27 · Table: `dublin_core_remaining` (117,721 rows)

---

## 1. What this pipeline does

Two scripts in this directory, run in order:

| Step | Script | In | Out |
|---|---|---|---|
| 1 | `signature.py` | table export CSV (`nid`, `Title`) | `dataset_signatures*.csv` — adds `metric`, `alternative_metrics`, `modifiers`, `conditions` |
| 2 | `final_archival.py` | signature CSV | `dataset_relations*.csv`, `canonical_datasets*.csv` |

Step 2 embeds each row (MiniLM-L6-v2), does a FAISS top-K neighbour search,
then rule-classifies each surviving pair into one of four `family_type`s:

- `EXACT_DUPLICATE` — same metric, same years, same numbers, fuzzy > 0.99
- `LONGITUDINAL` — same metric/numbers, both have years, fuzzy > 0.92
- `ANALYTICAL_VARIANT` — differing count of variant terms (tribal/rural/urban/male/female/sex/residence) within 1 year
- `RELATED` — ≥ 3 shared non-generic title tokens

`EXACT_DUPLICATE` + `LONGITUDINAL` edges are unioned into a graph; connected
components become "canonical groups" with one canonical (latest-year) member.

---

## 2. Already done — do not redo

### Data export (from `transformation/metadata.db`, DuckDB)

`data/archival_remaining/dublin_core_remaining_.csv` — 49 MB, 117,721 rows:

```sql
COPY (
  SELECT nid, "Title", "Relation[Catalog Title]",
         "Publisher[ministry_department]", Collection, merge_method, new_title
  FROM dublin_core_remaining
) TO 'data/archival_remaining/dublin_core_remaining_.csv' (HEADER, DELIMITER ',');
```

Validated: parses to exactly 117,721 rows, **`nid` is int64 with 0 nulls**, 0
duplicate nids. That last point matters — see the float-nid trap in §6.

### Signatures

`data/archival_remaining/dataset_signatures_remaining.csv` — 70 MB, done.
**Reusable as-is**; step 1 does not need re-running.

### Files on disk

```
data/archival_remaining/
├── dublin_core_remaining_.csv          49 MB  table export      [done]
├── dataset_signatures_remaining.csv    70 MB  step-1 output     [done]
├── run_topk5.log                              aborted run log
└── (outputs land here)
```

`/data/archival_remaining/` was added to `.gitignore` — the export, the
signature CSV and the ~181 MB embeddings cache are all working files and should
not be committed. The three scripts live in this directory and *are* tracked.

---

## 3. Script changes made (uncommitted, in the working tree)

Both scripts had hardcoded input/output filenames pointing at the earlier
`dublin_core_metadata` run. Changes keep every default identical, so existing
invocations behave exactly as before.

**`signature.py`** — added `--input` / `--output`.

**`final_archival.py`**
- added `--input`, `--relations-output`, `--canonical-output`, `--top-k`,
  `--sim-threshold`, `--embeddings-cache`
- **`--embeddings-cache <path.npy>`** — writes embeddings on first run, reuses
  them on later runs when the row count matches the input (guards against a
  stale cache pairing wrong vectors to wrong nids). This makes a re-run at a
  different `--top-k` cheap: FAISS search + relation loop only.
- **perf fix**: the canonical-groups loop did `df[df["nid"] == nid].iloc[0]` —
  a full 117K-row scan *per member per component*. Replaced with a
  `nid -> title` dict built once. This was the real bottleneck, not FAISS.
- added a **TOP_K saturation** diagnostic printed after the search: the share of
  rows where all K returned neighbours still clear `SIM_THRESHOLD`, i.e. where K
  — not similarity — truncated the family.

Line endings: both files are CRLF in git; keep them CRLF or the diff explodes to
a full-file rewrite.

---

## 4. Run it on the GPU box

### Dependencies

`faiss-cpu` and `sentence-transformers` were **missing**; everything else was
present. A `pip install --dry-run` confirmed the install adds only
`faiss-cpu`, `sentence-transformers`, `scikit-learn`, `narwhals`,
`threadpoolctl` — **no numpy/pandas/torch upgrade**. Run the dry-run again on
EC2 before installing: recent wheels are built against numpy 2.x and will
silently break this repo's `numpy 1.26.4` / `pandas 2.1.3` / `torch 2.10` stack
if pip resolves that way.

```bash
python3 -m pip install --dry-run faiss-cpu sentence-transformers   # read the plan first
python3 -m pip install faiss-cpu sentence-transformers
```

On GPU you want CUDA torch (the local box is `torch 2.10.0+cpu`) and optionally
`faiss-gpu` in place of `faiss-cpu`. `sentence-transformers` picks up CUDA
automatically — no code change needed. The model (`all-MiniLM-L6-v2`, ~90 MB)
downloads on first use.

Worth doing on GPU: `batch_size=64` is hardcoded in the `model.encode(...)` call
in `final_archival.py`. Raise it to 512–1024 for GPU throughput.

### Command

```bash
cd /path/to/nic-metadata-cleaning

python3 -u "transformation/archival and relationship code/final_archival.py" \
  --input             data/archival_remaining/dataset_signatures_remaining.csv \
  --relations-output  data/archival_remaining/dataset_relations_remaining.csv \
  --canonical-output  data/archival_remaining/canonical_datasets_remaining.csv \
  --embeddings-cache  data/archival_remaining/embeddings_remaining.npy \
  2>&1 | tee data/archival_remaining/run_topk5.log
```

Step 1 only needs re-running if the table changed:

```bash
python3 "transformation/archival and relationship code/signature.py" \
  --input  data/archival_remaining/dublin_core_remaining_.csv \
  --output data/archival_remaining/dataset_signatures_remaining.csv
```

### Then summarise

```bash
python3 "transformation/archival and relationship code/summarise_run.py"
```

Reports relation counts by family type, duplicate counts with a
same-title/differing-title split, overlap counts, canonical group-size
distribution and largest families, archival-flag counts by ministry, and a
cross-check against literal duplicate titles. Writes
`duplicates_remaining.csv`, `overlaps_remaining.csv`,
`archival_candidates_remaining.csv`.

---

## 5. Deciding TOP_K — the one judgement call

`TOP_K = 5` is likely binding on this corpus. It is full of large near-identical
title families (HMIS item-wise, AHS rounds, per-district series); a family of
200 near-identical titles gets 5 neighbours each, so duplicate recall is
truncated and the component graph fragments arbitrarily.

Two signals, in order of authority:

1. **Ground truth (use this).** `summarise_run.py` prints
   `missed by the pipeline : Z` — nids with a literally identical twin in the
   table that were *not* caught as `EXACT_DUPLICATE`. Identical titles have
   cosine 1.0, so the only way one is missed is that its twin fell outside the
   top-K. **`Z > 0` is proof K is too small.**
2. **Saturation %** printed by the run itself — a proxy. Above ~2% it warns.

If either fires, re-run with `--top-k 25`. With the embeddings cache this skips
the embed pass entirely; the FAISS matmul costs the same and the relation loop
grows ~5×.

Baseline for comparison: 143 literal duplicate-title groups (173 if
case/whitespace-normalised), 168 redundant rows (200 normalised).

---

## 6. Known issues — report these alongside the numbers, don't absorb them

**LONGITUDINAL is undercounted in the relations CSV.** In the relation loop,
`graph_edges` is appended before the direction gate but the relation *rows* are
not:

```python
if family_type == "LONGITUDINAL":
    sy, ty = max(source_years), max(target_years)
    if abs(sy - ty) <= 2:
        if sy < ty:
            relations.append(...)   # only emitted here
```

A detected LONGITUDINAL pair emits zero rows when the gap > 2 years, when
`sy == ty`, or when `sy > ty`. And `seen_pairs` is populated unconditionally, so
the `sy > ty` half is dropped outright — it is never re-derived when the loop
reaches the other member. **The LONGITUDINAL count in
`dataset_relations_remaining.csv` is a lower bound**, roughly half or less of
what was actually detected. `EXACT_DUPLICATE`, `RELATED` and
`ANALYTICAL_VARIANT` go through the `else` branch and are unaffected; canonical
grouping is unaffected because the graph edge was already added. If you do a
second pass, add a counter for `family_type` *before* the direction gate to
recover the true pair count.

**`archival_flag` is not the duplicate signal.** It fires only when *every*
title in a component normalises identically (`unique_titles == 1`). Components
merge `EXACT_DUPLICATE` **and** `LONGITUDINAL` edges — so a pair of identical
titles that has any longitudinal edge to a different-year sibling gets absorbed
into a bigger component, `unique_titles` goes above 1, and every member's flag
goes False. Expect this to suppress most of the 143 literal duplicate groups.
**A near-zero `archival_flag` count is not evidence of no archival candidates.**
Derive archival candidates from `family_type == 'EXACT_DUPLICATE'` — that is
what the downstream flagger consumes.

**Similarity runs on a truncated proxy, not the title.** `signature.py` sets
`modifiers` and `conditions` to `""`, so every embedding text is
`metric | ngrams |  | ` — a constant empty tail across all rows, which uniformly
inflates cosine similarity. And `build_metric` keeps only the **first 6 tokens**,
so titles that diverge past token 6 get identical metrics. `SIM_THRESHOLD = 0.84`
on top of that is loose. This is inherent to the pipeline as written; state it
next to the counts so they are not over-read. `summarise_run.py` surfaces it
concretely via the "examples where titles DIFFER" block under duplicates.

**Float-nid trap (avoided here, watch on re-export).** `nid` is VARCHAR in the
DB. If any exported nid is null, pandas infers float and writes `86585.0` into
the relations CSV. `flag_duplicate_archives.py` joins on
`CAST(nid AS VARCHAR) IN (SELECT CAST(target_nid AS VARCHAR) ...)`, and a `.0`
suffix makes that join match **zero rows with no error**. The current export is
clean (int64, 0 nulls) — re-verify if you re-export.

---

## 7. Context established while preparing this

- **The two Dublin tables are disjoint.** `dublin_core_remaining` (117,721) and
  `dublin_core_metadata` (206,972) share **0 nids and 0 titles**. This is a
  within-table analysis; no cross-table dedup needed.
- **`dublin_core_remaining` has no `archive` / `archive_reason` columns.**
  `dublin_core_metadata` has both. Adding them is a schema change and was
  deliberately left for you to call.
- **Prior run baseline** — `dublin_core_metadata` currently carries
  36 `duplicate`, 5 `Wrong Data`, 1 `Overlap` archived rows (the `duplicate`
  ones set by `transformation/utils/flag_duplicate_archives.py` from
  `/home/aakash/NIC/dataset_relations.csv`). Note `Overlap` is already an
  established `archive_reason` value in this project.
- **`merge_method` mix on remaining** (context for expected family sizes):
  non-mergeable 54,993 · curate 41,134 · direct 16,211 ·
  change_in_header 3,772 · null 1,610 · to be removed 1.

---

## 8. Downstream — after the run, if the numbers look right

`transformation/utils/flag_duplicate_archives.py` writes
`archive = TRUE, archive_reason = 'duplicate'` onto the **target** nid of every
`EXACT_DUPLICATE` pair. Two things before pointing it at this run:

1. It is **hardcoded to `dublin_core_metadata`** and defaults to
   `--csv /home/aakash/NIC/dataset_relations.csv` (the *metadata* run). It needs
   a table parameter, or a copy, to target `dublin_core_remaining`.
2. `dublin_core_remaining` has no `archive` column. The script auto-adds
   `archive_reason` but **not** `archive` — that `ALTER TABLE` is manual.

Back up `metadata.db` before any bulk UPDATE. It has been corrupted twice
before, with bulk UPDATEs the suspect.
