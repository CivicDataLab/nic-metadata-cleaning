# Classifying PII Detections: false-positive / pii-permissible / pii-present

Research note and implementation record. Started 2026-09-02. Scope: the
~325k datasets scanned (206,947 tested in `dublin_core_metadata`, 116,111 in
`remain_raw_metadata`) and the detections stored in `pii_detections_lot1` /
`pii_detections_lot2`.

**Status.** Tier 1 and the office-holder allow-list are built and running;
Tier 3 is built and its verdicts on the 164-pair Tier 1 residual are written
to `pii_column_class` (§10.4); Tiers 2 and 4 are still designs. Sections
1-6 are the research that set the approach, sections 7-8 record what was built
and what it changed (§8.1-8.2 are how the vocabularies were made), section 9 is
what comes next and section 10 is Tier 3.

| what | where | state |
|---|---|---|
| Tier 1 rules | `pii_test/pii_classify.py` | built, `--test` self-tests pass |
| Office-holder allow-list | `pii_test/build_public_office_gazetteer.py` -> `gazetteer/public_office_holders.txt` | built, 26,512 names |
| Verdicts | `metadata.db` -> `pii_column_class`, `pii_dataset_class` | 7,707 pairs loaded |
| Tier 3 LLM judge | `pii_test/pii_tier3.py` + local vLLM `tier3-judge` | built; 163 of 164 residual pairs decided and written, the last one by a reviewer (§10.4) |
| Tier 2 model / gold set | — | designed, not built |

---

## 0. TL;DR

1. **The score cannot work, and it is not a calibration problem.** 22,461 of
   the stored PERSON detections carry exactly `0.85`. That is Presidio's
   hard-coded `SpacyRecognizer` default, not a model probability
   ([issue #1190](https://github.com/microsoft/presidio/issues/1190),
   [#1372](https://github.com/microsoft/presidio/issues/1372)). `0.4` on phone
   numbers is likewise the weak-regex constant. There is no signal to threshold.
2. **The three labels are two different questions at two different levels.**
   *Is this span really a person/phone/email?* is a **column-level** question
   (a column is a roster or it is not). *May it be published?* is a
   **dataset-and-role-level** question (whose data, in what capacity). One
   classifier cannot answer both from the span alone; the literature and every
   production system found do it with table context.
3. **The unit of classification should be the (dataset, column) pair, not the
   span.** There are only 7,707 such pairs (3,997 LOT 1 + 3,710 LOT 2) under
   236 distinct headers. That is small enough for an LLM judge over every pair,
   and small enough to hand-label a real evaluation set.
4. **Recommended design:** a three-tier cascade — deterministic rules → a
   feature-based gradient-boosted classifier trained on the graded corpus →
   a column-level LLM judge for the residual, given dataset title, ministry,
   sibling headers and sample values. Plus two entity-level allow-lists that
   define *permissible*: public-office holders (Lok Sabha / Rajya Sabha /
   Wikidata positions) and helpline / office contact numbers.
5. **Legal anchor for "permissible":** DPDP Act 2023 s.3(c)(ii) excludes
   personal data "made publicly available … by any other person under any
   obligation under any law". Names and contact details of MPs, heads of
   institutions, and RTI/nodal officers fall there; a farmer's mobile in a call
   centre transcript or a household member's mother's name does not.
6. **Measured outcome so far.** Tier 1 alone classifies 96.8% of pairs as
   false positives, and of the 2,242 datasets currently carrying
   `pii_detected = true`, **2,131 are false positives**. It also finds 7
   datasets holding real PII that are *not* flagged, so it adds recall as well
   as precision. Details in §7.

---

## 1. What the stored data actually looks like

Counts below are after the full LOT 1 re-scan finished on 2026-09-02
(206,947 of 206,972 rows tested; the flag count fell from 481 to 281 as the
re-scan replaced the worthless earlier pass).

| | LOT 1 | LOT 2 |
|---|---|---|
| detections | 14,042 | 40,695 |
| (dataset, column) pairs | 3,997 | 3,710 |
| distinct headers | 36 | 200 |
| distinct entity texts | 2,652 | 8,404 |
| datasets flagged | 281 | 1,961 |

Where the flags come from:

* **LOT 1:** ~272 flagged datasets are HMIS "Performance of Key HMIS
  Indicators" tables whose `Indicator` column was read as PERSON — false
  positives. 6 hold a Lok Sabha member directory (`Member Name`,
  `Father Name`, `Email ID` …) — permissible; note these six are *mistitled*
  in the catalogue and actually carry the **current**-member file, see §7.
  A handful (KCC transcripts, `Mobile_Number`,
  `Address_Original_First_Line`) are real.
* **LOT 2:** 1,948 of 1,961 flags came through the old cardinality-only
  "name-like PERSON columns" path: `Crime Head`, `NCO Name`, `Bus Route Name`,
  `Agricultural Commodities`, `Sub District Head Quarter (Name)` — nearly all
  false positives. The 13 regex-flagged ones split between permissible
  (`Name of Vice-Chancellor/ Director/ Principal/ Head` + `Contact No`,
  `EMAIL ID,FAX,PHONE` of institutions) and false (`ELEPHANT POPULATION IN
  2007`, `Aggregate Evapotranspiration Volume` read as phone numbers).

Three observations that drive the design:

* **Headers carry most of the signal.** 236 headers cover 7,707 pairs. Nearly
  every header maps cleanly to one class once you read it with the dataset
  title: `Crime Head` → FP; `Member Name` in a Sansad directory → permissible;
  `Mother Name` in an AHS household schedule → present.
* **The same header flips class with dataset context.** `name` is a public
  official in a "Nodal Officers" table and a private citizen in a beneficiary
  list. `Contact No` next to `Name of Vice-Chancellor` is an office line; next
  to `Father Name` and `Village` it is personal.
* **Dataset metadata is available but uneven.** Title, Catalog Title,
  ministry and sector exist for all rows. `Description` is populated for all
  117,721 `dublin_core_remaining` rows and for **zero** `dublin_core_metadata`
  rows. Sibling column headers and `rows_scanned` are not persisted at all
  (sharp edge #1) — only headers of columns that produced a detection survive.

---

## 2. Reframing the labels

```
                 ┌─ Is the column really a roster of identifiable people /
                 │  personal contact channels?              ── no ──► FALSE-POSITIVE
  (dataset, col) ┤
                 │  yes
                 └─ Are those people identified in a public-office or
                    organisational capacity, or is the contact channel
                    an institutional one?                    ── yes ─► PII-PERMISSIBLE
                                                             ── no ──► PII-PRESENT
```

**Q1 (real or not)** is answered by column *shape*: cardinality, name-shaped
fraction, cross-dataset frequency, digit content, gazetteer hits, header
semantics. `evaluate_dataset_flag()` already does a rule version of this.

**Q2 (permissible or not)** is answered by *role* and *channel*, which live in
the header, the sibling headers and the dataset title, never in the span:

| signal | → permissible | → present |
|---|---|---|
| header role words | MP, MLA, Minister, Chairman, Director, Principal, Vice-Chancellor, Nodal Officer, CPIO, Secretary, Registrar, Contact Person, Author, Awardee | Beneficiary, Applicant, Farmer, Patient, Mother, Father, Spouse, Household Head, Student, Worker, Complainant, Victim, Accused |
| sibling headers | Designation, Department, Office, Jurisdiction, Institution, Tenure, Constituency, Party | Age, Gender, Caste, Religion, Income, Disease, Aadhaar, Bank, Village, House No, Scheme |
| dataset title / catalog | directory, list of members, office bearers, contact details, awardees, who's who | survey, schedule, beneficiaries, transcripts, call records, complaints, registration |
| phone class | toll-free `1800/1860`, short codes, STD landline with office context | 10-digit mobile starting 6–9, especially inside free text |
| email domain | `gov.in`, `nic.in`, `sansad.nic.in`, `ac.in`, institutional | consumer domains next to private-person headers (weak: officials use Gmail too) |
| entity allow-list | matches a Lok Sabha / Rajya Sabha / Wikidata office-holder | no match (absence is *not* evidence of private) |

Legal basis for the Q2 split: [DPDP Act 2023 s.3(c)(ii)](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
excludes personal data made public by the principal or by another person under
a legal obligation ([commentary](https://lawschoolpolicyreview.com/2026/01/13/publicly-available-data-under-the-dpdp-act-the-limits-of-exemptions-in-ai-driven-processing/)).
NDSAP's negative-list guidance ([Implementation Guidelines 2.4](https://www.data.gov.in/sites/default/files/NDSAP%20Implementation%20Guidelines%202.4.pdf))
says sensitive personal information must not go on the platform — that is the
*present* class. NIST SP 800-122 makes the same point: the same field is
sensitive or not depending on context, so a per-value verdict is the wrong
granularity ([NIST](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-122.pdf)).

---

## 3. What the literature and industry do

**Second-stage verification of NER/regex candidates with an LLM.**
RECAP ([arXiv 2510.07551](https://arxiv.org/html/2510.07551v1)) runs regex +
NER, then sends ambiguous spans with one sentence of context to an LLM for
confirmation; weighted F1 rises 28.8 points across the two refinement phases,
+82% over a fine-tuned NER baseline. This is the cell-level version of what we
need; at our scale it is only affordable because we do it per column, not per
cell.

**Column-level personal-data classification with table context.**
[arXiv 2506.22305](https://arxiv.org/html/2506.22305v1) is the closest match
to this task: GPT-4o given *dataset title + description + target column name +
all sibling column names + 10 most frequent values* decides if a column is
personal data. Macro-F1 0.865 average vs Presidio 0.608 and a DistilBERT
column classifier 0.643; the gain comes precisely from sibling headers and
description (e.g. `Cabin`, `Ticket` only make sense in context). Same recipe
in production: Grab's data classification (table + column name into an LLM
against a tag taxonomy, "users changed fewer than one tag per table",
[blog](https://engineering.grab.com/llm-powered-data-classification)),
Databricks LogSentinel (name, type, comment, sample values, few-shot examples
retrieved by embedding; 92% precision / 95% recall on 2,258 labelled columns;
columns of one table batched in one request,
[blog](https://www.databricks.com/blog/logsentinel-how-databricks-uses-databricks-llm-powered-pii-detection-and-governance)),
NVIDIA NeMo's LLM column classification
([docs](https://docs.nvidia.com/nemo/microservices/25.10.0/generate-private-synthetic-data/synthesize/replace-pii/llm-classification.html)).

**Semantic column-type detection without an LLM.** Sherlock (values only)
and Sato (values + table context via topic model + CRF over neighbouring
columns) are the pre-LLM approach; Sato beats Sherlock by up to 14.4 macro-F1
exactly because of context ([VLDB 2020](https://www.vldb.org/pvldb/vol13/p1835-zhang.pdf)).
Useful as design guidance (features = header + values + neighbours), but the
pretrained models are English/Web-table and would need retraining.

**Presidio's own answer to false positives** is context words, allow-lists
and deny-lists ([context enhancement](https://microsoft.github.io/presidio/tutorial/06_context/),
[FAQ](https://microsoft.github.io/presidio/faq/)); these only *tighten*, and
we have already exhausted them (gazetteers, frequency blocklist). They cannot
produce the permissible/present split.

**Public-figure allow-lists.** Wikidata's *every politician* project and
OpenSanctions' Wikidata PEP dataset give machine-readable office-holder lists
([WikiProject](https://www.wikidata.org/wiki/Wikidata:WikiProject_every_politician),
[OpenSanctions wd_peps](https://www.opensanctions.org/datasets/wd_peps/)).
For India, `sansad.in` member lists (Lok Sabha and Rajya Sabha, current and
former) are the direct source and already sit in our permissible sample.

**Weak supervision to get training labels cheaply.** Snorkel-style labelling
functions (header regexes, gazetteer hits, cardinality rules, phone class)
combined by a label model produce noisy labels at scale from a small gold set
([Stanford SAIL](https://ai.stanford.edu/blog/weak-supervision/)). Our filters
are already labelling functions in all but name.

**Caveat on LLM-as-judge.** JudgeWEL ([arXiv 2601.00411](https://arxiv.org/pdf/2601.00411))
finds LLMs judging NER labels are good on obvious errors but uneven across
entity types and weak on span boundaries. Use the LLM at column level with
rich context, not as a span oracle, and keep a human-labelled test set.

---

## 4. Recommended design

### 4.1 Unit and output

Classify every **(dataset, column)** pair that has ≥1 stored detection.
Output table `pii_column_class`:

```
uuid, lot, column, entity_types, n_detections,
pii_class ∈ {false_positive, permissible, present},
role ∈ {not_person, public_office, org_contact, private_individual, personal_contact, unknown},
confidence, tier ∈ {rule, model, llm, human}, reason, evidence_json, classified_at
```

Dataset roll-up: `present` if any column is present; else `permissible` if any
column is permissible; else `false_positive`. Keep `pii_detected` as is (it is
the *detector's* answer); add `pii_class` beside it so stored results are never
loosened in place (sharp edge #7).

### 4.2 Features per pair (all derivable now except the two marked ✚)

* **Header:** normalised header, role-word hits (public / private lists in
  §2), name/contact/id keyword class from `classify_column_name`, script.
* **Column shape (from stored rows):** cardinality, n distinct, name-shaped
  fraction (`looks_like_person_name`), median cross-dataset frequency,
  digit-containing fraction, mean token count, share of values in each
  gazetteer, fraction of source = regex, phone-class histogram
  (`classify_phone_number`), email-domain class.
* **Dataset context:** Title, Catalog Title, ministry, sector, Description
  (LOT 2 only), title keyword class (directory / survey / transcript / …),
  publisher type (Sansad, NCRB, Census, MoHFW HMIS …).
* ✚ **Sibling headers** of the dataset (needs one header read per dataset —
  cheap: a `head -1` from S3, or from the `headers_cleaned` pipeline if it
  stores them).
* ✚ **`rows_scanned`** and name density (sharp edge #1; persist it going
  forward).

### 4.3 Three-tier cascade

**Tier 1 — deterministic rules (covers the bulk, zero cost).**
Labelling functions, applied in order, each returning a class + reason. This
was the sketch; the cascade that was actually built has twelve rules and a
different ordering, because three of the assumptions below turned out to be
wrong against real data — see §7 for the built version and why it differs.

1. Header in the closed FP list of known controlled vocabularies (`Crime
   Head*`, `NCO Name`, `Indicator*`, `*Commodit*`, `Bus Route Name`, `Railway
   Station Name`, `Species`, `Mother Tongue Name`, `*Head Quarter (Name)`,
   `Products`, `DESCRIPTION`, `CARGO*`) **or** column fails Q1 shape tests
   (cardinality ≤ 0.5, median frequency > 1, name-shaped < 50%) → `false_positive`.
2. Phone column with only toll-free / institutional / landline numbers and no
   private-role sibling → `permissible`.
3. Header contains a public-office role word, or dataset title matches a
   directory pattern, or ≥ 30% of distinct values match the office-holder
   allow-list → `permissible`.
4. Header contains a private-role word, or the dataset has ≥ 2 quasi-identifier
   siblings (age, gender, caste, village, house no, Aadhaar, scheme), or the
   detection is a mobile number / email inside free text (`KccAns`,
   `faqAnswer`, `Particulars`) → `present`.
5. Otherwise → undecided, pass to Tier 2.

Expect Tier 1 to settle > 90% of the 7,707 pairs, because 20 headers account
for the overwhelming majority of them. *Outcome: it settles 97.9%, and the
residual 2.1% is deliberate — the built rules refuse to convict a column on
dataset context alone.*

**Tier 2 — gradient-boosted classifier on the features in §4.2.**
Train on the graded corpus (`pii-test-sample/*`: 4,104 detection rows across
~20 datasets, aggregated to pairs) plus Tier-1 labels as weak supervision
(Snorkel label model or simply treat rules as high-precision pseudo-labels).
LightGBM/XGBoost, three classes, calibrated probabilities. Route anything
below 0.8 confidence to Tier 3. This is the tier that generalises to headers
the rule list has never seen.

**Tier 3 — column-level LLM judge for the residual.**
One prompt per undecided pair (or one per dataset, batching its columns as
LogSentinel does), containing: dataset title, catalog title, ministry, sector,
description if present, all sibling headers, the target header, up to 15
distinct detected values, column stats, and the class definitions from §2 with
the DPDP s.3(c)(ii) framing. Ask for `{class, role, confidence, reason}` as
JSON, few-shot with 6 examples drawn from the graded corpus (one per class per
lot). Cost: a few thousand pairs × ~800 tokens ≈ 3–5 M tokens — a few dollars
on any API, or free on the local T4 (16 GB) with a quantised 7–8B instruct
model via vLLM at roughly 1–2 pairs/s. Prefer the local route: the values
being sent are, by hypothesis, PII (the same concern 2506.22305 raises about
cloud transmission).

**Tier 4 — human review** for LLM confidence < 0.7 and for every `present`
verdict before it drives an action. Feed corrections back into the graded
corpus.

### 4.4 Entity-level allow-lists (define "permissible" concretely)

* **Office-holders** — *built, see §8.* Lok Sabha members plus Wikidata
  humans holding Indian positions, in `gazetteer/public_office_holders.txt`.
* **Institutional email domains** — *built.* `*.gov.in`, `*.nic.in`,
  `*.ac.in`, `*.edu.in`, `*.res.in`, `*.org.in` as
  `INSTITUTIONAL_EMAIL_SUFFIXES` in `pii_classify.py`.
* **Helplines / office numbers** — *partly built.* Toll-free ranges and short
  codes are recognised structurally by `pii_filters.classify_phone_number`,
  which is enough for rule R4. The harvested list of repeated landlines is
  **not** built: `011-24300606` appears dozens of times in one KCC file alone
  and a frequency-counted phone list would catch that class properly.

These are *allow* lists: a hit is evidence of permissible; a miss is not
evidence of present.

---

## 5. Evaluation plan

The current graded corpus is too narrow to measure anything: `pii-present`
is dominated by one KCC file, `pii-permissible` by four Sansad files,
`pii-false-postive` by MSME enterprise lists. Build a stratified gold set
**by header cluster**: sample ~15 pairs from each of the top 40 headers and
~100 from the long tail (~700 pairs total), label at pair level, three
classes. `labels.csv` (202 dataset-level rows) can be folded in.

Report per-class precision/recall and, separately, the two binary questions
(real-vs-FP, permissible-vs-present) since they fail for different reasons.
Target: recall on `present` ≥ 0.95 (the cost of a miss is a leak), precision
on `false_positive` ≥ 0.95 (the cost is a wasted review). Freeze the gold set
before tuning Tier 1; otherwise the frequency-blocklist feedback loop (sharp
edge #2) repeats itself in the classifier.

---

## 6. Alternatives considered

| approach | verdict |
|---|---|
| Threshold / recalibrate the Presidio score | Not possible: 0.85 and 0.4 are constants. spaCy does not expose span probabilities; the HF models do, but only for their own spans. |
| Cell-level LLM verification (RECAP style) | Right idea, wrong granularity here: ~55k stored spans is fine, but a live re-scan would be millions of cells. Do it per column. |
| Retrain / swap the NER model (GLiNER, IndicNER fine-tune) | Improves Q1 slightly, cannot answer Q2, and reopens the "filters only tighten" invariant. |
| Pure header classifier (Grab style, no values) | Cheap and strong, but `name` / `Contact No` / `Particulars` are unresolvable without values and siblings. Use as Tier-1 input, not alone. |
| k-anonymity / quasi-identifier analysis | Complements Q2 (household survey with age+village+name is identifying even without a full name) but is a re-identification risk score, not a three-class label. Worth a later phase for `present` severity. |

---

---

## 7. Tier 1 — built (2026-09-02)

`pii_test/pii_classify.py`. `python pii_classify.py --test` runs the
self-tests; `--snapshot DIR` classifies a parquet export; `--db PATH --write`
creates the table. Results are in `transformation/metadata.db` as
`pii_column_class`, with `pii_dataset_class` as the roll-up view.

**Result over 54,737 stored detections / 7,707 (dataset, column) pairs**,
after the full LOT 1 re-scan completed on 2026-09-02:

| class | pairs | share | datasets |
|---|---|---|---|
| false_positive | 7,458 | 96.8% | 6,222 |
| undecided | 164 | 2.1% | 137 |
| permissible | 52 | 0.7% | 11 |
| present | 33 | 0.4% | 26 |

Rolled up to datasets: 6,192 false_positive, 124 undecided, 26 present,
10 permissible.

Against the current `pii_detected` flag, of the 2,242 flagged datasets:
**2,131 are false positives**, 19 present, 10 permissible, 82 undecided.
Tier 1 also finds 7 datasets holding `present` PII that are *not* currently
flagged, so this is not purely a precision filter.

### 7.1 The cascade as built

Twelve rules, first match wins. `pairs` is how many of the 7,707 each decided.

| rule | verdict | pairs | what it tests |
|---|---|---|---|
| R1-skip-header | false_positive | 1,637 | `classify_column_name` already says the header cannot hold personal data |
| R1-controlled-vocab | false_positive | 5,368 | header token marks a closed category list, and only PERSON was detected |
| R2-column-shape | false_positive | 450 | PERSON values are not name-shaped, or the column is low-cardinality, or corpus-common *and* not uniformly name-shaped |
| R3-not-a-number | false_positive | 3 | phone matches fit no numbering-plan slot, or are bare digit runs in a column naming no contact channel |
| *(gate)* | → R12 | — | no person or contact signal in the header: context alone may not convict |
| R4-institutional-channel | permissible | 3 | every contact value is toll-free, a landline, or an institutional domain |
| R5-private-absolute | present | 0 | header says beneficiary / patient / victim / accused — overrides any context |
| R6-office-allowlist | permissible | 6 | ≥30% of distinct values (min 3) are known public office holders |
| R7-directory-context | permissible | 42 | the dataset is an office-bearer directory |
| R8-office-header | permissible | 1 | header names a public office (MP, CPIO, chancellor …) |
| R9-private-contextual | present | 0 | header names a relative or private role, and the dataset is not a directory |
| R10-individual-records | present | 29 | the dataset holds individual records |
| R11-personal-channel | present | 4 | a subscriber mobile or personal email address |
| R12-residual | undecided | 164 | no rule applies — hand to Tier 2/3 |

Three ordering decisions carry the design:

* **Q1 before Q2.** A column that is not personal data cannot be
  "permissible"; asking about publication capacity first would launder every
  crime-head list into a legal category it does not need.
* **Dataset context outranks most header role words** (R7 above R9). In a
  member directory, `Father Name` holds a real relative of a real person and
  is published inside the member's official biography. Reading the header
  alone gives `present`; reading it inside a directory gives `permissible`.
* **Some header words outrank any context** (R5 above R7). `Beneficiary`,
  `Patient`, `Victim`, `Accused` name a private individual however the dataset
  is titled. R5 and R9 show 0 pairs on today's corpus but are load-bearing
  guards, and the self-tests assert them.

No confidence float is emitted for rule verdicts. Inventing one would repeat
exactly the mistake that makes the detector's 0.85 useless; each verdict
carries a `rule_id` and an ordinal `rule_strength`, and the `confidence`
column stays NULL until Tier 2 or 3 fills it.

### 7.2 Three findings that changed the design in §4

1. **A catalogue title can describe a different file than the one scanned.**
   Six LOT 1 datasets titled "Data Item Comparison Report of Sikkim for
   2014-2015 and 2013-2014" have `Relation[download_url]` pointing at
   `Current_mem_Eng_nov_2017.csv` — the Lok Sabha current-member directory.
   Their columns are `Member Name`, `Father Name`, `Position(s) Held`,
   `Books Published`. Title-derived context is therefore wrong for exactly the
   datasets where it matters most. Tier 1 now derives context from the
   **column schema** as well, and the schema wins where the two disagree
   (`schema_context`, `DIRECTORY_SCHEMA_MARKERS`). This is worth chasing as a
   catalogue bug in its own right.

2. **Cross-dataset frequency cannot reject a column on its own.** The
   parliamentary directories are republished six times — across years and in
   both languages — so every genuine MP appears in six "different" datasets
   and scores a median frequency of 6. Real controlled vocabularies sit at a
   median of 17 with a 90th percentile of 90. The ranges overlap, and the
   threshold `evaluate_dataset_flag` uses for flagging (> 1) rejects the
   genuine directories outright. Frequency now only rejects when the values
   are also less than uniformly name-shaped; a fully name-shaped, highly
   distinct column goes to the later tiers instead of being dismissed.

3. **Dataset context must not convict a column on its own.** Letting it
   label `Name of the Monument`, `Depth range (m)` and `Accreditation Body`
   as personal data purely because the dataset looked like individual records.
   The context rules now require a person or contact signal in the column
   itself (`column_signal`); without one the pair goes to `undecided`.

Two smaller corrections: Presidio's toll-free prefix test matches any digit
run starting `180`, which turned an evapotranspiration volume and an elephant
population into published helplines, so a phone match must now be *written*
like a number; and address columns count as personal data in their own right,
which is what makes an MP's listed address permissible and a respondent's
address present.

An audit of the 1,778 riskiest rejections — those at least 90% name-shaped
with near-unique values — found no genuine person column among them. They are
place names (`Aizawl West`), commodities (`FERRO ALLOYS`, `EARTHEN POT`),
station names and district headquarters.

**Not yet done, and load-bearing for the tiers above:** sibling headers are
still derived from columns that happened to produce a detection, so a clean
quasi-identifier column is invisible, and `rows_scanned` is still not
persisted.

### 7.3 The six mistitled datasets

Confirmed with the data owner: the uploader attached the wrong files in the
backend. The catalogue rows are HMIS comparison reports; the files behind them
are the Lok Sabha current-member directory. This is a backend data-entry bug,
not a modelling problem, and it is worth fixing at source. Until it is, the
schema-over-title rule is what keeps the classifier correct on them, and it
should stay regardless — nothing guarantees these six are the only ones.

---

## 8. The office-holder allow-list (2026-09-02)

`pii_test/build_public_office_gazetteer.py` builds
`gazetteer/public_office_holders.txt`. Three sources:

| source | what it contributes |
|---|---|
| `--local` | Lok Sabha **former**-member directories shipped with the graded corpus |
| `--corpus` | directory datasets found by **column schema**, harvested from S3 — this is what supplies the **current** members |
| `--wikidata` | Indian politicians and holders of India-located positions, English and Hindi labels |

**This is the only gazetteer that makes the pipeline quieter about real
people**, so its failure mode is inverted: a bad entry marks a private
individual publishable. Four guards, all reported in the file header:

* no mononyms, counted **after** stripping honorifics — `Shri Vizol` is two
  tokens but one name; 488 such entries were rejected across the three
  sources, 76 of them from the local directories alone;
* no collisions with any rejection gazetteer;
* nothing appearing in more than `CROSS_DATASET_MAX` datasets;
* and a single match never decides anything — `pii_classify` requires
  `PUBLIC_OFFICE_MATCH_RATE` (30%) of a column's distinct values, minimum
  three, before rule `R6` calls the column permissible.

The final list holds **26,512** names. Rejections, all recorded in the file
header: 488 mononyms after honorific stripping, 60 out of length range, 35
containing digits, 13 appearing in too many datasets to identify anyone, 2
colliding with a rejection gazetteer.

Three things the build showed:

1. **The local source alone is not enough.** Built from former members only,
   it matched **2%** of the `Member Name` values in the mistitled datasets,
   which hold *current* members. The `--corpus` source, which finds directory
   datasets by schema and harvests their own spellings, is what closes that
   gap; Wikidata is what covers state legislatures and non-political office.
2. **A bigger list did not mean more matches.** At 26,512 names -- 7,780 from
   the local directories, 20,000 Wikidata labels, 1,446 harvested from the
   corpus -- rule `R6` still fires on exactly the six `Member Name` columns,
   at a 92% match rate. No private-individual column was swept into
   permissible by the extra 18,000 names, which is the 30%-of-column
   threshold doing its job. Wikidata's public endpoint was rate-limiting to
   one request per minute during an outage, so only the first page of the
   politician query landed; the builder keeps partial results and records in
   the file header which sources actually contributed.
3. **The allow-list correctly refuses to match relatives.** `Mother Name` and
   `Spouse Name` matched **0%**. Those people hold no office. They are
   permissible only by sitting inside a published member record, which is the
   dataset-context rule's job (`R7`), not the allow-list's. Harvesting them
   would have put ordinary private names on a list that travels to every other
   dataset, so `NAME_COLUMN_HINTS` excludes the relative columns by design.

### 8.1 How the 26,512 names were collected

Five steps, one script (`--all` runs all three sources):

1. **Collect raw strings.**
   * `--wikidata` runs two SPARQL queries against the public endpoint: humans
     who are Indian citizens with occupation *politician*, and humans holding
     any position whose country is India. The second query is what catches
     judges, governors and vice-chancellors, who are not tagged as
     politicians. English and Hindi labels, paged 20,000 at a time.
   * `--local` reads the member directories shipped with the graded corpus and
     takes the distinct values of the office holder's **own** name column,
     picked by header (`NAME_COLUMN_HINTS`). Father / Mother / Spouse columns
     are deliberately not harvested.
   * `--corpus` finds directory datasets in S3 by their **column schema**
     (`pii_classify.schema_context`), not their catalogue title — in this
     corpus the two disagree (§7.3) — and harvests the same name columns. This
     is the source that supplies the corpus's own spellings.
2. **Normalise** every string through the same `normalize_entity_text` that
   both sides of every later comparison use: casefold, punctuation to spaces,
   whitespace collapsed. `Shri A.M. Pathan` and `SHRI A M PATHAN` become one
   key.
3. **Filter, counting every rejection reason:** no digits, 6-60 characters, at
   least two tokens *after* honorifics are stripped, no collision with any
   rejection gazetteer, cross-dataset frequency ≤ 3.
4. **Keep the honorific-free twin as well.** The directories write `Shri Vizol
   Koso`; other datasets write `Vizol Koso`. The stripped form is re-checked
   against the same filters rather than assumed safe — stripping can push a
   name under the length floor or onto a rejection list.
5. **Write the provenance into the file header:** snapshot date, raw count per
   source, and each rejection reason with its count.

29,226 raw strings in — 20,000 Wikidata labels, 7,780 local, 1,446 corpus —
598 rejected with a recorded reason, duplicates across the three sources
collapsing to **26,512 distinct names** out. Nothing is hand-typed and nothing
is hand-edited; the file says so on line 1, because the only safe way to change
an allow-list about real people is to change the script and re-run it.

### 8.2 The other vocabularies, and how they were built

Everything else under `gazetteer/` is a **rejection** list — things that are
categorically not people. One file per vocabulary, so a rejection can name the
list it came from and any single list can be dropped wholesale if it turns out
to over-reject.

| file | entries | built from |
|---|---|---|
| `place_names.txt` | 16,562 | the catalogue's own spatial fields |
| `cross_dataset_common.txt` | 4,648 | counted, not collected — see below |
| `settlements.txt` | 1,026 | block / locality name columns, 600 datasets |
| `commodities.txt` | 520 | commodity columns, 60 datasets |
| `occupations.txt` | 486 | `NCO Name`, 40 datasets |
| `crime_heads.txt` | 278 | NCRB `Crime Head` columns, 40 datasets |
| `languages.txt` | 256 | census `Mother Tongue Name`, 18 datasets |
| `species.txt` | 113 | `Species`, 9 datasets |

Three methods, in short.

**Place names come from the metadata, not the data.** Every dataset already
declares which states, districts and subdistricts it covers; splitting those
semicolon-separated fields in `remain_raw_metadata` yields every place the
corpus talks about, for free and without downloading anything. Anything under
four characters is dropped, because two- and three-letter fragments collide
with initials and name particles. Indian administrative place names were the
single largest source of PERSON false positives in the LOT 2 scan (`RAJGARH`,
`THOUBAL`, `JAISALMER`). The harvest is otherwise unfiltered, and it shows: 123
of the 16,562 entries are `(+N more)` truncation markers copied straight out of
the catalogue's own overflowing spatial fields. They are inert — no PERSON span
will ever equal `(+107 more)` — but they are a reminder that this list is only
as clean as the metadata it came from.

**Value families are harvested, not typed.** For each family: find the datasets
whose *column header* matches the family, download those CSVs from S3, take the
distinct values of the matching columns. The header patterns are deliberately
narrow — `Particulars` also carries crime heads, but carries free text too, and
harvesting free text into a rejection list is how a real name ends up in one.
The guard is `min_datasets`: a value must appear in at least 2 of the harvested
datasets (3 for the free-text families) to be kept. A genuine commodity recurs
across districts; someone typing `Ashok Kumar` into a free-text commodity
column does not, and would otherwise be put beyond detection forever —
commodities dropped 12,258 one-off values on that rule alone. Harvesting beats
typing because it captures the corpus's own spellings: `MAKKI`, `ATTA CHAKKI`,
`C.H. Not Amounting to Murder`.

**The frequency blocklist is counted, not collected.** For every normalised
PERSON value in the detection tables, count how many *distinct datasets* it was
seen in, and keep `count<TAB>value` for everything seen in at least two. The
premise is that a personal name is confined to the dataset that is about that
person: of the 304 genuine names in the reference VC directory, 300 appear in
exactly one dataset and none in more than three. `dacoity` appears in 609.
Anything above `CROSS_DATASET_MAX = 3` is rejected outright, with its own
traceable reason (`cross-dataset-common`) so the threshold can be revisited
against the labelled set; datasets known to hold genuine names are excluded
from the counts, so the list cannot be poisoned by the real names in them.

Its known weakness is sharp edge #2, and it is why §9 item 2 exists: the list
is built from post-filter detections that were produced *using* it, so each
rebuild can only ever remove more.

---

## 9. What is left

**Done:** the office-holder allow-list (§8) and Tier 1 over all 7,707 pairs
(§7), which reclassified the 1,948 NCRB/Census LOT 2 flags and the 272 HMIS
LOT 1 flags as `false_positive` as predicted.

**Next, in order:**

1. **Persist `sibling_headers` and `rows_scanned`** in `run_pii_s3.py`, and
   back-fill headers for the 2,242 flagged datasets from S3 (`head -1`). Both
   Tier 2 and Tier 3 want them, and it fixes sharp edge #1. Today's sibling
   set is derived from columns that happened to produce a detection, so a
   clean quasi-identifier column is invisible and the absence of one proves
   nothing — the rules only read that set positively because of this.
2. **Rebuild the frequency blocklist** now that the full LOT 1 table exists.
   Its counts were seeded from a 331-dataset sample and have never seen most
   batches. Mind the feedback loop (sharp edge #2): it is built from
   post-filter detections that were produced using it, so each rebuild can
   only remove more.
3. **Build the stratified gold set** (§5) from the Tier-1 output, sampling
   from *all four* predicted classes so it is not skewed to easy false
   positives. Nothing here is measured yet — §7 reports what the rules *did*,
   not how often they were right. This is the gap that matters most.
4. **Re-run the Wikidata source** when the endpoint recovers. Only the first
   page of the politician query landed during the outage; the builder pages
   and keeps partial results, so a re-run needs no code change.
5. **Train Tier 2** on those features and measure it against the gold set.
   The residual it would otherwise feed is already going to Tier 3 (§10).
6. **Then** decide whether the live scan should call the classifier inline
   (needs the model loaded in workers — see the 2.4 GB/worker limit) or stay a
   post-pass over stored detections. Post-pass is recommended: it keeps
   detection and judgement separable and never loosens stored results.
7. **Raise the mistitled-file bug** with the catalogue owners (§7.3). Six are
   confirmed; nothing establishes that they are the only ones, and the
   schema-over-title rule should stay regardless.

---

## 10. Tier 3 — the local LLM judge (2026-09-09)

Built: `pii_test/pii_tier3.py`, 31 self-tests passing with no server up.

**Scope.** The 164 pairs Tier 1 left `undecided` (`R12-residual`; 53 LOT 1,
111 LOT 2). Tier 3 never revisits a pair a rule already decided — the rules are
the high-precision layer and an 8B model is not entitled to overrule them.
Tier 2 does not exist yet, so Tier 3 runs straight on the Tier 1 residual.
Everything stays on the box: the values being judged are, by hypothesis, PII.

**Server, as measured.** vLLM at `http://127.0.0.1:8000/v1/chat/completions`,
model id `tier3-judge` (`qwen3-8b-awq`), `max_model_len` 4096.

* **Guided decoding is not enabled.** Both OpenAI `response_format:
  json_schema` and vLLM's `guided_json` are accepted and then silently
  ignored — the model replies in prose. Structure has to come from prompt
  discipline and a tolerant parser, not from schema enforcement. Hence the
  `CLASS: <label>` final-line convention rather than JSON.
* Qwen3 thinking mode is on by default. An early design disabled it
  (`chat_template_kwargs: {"enable_thinking": false}`) to save tokens; that was
  reversed, see below.
* Reasoning on costs ~320-810 completion tokens and 11-27 s per pair. The full
  residual is well under two hours, single-stream.

### 10.1 Three design decisions, each forced by a probe

**1. The model returns a class and nothing else — but it reasons first.**
PII judgement is genuinely subjective, and the trace earns its cost. With
reasoning *off* and a single-label prompt, the Lok Sabha member column came
back `{"pii_class": "present", "role": "public_office"}` — self-contradictory,
since that role is exactly what makes it publishable. With reasoning *on* the
same column classifies correctly as `permissible`. The trace is stored in
`evidence_json.llm_reasoning` as evidence for a human reviewer; it is not a
field the pipeline parses.

No role question and no self-reported confidence. A confidence float the model
invents would repeat exactly the mistake that makes the detector's 0.85
useless, and the role taxonomy was an intermediate the derived class no longer
needs.

**2. Publication is not evidence — the prompt has to say so.** The worst
failure found in probing: `Beneficiary Name` on a PM Awas Yojana list came back
`permissible`. The trace showed the model reasoning itself in a circle —
*"the data is being published on data.gov.in ... under the DPDP Act, data made
public under a legal obligation is outside the Act ... therefore
permissible."* Every dataset in this corpus is already published; that is the
thing under audit, not evidence about it. The system prompt now states this
outright, restricts `permissible` to the person's own public office, says
scheme beneficiaries are private however public the scheme is, and breaks ties
toward `present` (§5 puts recall on `present` above precision).

**3. Give the model context, not Tier 1's arithmetic.** The input is
deliberately minimal: dataset title, catalog title, description, the file's
header row, the flagged column, the entity type and up to 15 flagged values.
Cardinality, name-shaped fraction, corpus frequency and the quasi-identifier
list are all dropped. They are Tier 1's evidence, and Tier 1 already weighed
them and abstained — feeding them back only invites the model to re-derive a
rule that has already declined to fire.

`Conforms To` supplies the header row: the metadata carries the file's full
comma-separated header list, which beats the sibling set derived from columns
that happened to produce a detection (that derived set is sharp edge #1 — a
clean quasi-identifier column is invisible in it). It is present for all 111
undecided LOT 2 pairs but only 1 of the 53 LOT 1 pairs, so the loader prefers
it and falls back to the derived columns, and drops the line entirely when it
would only repeat the flagged column.

### 10.2 Running it on this box

The T4 has 15,360 MiB and **the repo's own PII service is already on it** —
`gunicorn -c pii_test/pii_service/gunicorn.conf.py` holds ~650 MiB. If vLLM is
launched without allowing for that, it pre-allocates almost the whole card
(~13.87 GiB), the first forward pass asks for another 192 MiB, and CUDA OOM is
raised *inside the vLLM engine loop* — which kills the engine and takes the
whole HTTP server down. It is not a slow request or a 500 to retry; the process
is gone. This happened twice while building this section.

Launch with headroom instead, e.g. `--gpu-memory-utilization 0.80` (and
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, as the OOM message itself
suggests), or stop the PII service first if it is idle.

### 10.3 Safety rails

* A reply that does not parse is **never** a verdict — the pair keeps its
  `undecided` class and its Tier 1 rule id, and the failure is recorded in
  `evidence_json.llm_error`. This covers a dead server, a truncated reply and
  an ambiguous one alike.
* A bare class token is accepted only when exactly one of the three appears;
  two candidate labels in the text is treated as no answer.
* Classes named inside the `<think>` block are stripped before parsing, so a
  discarded hypothesis cannot become the verdict.
* A run of consecutive transport failures **aborts the run** rather than
  grinding on. Without it, one OOM would mark all 164 remaining pairs
  `undecided (connection refused)` and destroy the Tier 1 verdicts they still
  carry. Unparseable replies deliberately do not trip it — only transport
  failures do.
* Write-back is an `UPDATE` on the existing rows: `tier='llm'`,
  `rule_id='T3-judge'`, the Tier 1 rule preserved in
  `evidence_json.tier1_rule_id`. Same single-writer caution as §7 — the script
  exits with a clear message if a scan holds the DuckDB lock.

### 10.4 Runs so far

**Run 3 (2026-09-10) is the result of record, written to `pii_column_class`.**
All 164 pairs in one server session at `max_tokens=2500`, 41 minutes, zero
transport errors.

| verdict | pairs |
|---|---|
| `false_positive` | 160 |
| `permissible` | 2 |
| `present` | 1 |
| `undecided` | 1 |

163 rows now carry `tier='llm'`, `rule_id='T3-judge'`, with the Tier 1 rule kept
in `evidence_json.tier1_rule_id`. `Accreditation Body` came back truncated and was
later set **`permissible` by a reviewer** (`tier='human'`, `rule_id='T4-reviewer'`,
finding 4). At dataset level (`pii_dataset_class` is a view, so it follows
automatically) the 124 datasets that were `undecided` became **122
`false_positive`, 1 `present`, 1 `permissible`**; no other dataset changed
class, and no pair in the table is `undecided` any more. The 164 rows as they stood
before the write are in `pii_test/EDA/tier3_prewrite_pii_column_class.csv`, so
the write can be reverted exactly.

**Earlier runs.** Run 1 (2026-09-09, dry, `max_tokens=1200`) gave 157 / 1 / 1 /
5; its 5 `undecided` were all truncation, and re-running them at 2500 made it
159 / 3 / 1 / 1. Run 2 (2026-09-10, 2500, with `--write`) died at pair 61 when
the vLLM process exited — not GPU contention this time, since the PII service
was stopped and 1.3 GiB was free — and the circuit breaker aborted with nothing
written. Runs 2 and 3, on two different vLLM launches, agree on all 60 pairs
they share.

What the runs established:

1. **Undecided meant truncation, not ambiguity.** At 1200 tokens the `<think>`
   block never closed on 5 pairs and no `CLASS:` line was reached; at 2500 all
   but one finish. The parser now refuses an unclosed think block explicitly,
   so truncation and ambiguity are no longer confusable in `llm_error`.
2. **Deterministic within a server session; near-ties can move across
   sessions.** The same prompt at `temperature=0` gives byte-identical replies
   within one session. But `59bfcb82` came back `permissible` in run 1 and
   `false_positive` in runs 2 and 3. Probing it in one session ruled out the
   token budget: the 1200-token reply is an exact prefix of the 2500-token
   one, so a bigger budget only lets the model finish. Run 1's session took a
   different reasoning path. Runs 2 and 3 agreeing 60/60 across two further
   launches says this is rare and confined to near-ties.
3. **Both `permissible` verdicts are mistitled files — and only a `present`
   there would matter.** Both are `Essential Information` pairs from the six mistitled
   datasets of §7.3, which carry identical values, differ only in title, and
   are exactly the near-ties of finding 2. Their verdicts should not be
   trusted in either direction. But all six datasets are already
   `permissible` through their `Member Name` column (`R6`) and the relatives
   and address columns around it (`R7`), so a `false_positive` or
   `permissible` verdict on `Essential Information` changes nothing at
   dataset level. A `present` one would — `present` outranks `permissible` in
   the roll-up — and the penalty run produced exactly that (finding 6).
4. **`Accreditation Body` (`fdf654ec`) is stuck in a loop, not short of
   tokens.** Its header says organisation, its values are people
   (`PROF.A.M.PATHAN`, `Prem Sharda`). Retried at 3,200 tokens — nearly all
   the 4,096 context leaves after its 839-token prompt — it still did not
   finish: the first third of its reasoning is 51 distinct sentences out of
   52, the last third 9 out of 52, one argument repeated about eleven times.
   More budget only buys more repetitions. That is the failure Qwen's own
   model card warns about (finding 5). With `presence_penalty=1.5` it
   finishes in 587 tokens as `false_positive`, reasoning that the column holds
   organisations, so the names are not people. That is what the system prompt
   tells it to do — the header decides, never the shape of the value — and it
   is often right: Indian trusts, colleges and hospitals are routinely named
   after people. Against it, these 11 values carry no organisation word
   (Trust, Society, College) and do carry personal forms: initials
   (`C.D.TETHI`, `D. RAJAN`), an academic title (`PROF.A.M.PATHAN`), lone
   given names (`Mina`, `RUKMINI`) and a role (`CHAIRPERSON`) — more like a
   person typed into the wrong field of a self-reported AISHE form. A reviewer
   settled it: accreditation there was done by individual professors, not a
   body, so the names are accreditors named in that official capacity —
   **`permissible`**, recorded as `tier='human'`, `rule_id='T4-reviewer'`.
   Neither the model nor a rule re-judges a reviewer's row.
5. **The decoding settings go against the model card.** Qwen3's README, for
   thinking mode: *"DO NOT use greedy decoding, as it can lead to performance
   degradation and endless repetitions"*, and for quantized models it
   *"strongly recommend[s]"* `presence_penalty=1.5`. `pii_tier3.py` runs
   thinking mode at `temperature=0` with no penalty — chosen for
   reproducibility, which it does deliver. `presence_penalty` is a
   deterministic logit adjustment, so it can be added without giving that up
   (the probe above returned the same 587 tokens twice).
6. **The penalty changes almost nothing — and the one change is wrong.** A dry
   re-run of all 164 (2026-09-10, same server session as run 3, so no
   restart confound) with `presence_penalty=1.5` plus a new prompt rule on
   organisations named after people: **162 of 164 verdicts identical**, nothing
   left `undecided`. The two that moved: `Accreditation Body` finished
   instead of looping, as `false_positive` — the model argued straight past
   the new rule ("PROF. or CHAIRPERSON are honorifics or roles, not personal
   names"), so the rule did not do the job it was written for; and
   `60836d47`, a mistitled `Essential Information` pair, went `false_positive`
   → `present`, calling Vajpayee, Lohia and Ambedkar "private individuals" on
   the tie-break. So greedy decoding had not distorted the 157 clean
   verdicts; its only cost was the one loop. Not written. Diff in
   `pii_test/EDA/tier3_penalty_compare.csv`.

Set the six aside and the result is simple: of the other 158 pairs, 156 are
`false_positive`, one is `present` and one is `permissible` by a reviewer.

The one `present` is `fd945b55`, `Name of the leaders` on "Name of Insurgent
groups in North East and their leaders" — real named individuals in a
law-enforcement record. The tie-break in the system prompt sends that to
`present`, which is the conservative call.

**Correction.** An earlier version of this section said the model cited
"William P. Vaughan" on `Essential Information` although no such value was in
its input. That was wrong: the name is one of the column's 15 sample values
and is in the prompt for all six datasets. The traces have not been shown to
invent evidence.

### 10.5 Still to do

- [x] Re-run all 164 at the 2500-token budget in one server session, then
      `--write`. Done as run 3 (§10.4).
- [x] ~~Decide what to do with the six mistitled `Essential Information`
      pairs.~~ Moot: the six datasets are `permissible` through `R6` whatever
      these pairs say (finding 3).
- [ ] Decide on `presence_penalty=1.5` as the default for future runs. The
      dry re-run (finding 6) says it only breaks loops; the new prompt rule
      did not help and could be dropped.
- [ ] Measure. Nothing here is scored; the gold set (§5, §9 item 3) is still
      what would turn these verdicts into a number. 160 of 164 landing on
      `false_positive` is consistent with the residual being what Tier 1
      declined to convict, but consistency is not accuracy.

---

## Sources

* Presidio default score: [issue #1190](https://github.com/microsoft/presidio/issues/1190), [issue #1372](https://github.com/microsoft/presidio/issues/1372), [context enhancement](https://microsoft.github.io/presidio/tutorial/06_context/), [FAQ](https://microsoft.github.io/presidio/faq/)
* LLM detection of personal data in structured datasets: [arXiv 2506.22305](https://arxiv.org/html/2506.22305v1)
* RECAP hybrid multilingual PII pipeline: [arXiv 2510.07551](https://arxiv.org/html/2510.07551v1)
* LLM-as-judge for NER labels (JudgeWEL): [arXiv 2601.00411](https://arxiv.org/pdf/2601.00411)
* Grab LLM data classification: [engineering.grab.com](https://engineering.grab.com/llm-powered-data-classification)
* Databricks LogSentinel: [databricks.com](https://www.databricks.com/blog/logsentinel-how-databricks-uses-databricks-llm-powered-pii-detection-and-governance)
* NVIDIA NeMo LLM column classification: [docs.nvidia.com](https://docs.nvidia.com/nemo/microservices/25.10.0/generate-private-synthetic-data/synthesize/replace-pii/llm-classification.html)
* Sato contextual semantic type detection: [VLDB 2020](https://www.vldb.org/pvldb/vol13/p1835-zhang.pdf), [Sherlock](https://www.researchgate.net/publication/354723631_Sherlock_A_Deep_Learning_Approach_to_Semantic_Data_Type_Detection)
* Zero-shot column-header topic classification: [arXiv 2403.00884](https://arxiv.org/abs/2403.00884)
* Weak supervision: [Stanford SAIL](https://ai.stanford.edu/blog/weak-supervision/)
* Public-figure lists: [Wikidata every politician](https://www.wikidata.org/wiki/Wikidata:WikiProject_every_politician), [OpenSanctions wd_peps](https://www.opensanctions.org/datasets/wd_peps/)
* Legal: [DPDP Act 2023](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf), [s.3(c)(ii) analysis](https://lawschoolpolicyreview.com/2026/01/13/publicly-available-data-under-the-dpdp-act-the-limits-of-exemptions-in-ai-driven-processing/), [NDSAP Implementation Guidelines 2.4](https://www.data.gov.in/sites/default/files/NDSAP%20Implementation%20Guidelines%202.4.pdf), [NIST SP 800-122](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-122.pdf)
