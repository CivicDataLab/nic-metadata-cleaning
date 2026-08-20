# Script Update Plan — PII Detection Accuracy (Round 2)

Concrete changes to `pii_test/`, derived from `FP_ANALYSIS_ROUND2.md` (evidence)
and `DETECTION_IMPROVEMENT_PLAN.md` (prior round). Current state:
`pii_detections_lot2` holds 40,695 detections, ~95% false; the run covers 26%
of the corpus (29,818 / 116,111 datasets).

Ordered by leverage. Steps 1–4 are small code changes; 5–7 are the data work;
8–9 are measurement and the re-run. Each step names its files, the exact edit,
and how to check it.

---

## 1. Fix subword fragmentation — `pii_utils.py:59`

**Change:** `aggregation_strategy="simple"` → `aggregation_strategy="average"`.

`simple` merges adjacent tokens only when B-/I- tags agree, so a single word
whose SentencePiece pieces get different tags is emitted as several entities
(`JHUNJHUNUN` → `J` + `HUNJHUNUN`). This is a documented behaviour, not a bug
in our code: the HF pipeline's word-level strategies (`first`/`max`/`average`)
exist precisely because `simple` "cannot be word-level" — see the
[pipeline source](https://github.com/huggingface/transformers/blob/main/src/transformers/pipelines/token_classification.py),
[HF issue #12593 "XLM-RoBERTa NER extraction breaks/splitting the words"](https://github.com/huggingface/transformers/issues/12593)
and [issue #23322](https://github.com/huggingface/transformers/issues/23322).
Word-level strategies need a fast tokenizer; XLM-R and MuRIL both load fast
tokenizers under transformers 4.53, so this is available.

Why `average` and not `first`/`max`: all three de-fragment, but `max` and
`first` keep `simple`-style inflated scores. Measured on 31k known-true names
vs 1.5k known-false village names (FP_ANALYSIS_ROUND2 §1.2), `average` at
matched 85% recall keeps 2.4× fewer FPs than `simple`; at 80%, 4.3× fewer.

Apply the same change to both models (the `HfNerPipeline` constructor is
shared, so it is one line). **Everything downstream shifts:** span boundaries,
scores, and which strings reach the filters. Steps 2 and 8 re-calibrate.

**Check:** the reproduction one-liner in FP_ANALYSIS_ROUND2 §4 returns whole
words; re-scan of `c1418789…` shows partial-word PER spans drop from ~42% to
~2% on `Village Name`.

## 2. Re-tune the PERSON score threshold — `pii_filters.py`

The 0.6 floor at `pii_filters.py:280` was set under `simple`'s inflated
scores, and the module docstring (lines 5–8: "a score threshold cannot
separate them") encodes a conclusion that was an artifact of the
fragmentation bug.

- Promote the floor to a named constant `PERSON_SCORE_FLOOR` and re-tune it
  against the TP set (`581bc9f5…` names) and FP set (`c1418789…` villages)
  **after** step 1. Expected landing zone 0.64–0.72 — tune, don't assume.
- Rewrite the module docstring: scores separate under word-level aggregation;
  the vocabularies handle what the threshold can't.
- Keep the threshold applying only to the NER path (`source == "presidio"`);
  regex stays exempt as today.

**Check:** `evaluate_filters.py` replay + a live scan of both fixtures; TP
recall on the VC column must stay ≥ current 343 detections at whatever floor
is chosen.

## 3. Negative bigrams for person tokens — `pii_utils.classify_column_name`

`head` and `mother` in `PERSON_NAME_TOKENS` (`pii_utils.py:212`) force-scan
`Sub District Head Quarter (Name)` (12,323 detections) and
`Mother Tongue Name` (2,005) — 35% of the table. The override can't be
removed (the genuine `…/Registrar/Director/Head` column depends on it), so
cancel it only in known compounds:

```python
# Adjacent-token pairs in which a PERSON_NAME_TOKEN is not a person.
NEGATIVE_PERSON_BIGRAMS = {
    ("head", "quarter"), ("head", "quarters"), ("head", "office"),
    ("head", "count"), ("crime", "head"), ("mother", "tongue"),
    ("account", "head"), ("budget", "head"),
}
```

In `classify_column_name`, before the person-token force: build the ordered
bigrams from `raw` (the token list already exists) and drop any person token
that participates in a negative bigram. `Head Quarter (Name)` then falls
through to the skip list (`quarter` is a skip token) and dies; the VC column
has no negative bigram and still forces.

**Check:** unit cases in the step-8 harness — `Sub District Head Quarter (Name)`
→ skip, `Mother Tongue Name` → skip, `Name of Vice-Chancellor/Director/Head`
→ force, `District_Officer_Name` → force.

## 4. Split the forced bypass — `pii_utils._column_skip_reason` (line ~441)

`if forced: return None` skips dtype **and** cardinality checks. The dtype
bypass is correct (a phone column read as int64 must reach the regex pass);
the cardinality bypass is what let a 17-distinct-values-in-2,587-rows census
column through.

- Have `classify_column_name` return which force fired — reuse the existing
  reason string or return `"force-pii"` vs `"force-person"` decisions.
- In `_column_skip_reason`: `force-pii` (email/phone/aadhaar tokens) bypasses
  everything as today; `force-person` bypasses the dtype/boolean/date/numeric
  checks but **still runs the cardinality check**.
- `select_detection_columns` passes the force kind through.

**Check:** `Sub District Head Quarter (Name)` rejected as categorical even if
step 3 is disabled; `Contact No` (int64) still scanned; a genuine name column
(ratio ≈ 1.0) unaffected.

## 5. Cross-dataset frequency rejection — new build step + `pii_filters.py`

The strongest new signal, and the only one that scales past hand-curated
lists. Measured on the current table (PERSON, normalised text → distinct
datasets):

| appears in N datasets | distinct texts | detections |
|---|---|---|
| 1 | 5,843 | 15,598 |
| 2–3 | 672 | 6,274 |
| 4–10 | 346 | 5,159 |
| 11–50 | 167 | 6,599 |
| >50 | 22 | 5,514 |

Genuine names from the VC directory: **300 of 304 appear in exactly one
dataset, none in more than three.** A "reject if seen in > 3 datasets" rule
removes ~17,300 detections (42%) at zero measured cost to real names.

Implementation:

- New script `build_frequency_blocklist.py` (pattern-match `build_gazetteer.py`):
  query `pii_detections_lot2` (+ `_baseline` for coverage) for normalised
  PERSON texts with `COUNT(DISTINCT uuid) > N`, default `N = 3`; write
  `gazetteer/cross_dataset_common.txt` with a header comment recording N and
  the source snapshot date.
- Load it in `pii_filters.py` exactly like `PLACE_NAMES`; rejection reason
  `"cross-dataset-common"`.
- **Caveats to encode in the script:** (a) today's table is built from
  fragmented spans — regenerate the list after step 1's re-scan, and again
  when the remaining 74% of the corpus is scanned; (b) very common real names
  ("Rahul Kumar") could eventually cross N in a corpus with many genuine
  rosters — keep the rejection at the *detection-filter* level with a
  traceable reason so it can be audited, and revisit N against the labelled
  set (step 8); (c) exclude the known-genuine fixture UUIDs from the count so
  the blocklist can't be poisoned by real names.

## 6. Extend the gazetteer — `build_gazetteer.py`

Keep one file per vocabulary so rejections stay traceable and a list can be
dropped wholesale (`gazetteer/crime_heads.txt`, `languages.txt`,
`commodities.txt`, `occupations.txt`); load each with its own label in
`pii_filters.py` alongside `place_names.txt`.

Cheapest first — harvest from the corpus itself rather than hand-typing:
distinct values of columns whose normalised header matches the family
(`crime head` / `heads of crime`; `mother tongue`; `*commodit*`;
`occupation`), pulled from the already-downloaded detections plus a
spot-check. Closed lists are small: NCRB crime heads ~60 values (3,664
detections), census mother tongues ~120 (2,005). Commodities and village
names are the long tail — do them last, after steps 1–5 shrink the residue,
and measure whether the frequency filter (step 5) already covers them (most
crop names recur across hundreds of district files, so it should).

## 7. Rework the dataset-level flag — `pii_filters.evaluate_dataset_flag`

`NAME_LIKE_CARDINALITY_RATIO = 0.5` (line 329) is anti-correlated with truth
on wide-format tables: `Crime Head` (one row per crime) scores ratio 1.00.
Only 13 of 1,961 current flags come from the trustworthy regex path.

Replace "cardinality > 0.5 alone corroborates" with corroboration requiring
**all** of:

1. cardinality ratio > 0.5 (necessary, as now — kills repeated categories);
2. the column's surviving PERSON values are mostly corpus-rare: median
   cross-dataset frequency ≤ the step-5 threshold (kills wide-format
   vocabularies, which are rare *within* a file but ubiquitous across files);
3. a name-shape check on a sample of values: ≥ half look like names
   (2–4 alphabetic tokens, no digits, not all-caps single tokens) —
   cheap regex, no model.

Keep the reason string mechanism; add the failing criterion to the reason so
review stays possible. Regex-sourced flags unchanged. This needs the per-value
frequency map from step 5 passed into `evaluate_dataset_flag` (extend the
existing `cardinality_by_column` plumbing in `run_pii_s3._scan_s3_csv`).

**Check:** NCRB fixture datasets un-flag; `581bc9f5…` still flags (real names,
ratio ~1.0, corpus-rare, name-shaped).

## 8. Measure before re-running — `evaluate_filters.py` + fixtures

- **Label the labelled set.** `--write-label-template` exists; the 201-row
  template was never filled in. Until `has_pii` is labelled, every number is
  precision-only. This is the gate for shipping steps 1–7.
- Extend the `pii_filters.py` `__main__` harness with the new families:
  `Dacoity`, `BAJRA`, `Clerks` (post-fix whole word), `Hindi` (language),
  negative-bigram column cases from step 3, and the flag cases from step 7.
- Keep the three reference fixtures as the end-to-end test
  (FP_ANALYSIS_ROUND2 §4): `c1418789…` → 0 detections, `581bc9f5…` → keeps
  343 PERSON + 495 phone + 239 email, `00215472…` → 0.
- Re-run `evaluate_filters.py` replay for the before/after table, noting the
  replay can't see step 1's effect (stored spans are already fragmented) —
  the fixtures are what measure step 1.

## 9. Reset and re-run

Only after 1–8: `reset_lot2_run.py --confirm`, then `run_pii_s3.py --lot2`.
Baselines (`pii_detections_lot2_baseline`, `remain_raw_metadata_pii_baseline`)
already exist for comparison via `--compare-baseline`. Then regenerate the
step-5 blocklist from the clean detections and finish the remaining 74% of
the corpus (86,293 datasets, `ministry_folder IS NULL`) — a different
ministry mix that may surface new FP families; budget one review pass over
its top surviving strings.

---

## Out of scope, noted

- **The spaCy/Presidio 0.85 path** (12,454 detections, 32% of PERSON) is
  untouched by step 1. After the fixture harness exists, measure it in
  isolation (`include_transformer_recognizer=False`) — if it contributes
  mostly noise on this corpus, drop spaCy PERSON and keep spaCy only as
  Presidio's tokenization backbone for pattern recognizers.
- **Column-level classification instead of cell-level NER** ("does this
  column hold names?") would sidestep most of this at far lower GPU cost —
  worth prototyping only if precision is still short after step 9.

## Verification summary

```bash
python pii_test/pii_filters.py                      # unit harness, exits non-zero on failure
python pii_test/run_pii_s3.py --path <fixture>.csv  # the three fixtures, expected counts above
python pii_test/evaluate_filters.py                 # replay before/after
python pii_test/evaluate_filters.py --labels labels.csv   # precision/recall once labelled
```
