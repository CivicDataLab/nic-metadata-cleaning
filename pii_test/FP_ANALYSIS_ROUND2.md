# PII False-Positive Analysis — Round 2

Briefing for a follow-up model. Written 2026-08-19 against the **current**
`pii_detections_lot2` table (40,695 detections), i.e. the output of the
already-implemented Stages 1–4 in `DETECTION_IMPROVEMENT_PLAN.md`.

That plan worked: 1,120,818 → 40,695 detections (−96.4%). **The residue is
still ~95% false**, and the reason is a single upstream bug that the previous
analysis never saw, because it corrupts the very evidence that analysis was
built on.

---

## 0. TL;DR

| # | Root cause | Detections | Fix cost |
|---|---|---|---|
| 1 | `aggregation_strategy="simple"` splits words into subword fragments | pervasive — corrupts ~40% of spans and **all** scores | one-line |
| 2 | Person-name tokens force-scan non-person compounds (`Head Quarter`, `Mother Tongue`) | 14,386 (35%) | small |
| 3 | `forced` columns bypass the cardinality check | subset of #2 | 3 lines |
| 4 | Gazetteer covers only admin geography — no crops, crimes, occupations, species, villages | ~19,000 (47%) | data work |
| 5 | Dataset-level "name-like cardinality" test is anti-correlated with truth | 1,948 of 1,961 flags | rethink |

Fix #1 first. It is one line, and it unblocks #4 and the score threshold that
the previous plan wrongly concluded was unusable.

---

## 1. The upstream bug: subword fragmentation

`pii_utils.py:59` builds the Latin NER pipeline as:

```python
hf_pipeline("token-classification", model="Davlan/xlm-roberta-base-ner-hrl",
            aggregation_strategy="simple", ...)
```

XLM-R uses SentencePiece. With `aggregation_strategy="simple"`, HF groups
adjacent tokens only when the B-/I- tags agree, so **a single word whose
subword tokens get different tags is emitted as two or more separate
entities**. Reproduced locally on the cached model:

| input | `simple` output | `average` output |
|---|---|---|
| `JHUNJHUNUN` | `J` (0.95) + `HUNJHUNUN` (0.68) | `JHUNJHUNUN` (0.46) |
| `Clerks` | `C` (1.00) + `lerks` (0.92) | `Clerks` (0.62) |
| `Robbery` | `Robb` (1.00) + `ery` (0.57) | `Robbery` (0.79) |
| `UTTARKASHI` | `U` (0.94) + `TTARKASHI` (0.70) | `UTTARKASHI` (0.43) |
| `Jharsuguda` | `J` (1.00) + `harsuguda` (0.99) | `Jharsuguda` (0.50) |
| `Rahul Kumar` | `Rahul Kumar` (1.00) | `Rahul Kumar` (1.00) |

`keep_result` drops spans under 3 characters, so the leading `J`/`C`/`U`
disappears and only the mangled tail is stored. **This is why the top of the
detection table reads like noise**: `lerks` (752), `Robb` (617), `ILLI` (682),
`HUNJHUNUN` (515), `garh Sahib` (400), `TTARKASHI` (250), `harsuguda` (266).

Measured on a real file (`c1418789…`, Village Amenities, Kandhamal — 2,587 rows):

| column | `simple` PER spans | of which partial-word | `average` PER spans | partial |
|---|---|---|---|---|
| `Village Name` | 1,351 | **562 (42%)** | 1,125 | 18 (1.6%) |
| `Sub District Head Quarter (Name)` | 8 | 2 | 8 | 0 |

### 1.1 It silently disables the gazetteer

Stage 3 built `gazetteer/place_names.txt` (16,562 entries) and it works — but
it never fires, because it is fed mangled strings. Of the **top 400 FP strings
in the table, 0 match the gazetteer**. Unfragment them and they do:

| stored fragment | in gazetteer | true word | in gazetteer |
|---|---|---|---|
| `HUNJHUNUN` | ✗ | `JHUNJHUNUN` | ✓ |
| `TTARKASHI` | ✗ | `UTTARKASHI` | ✓ |
| `harsuguda` | ✗ | `Jharsuguda` | ✓ |
| `HALAWAR` | ✗ | `JHALAWAR` | ✓ |
| `ELLARY` | ✗ | `BELLARY` | ✓ |
| `ILLI` | ✗ | `DELHI` | ✓ |
| `eshwar` | ✗ | `Bhubaneshwar` | ✓ |

11 of 12 sampled fragments hit the gazetteer once whole. Stage 3 was built
correctly and has been dead on arrival.

### 1.2 It also invalidates the plan's conclusion about scores

`DETECTION_IMPROVEMENT_PLAN.md` §1.4 concluded "confidence score is not a
usable filter" because `Urban` scored 0.997. That conclusion was drawn from
scores produced by `simple`, which reports the max-ish subword score and is
systematically overconfident. Under `average`, scores separate properly.

Known-TP set: 31,134 person names from `581bc9f5…` (university VC directory).
Known-FP set: 1,500 village names from `c1418789…`. Per-value max PER score:

| target TP recall | `simple` threshold → FP kept | `average` threshold → FP kept |
|---|---|---|
| 90% | 0.685 → 35.3% | 0.473 → **31.3%** |
| 85% | 0.847 → 20.7% | 0.644 → **8.7%** |
| 80% | 0.901 → 14.7% | 0.720 → **3.4%** |

At matched 85% recall, `average` keeps **2.4× fewer** false positives; at 80%,
**4.3× fewer**. A score threshold becomes a real instrument.

**Recommendation:** switch to `aggregation_strategy="average"`, then
re-tune the `filter_person_detection` threshold (`pii_filters.py:280`, currently 0.6) against the
two sets above. `max` also de-fragments but keeps `simple`'s inflated scores —
`average` is the one that buys both.

The `pii_filters.py` module docstring (lines 5–8) encodes the old conclusion
verbatim — "a score threshold cannot separate them" — and should be rewritten
alongside the fix, or it will mislead the next reader the same way.

⚠️ This changes every score in the pipeline. Anything calibrated against the
old numbers (thresholds, the 0.85 spike from Presidio/spaCy) must be re-checked.

---

## 2. Where the 40,695 detections actually come from

| family | detections | share | verdict |
|---|---|---|---|
| B. `Head Quarter (Name)` geography | 12,323 | 30.3% | false |
| C. commodity / crop vocabulary | 10,137 | 24.9% | false |
| G. place & infrastructure names | 4,707 | 11.6% | false |
| D. crime-head vocabulary | 3,664 | 9.0% | false |
| E. `Mother Tongue Name` languages | 2,005 | 4.9% | false |
| F. occupation titles (NCO) | 1,271 | 3.1% | false |
| H. species names | 206 | 0.5% | false |
| A. phone / email | 1,551 | 3.8% | **true** |
| I. genuine person-name column | 343 | 0.8% | **true** |
| Z. other (mixed) | 4,488 | 11.0% | mostly false |

**~95% false. ~4.6% defensible.**

### 2.1 Force-scan collisions — 14,386 detections (35%)

`PERSON_NAME_TOKENS` (`pii_utils.py:212`) contains `head`, `mother`,
`director`, `owner`. Combined with a `name` token these force a scan and
override every skip rule:

| column | force reason | detections | reality |
|---|---|---|---|
| `Sub District Head Quarter (Name)` | person token `'head'` | 8,434 | census geography |
| `District Head Quarter (Name)` | person token `'head'` | 3,889 | census geography |
| `Mother Tongue Name` | person token `'mother'` | 2,005 | language list |
| `Type of Pipeline / Owner/Name of Pipeline` | person token `'owner'` | 58 | operator orgs |
| `Name of Vice-Chancellor/…/Head` | person token `'director'` | 343 | **genuine — keep** |
| `Contact No` / `EMAIL ID` / `E-mail id` / `PHONE` | force tokens | 1,229 | **genuine — keep** |

The person-token override is doing real work (the VC column depends on it), so
it can't just be deleted. What it needs is **negative bigrams**: `head quarter`,
`mother tongue`, `head office`, `crime head`, `head count` must cancel the
person reading. Match on adjacent token pairs, not the bare token.

### 2.2 The cardinality bypass — `pii_utils.py:441`

```python
if forced:
    return None       # skips numeric, boolean, date AND cardinality checks
```

`Sub District Head Quarter (Name)` has **17 distinct values over 2,587 rows**
(ratio 0.007). The Stage-2 cardinality rule was designed for exactly this and
would have rejected it — but force-scan skips the check.

The docstring justifies the bypass with "a phone column read as int64 must
still reach the regex pass". That argues for bypassing the **dtype** checks,
not the cardinality check. Split them: let `forced` bypass dtype/boolean/date,
but still apply cardinality to person-token forces. Keep the bypass for
`FORCE_SCAN_TOKENS` (email/phone/aadhaar) where a low-cardinality column is
still worth a regex pass.

### 2.3 Vocabulary gaps — ~19,000 detections (47%)

The gazetteer is built from `remain_raw_metadata.{spatial_states,
spatial_districts, spatial_subdistricts}` only. Everything below is missing:

- **Crops/commodities** — `BAJRA`, `PADDY`, `MILLET`, `SARSON`, `ARECANUT`, `MAKKI`, `DHAN`, `RUBBER`, `POTTERY`, `EARTHEN POT`, `Beedi`, `ICE MILL`, `ATTA CHAKKI`. Columns: `Agricultural Commodities (First/Second/Third)`, `Manufactur* Commodit*`, `Handicrafts Commodities (*)`. **10,137 detections.**
- **NCRB crime heads** — `Dacoity`, `Robbery`, `Burglary`, `Arson`, `Murder`, `Prostitution`, `Miscellaneous`. Columns: `Crime Head`, `Crime Head (Col. N)`, `Heads of Crime`, `CRIME HEAD`, `Particulars`. **3,664 detections.** Closed list, ~60 values — publish it verbatim.
- **NCO occupation titles** — `Clerks`, `Stock Clerks`, `Cook`, `Philologists`. **1,271.**
- **Village / habitation / station / water-body names** — a much longer tail than district names. `VILLNAME`, `water_body_name`, `Bus Route Name`, `Railway Station Name`, `Habitation Name`, `sub_basin_name`, `Station`. **4,707.** Census village directories are the obvious source; the corpus itself is another (harvest distinct values from every column whose header carries a geography token).
- **Languages** — `Mother Tongue Name`, ~120 values. **2,005.**
- **Species** — `Hilsa Ilisha`, `Lizard Fishes`, `Muraenesox`, `Lactarius`. **206.**

Note the previous plan's premise no longer holds. It observed 7,429 distinct
strings with 1,000 covering 94.9%, and concluded a lookup table was
sufficient. That was true of the *old* detection mix; the residue now is a
much flatter long tail (village names especially). A gazetteer alone will not
finish this — it needs the column-level rules of §2.1–2.2 doing most of the
work, with the gazetteer as backstop.

---

## 3. The dataset-level flag is worse than the detection table

1,961 of 29,818 tested datasets are flagged (6.6%). By flag reason:

| reason family | datasets | share |
|---|---|---|
| crime vocabulary | 766 | 39.1% |
| commodity vocabulary | 472 | 24.1% |
| other / needs review | 229 | 11.7% |
| free-text/label columns | 217 | 11.1% |
| place & infrastructure | 131 | 6.7% |
| occupation titles | 117 | 6.0% |
| language names | 16 | 0.8% |
| **regex / high-precision** | **13** | **0.7%** |

**Only 13 of 1,961 flags come from the trustworthy path.**

The cause is Stage 4's corroboration rule (`pii_filters.py:329`):
`NAME_LIKE_CARDINALITY_RATIO = 0.5` — a PERSON hit corroborates only if the
column is mostly-distinct. But NCRB tables are **wide-format**: one row per
crime head, so `Crime Head` has ratio **1.00** and looks maximally name-like.
The test is not just weak here, it is anti-correlated — the more rigidly
categorical the table's layout, the more name-like the column scores.

Cardinality cannot distinguish "a list of 30 crime types, one per row" from
"a list of 30 people, one per row". Something else has to: closed-vocabulary
membership, whether values recur across *unrelated datasets* (a real person
does not appear in 584 different ministries' files — `Dacoity` appears in 584),
or the presence of name-structural cues (honorifics, 2–3 token
given/surname shape, surname-list membership).

**The cross-dataset frequency signal is the strongest lead here and is
currently unused.** `Robb` appears in 585 datasets, `Dacoity` in 584,
`Burglary` in 387. A genuine personal name is nearly always confined to one
dataset. This is computable directly from the existing table and would
generalise past every vocabulary gap in §2.3 without hand-curating a single
list.

---

## 4. Reproduction

```bash
# Detection table (already local, read-only)
python3 -c "import duckdb; con=duckdb.connect('transformation/metadata.db',read_only=True); \
print(con.execute('select entity_text,count(*) c from pii_detections_lot2 \
where entity_type=\'PERSON\' group by 1 order by c desc limit 30').fetchall())"

# The fragmentation bug, no GPU needed
python3 -c "
from transformers import pipeline
for s in ('simple','average'):
    p=pipeline('token-classification',model='Davlan/xlm-roberta-base-ner-hrl',aggregation_strategy=s,device=-1)
    print(s, [(o['entity_group'],o['word'],round(float(o['score']),2)) for o in p('JHUNJHUNUN')])"

# Reference files
aws s3 cp s3://nic-ogdp-datasets/downloaded-datasets/ministry-of-home-affairs-department-of-home-registrar-general-and-census-commissioner-india/c1418789-c923-4320-bd2f-54ef6dbcb9a7.csv .   # 250 FPs, zero PII
aws s3 cp s3://nic-ogdp-datasets/downloaded-datasets/ministry-of-education/581bc9f5-1559-4e4e-bb0d-78bb3d1c9974.csv .                                                                        # genuine names+phone+email (latin-1)
```

Reference datasets worth keeping as fixtures:

| uuid | what | current | should be |
|---|---|---|---|
| `c1418789-c923-4320-bd2f-54ef6dbcb9a7` | Village Amenities, Kandhamal — census counts | 250 detections | 0 |
| `581bc9f5-1559-4e4e-bb0d-78bb3d1c9974` | University VC directory | 343 PERSON + 495 phone + 239 email | keep all |
| `00215472-af1c-48c3-8009-2f524dd22a19` | School infrastructure counts (old reference) | 0 | 0 ✓ |

---

## 5. Suggested order of work

1. **`aggregation_strategy="average"`** — one line. Then re-measure everything;
   several numbers in this document and in `DETECTION_IMPROVEMENT_PLAN.md`
   will move. Verify the gazetteer starts firing.
2. **Re-tune the PERSON score threshold** against the TP/FP sets in §1.2.
   0.64–0.72 looks right, but tune it, don't take it.
3. **Negative bigrams for person tokens** (`head quarter`, `mother tongue`,
   `crime head`, `head office`) — kills 14,386 detections without touching the
   VC column.
4. **Split the `forced` bypass** so cardinality still applies to person-token
   forces (`pii_utils.py:441`).
5. **Cross-dataset frequency filter** — the highest-leverage idea in this
   document, and the only one that scales past hand-curated lists. Reject a
   PERSON value that appears in more than N unrelated datasets.
6. **Extend the gazetteer** — crime heads and languages are small closed lists
   and nearly free; commodities and village names are the real work.
7. **Replace `NAME_LIKE_CARDINALITY_RATIO`** with something that isn't
   defeated by wide-format tables (§3).
8. **Then** re-run. Note the run is only **26% complete** (29,818 of 116,111
   datasets; 86,293 untested, `ministry_folder IS NULL`). Fixing filters before
   finishing the scan is the right order — but the untested 74% is a different
   dataset mix and may surface FP families absent from this analysis.

---

## 6. Open questions for the next model

- Is `average` the right aggregation, or should the pipeline read word-level
  offsets directly (`word_ids()`) and aggregate itself? `average` is one line;
  manual aggregation is more control and more code.
- The corpus is overwhelmingly **aggregate statistical tables** — is
  cell-level NER the right tool at all? A cheaper column-level classifier
  ("does this column hold personal names, yes/no") run once per column instead
  of once per cell would sidestep most of §2 and cost far less GPU. Cell-level
  NER would then only run on columns that survive.
- The 0.85 score spike is 12,454 detections (32% of PERSON) — Presidio/spaCy's
  fixed `en_core_web_lg` score. That whole path is unaffected by the
  aggregation fix and needs its own evaluation; it may be contributing little
  beyond noise now that a proper NER model is in place.
- Recall is still unmeasured. Every number here is about precision, because
  the labelled set from Stage 5 was never labelled. Nothing here should be
  shipped as "better" without it — §1.2's TP set (31k names from one file) is
  a stand-in, not a benchmark.
