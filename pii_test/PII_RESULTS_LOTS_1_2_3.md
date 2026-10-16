# PII results across lots 1, 2 and 3, and the KCC transcripts

Written 2026-10-07, last updated 2026-10-12. Covers the PII test results for
`dublin_core_metadata` (lot 1), `dublin_core_remaining` (lot 2) and `dublin_core_lot3`
(lot 3), and the Kisan Call Centre (KCC) transcripts ([section 7](#7-kcc-transcripts)).
A short version for readers new to the project is `PII_RESULTS_LOTS_1_2_3_v2.md`.

On 2026-10-12 every dataset the pipeline had judged `present` or `permissible` in lots 2 and 3
was read again and the false detections were removed. The counts in this report are the final
ones after that review, unless a table says "pipeline". How the review was done is in
[section 2](#2-how-to-read-the-numbers). Sources for every number are in
[section 10](#10-sources).

No detected values (names, phone numbers, email addresses) are reproduced here. Dataset titles
and column headers are.

---

## 1. Summary

Final counts, after the false detections were removed:

| | Lot 1 | Lot 2 | Lot 3 | All three |
|---|---|---|---|---|
| Table | `dublin_core_metadata` | `dublin_core_remaining` | `dublin_core_lot3` | |
| Rows in the table | 206,972 | 117,721 | 29,598 | 354,291 |
| Scanned | 123,578 (59.7%) | 111,638 (94.8%) | 28,832 (97.4%) | 264,048 |
| Files in which the scan detected something | 3,917 | 5,878 | 2,387 | 12,182 |
| **`present`: personal data of private individuals** | **0** | **32** | **27** | **59** |
| **`permissible`: people in a public or professional role, office and business contacts** | **8** | **330** | **300** | **638** |
| False detections removed (not personal data) | 3,909 | 5,518 | 2,060 | 11,487 |

- Lot 2's `present` and `permissible` counts each include one file the scan could not read,
  found by the review. Without them the three result rows add up to the files with a
  detection.
- Lot 3 is counted in table rows. One file is listed twice in the table, so the 300
  `permissible` rows are 299 files.
- Of the 305,565 detections stored, 116,379 are left: 10,953 in `present` files and 105,426 in
  `permissible` ones. 189,186 were removed as false.

What the review changed:

| Pipeline verdict | Files | Final `present` | Final `permissible` | Removed as false |
|---|---|---|---|---|
| Lot 2 `present` | 231 | 31 | 100 | 100 |
| Lot 2 `permissible` | 256 | 0 | 229 | 27 |
| Lot 2, no detections (two unreadable files) | 2 | 1 | 1 | 0 |
| Lot 3 `present` (rows) | 237 | 27 | 178 | 32 |
| Lot 3 `permissible` (rows) | 128 | 0 | 122 | 6 |
| Lot 1 `permissible` (not reviewed again) | 8 | 0 | 8 | 0 |

What the numbers say:

1. **59 datasets hold personal data of private individuals: 32 in lot 2, 27 in lot 3, none in
   lot 1.** They are listed in sections [5.4](#54-the-32-present-files) and
   [6.4](#64-the-27-present-rows).
2. **The most serious are four Smart Cities files about patients, children and victims.**
   - "Pimpri Chinchwad Municipal Corporation COVID 19 Admitted_API": 100 COVID patients with
     name, address, age, mobile number and comorbidity.
   - "TIRUPPUR Covid Patient as on 29/06/2020": named patients with age, ward and test result.
   - "Cases of Child Missing : 2020 to 2021" (Tiruppur): children named with father's name,
     home address, mobile number and caste.
   - "Traffic Accidents : 2020 to 2021" (Tiruppur): victims named with address, mobile number,
     caste and occupation.
3. **The rest of the 59** are 13 Minor Irrigation Census files (scheme owners' names, field
   staff's mobile numbers), 13 Rajya Sabha answer tables (accused persons, encroachers, the
   dead and their next of kin, beneficiaries), 22 lot 3 files of scheme beneficiaries and
   property owners (16 of them fishermen's relief payments), 5 advocate rolls that give
   father's or husband's name, date of birth or community, and 2 single files (property
   owners on building permissions in Thane; a merchant registration survey with PAN numbers).
4. **94% of the files with a detection were false detections.** 11,487 of 12,182 files hold
   no personal data: village names, crime heads, health indicators, crops and project names
   read as people, and ordinary numbers read as phone or Aadhaar numbers.
5. **The pipeline's `present` verdict was right for 58 of 468 files (12%).** 278 of the others
   are people in a public role or office contacts, and 132 are not personal data. The
   `permissible` verdict was right for 351 of 384 (91%).
6. **71 of the 638 `permissible` datasets are judgment calls**, marked as sets so they can be
   moved together: 16 parliamentary member directories that also give relatives' names and
   home addresses (nine of them under an unrelated title), 40 advocate and notary registers,
   and 15 lists of students, volunteers, service-centre operators and similar. If all 71
   were counted as `present`, the total would be 130.
7. **Lot 1 is closed as holding no PII (decided 2026-10-08).** Its September re-scan covered
   60% of the files; the other 83,359 keep a May result that found nothing and will not be
   re-scanned.
8. **Lot 2 is 94.8% checked.** Of the 6,083 rows not checked, 6,039 cannot be downloaded
   (5,006 return HTTP 404), 43 are not tables and one file is empty.
9. **The review removed false detections; it did not look for misses.** Files the pipeline
   judged `false_positive` or found nothing in were not read again. Two misses were found by
   chance, and three of the 59 files were caught on a phone number or an address while the
   names beside it went undetected ([section 9](#9-limits-and-recommended-next-steps)).
10. **KCC holds farmers' personal data in at least 408 files.** Of the 376 KCC files the
    September run called `present`, 216 hold farmer records and 160 were flagged on phone
    numbers alone, which is not confirmed. The scan of every row finished on 2026-10-09 and
    is not classified yet ([section 7](#7-kcc-transcripts)).

---

## 2. How to read the numbers

- **Detection**: one value the scan read as a person's name, phone number, email address or
  ID number.
- **Flagged column**: a column of one file with at least one detection. Verdicts are given per
  flagged column, never per value.
- **Verdict classes**:
  - `false_positive`: the column does not hold personal data (a list of crops, a place name).
  - `permissible`: personal data of people acting in a public or official role, or an
    institution's contact details (MPs, office phone numbers).
  - `present`: personal data of private individuals.
- **File verdict**: the most serious verdict among the file's flagged columns
  (`present` over `permissible` over `false_positive`).
- **Who decides**: Tier 1 is a set of fixed rules (R1 to R12, listed in
  [section 11](#11-rule-glossary)). Columns the rules cannot decide go to Tier 3, a local LLM
  judge (Qwen3-8B).
- **Scan flag** (`pii_detected` / `pii_found`): the scan's own yes/no per file, set before any
  classification. It is a cruder signal than the verdict and the two often disagree.

What the scan reads in each file:

- Only the first 250 rows. In lot 1, 159,407 of the 206,895 files with a known row count
  (77%) are longer than that.
- Only columns that could hold text about people. Purely numeric tables are marked "no
  scannable columns" and nothing in them is read. In the lot 1 re-scan, 327,558 of 7,111,173
  columns (4.6%) were read.

### The final result and the review behind it

The pipeline's verdicts over-call, so on 2026-10-12 they were checked one by one. The checking
was done by Claude, the AI assistant working on the project, not by a human reviewer:

- **What was read.** Every dataset the pipeline judged `present` (231 files in lot 2, 237 rows
  in lot 3) or `permissible` (256 and 128): the title, all headers, each flagged column with a
  sample of its detected values, and the cells themselves where that did not settle it.
- **The classes are the pipeline's own**, applied as follows.
  - `present`: people named as beneficiaries, patients, victims, accused, owners or next of
    kin; or a register that gives relatives' names, date of birth or community.
  - `permissible`: people named in a public, official or professional role (members,
    officials, principals, scientists, athletes, award winners, advocates and notaries on a
    register), and the contact details of offices, institutions and businesses.
  - `false_positive`: not personal data. Place, scheme, institution and disease names read as
    people; ordinary numbers read as phone or Aadhaar numbers.
- **Detections.** A detection is kept when its dataset is finally `present` or `permissible`
  and it sits in a column the pipeline did not reject. Six columns the pipeline had rejected
  were kept because they do hold personal data (beneficiary names, PAN numbers and similar).
- **Judgment calls.** Where the rule above gives `permissible` but the case can be argued, the
  dataset is marked "judgment call" with the reason, so each set can be moved to `present`
  in one step.
- **No pipeline output was changed.** The decisions are in
  `pii_test/final_review/final_results.csv`, written by `pii_test/build_final_review.py`. A
  pipeline re-run does not carry them forward.
- **Limits.** It is one reviewer's judgment (an AI assistant's, with no second reviewer),
  per dataset and column, not per value: a kept
  column can still contain single false values. Datasets the pipeline judged `false_positive`
  or found nothing in were not read again. Lot 1's eight `permissible` files were not
  reviewed again; lot 1 was closed on 2026-10-08.

---

## 3. The three lots went through different pipelines

| | Lot 1 | Lot 2 | Lot 3 |
|---|---|---|---|
| Scan dates | 1-2 Sep 2026 (59.7% of rows); 8-11 May 2026 result kept for the rest | 8 Oct 2026 | 1 Oct 2026 |
| Scan code | After the 25 Aug fixes | Current | Current |
| Formats scanned | CSV | CSV, Excel, JSON (first 250 records) | CSV, Excel, JSON (first 250 records) |
| Classified | 2-10 Sep 2026 | 8 Oct 2026, with rules changed on 22 Sep | 1 Oct 2026, with rules changed on 22 Sep |
| Context given to the classifier | Title and catalogue; only the headers of columns that had detections | Title, catalogue, description, publisher, sector, and every header of the file | Same as lot 2 |
| Columns sent to the LLM judge | 53 | 2,935 | 1,168 |
| Results stored in | `pii_detections_lot1`, `pii_column_class` | CSV files in `pii_test/lot2/` | CSV files in `pii_test/lot3/` |
| Verdicts reviewed one by one | No; lot closed on 8 Oct 2026 | 12 Oct 2026 | 12 Oct 2026 |

Lot 2 also has an older result: 29,818 of its CSVs were scanned on 4-5 Aug 2026 with the scan
code of that time and classified in September. Those tables (`pii_detections_lot2`,
`pii_column_class`) are untouched. [Section 5.7](#57-what-changed-against-the-august-scan)
shows how the verdicts moved.

---

## 4. Lot 1: `dublin_core_metadata`

206,972 rows, all published by the Ministry of Health and Family Welfare, in 365 catalogues.
170,691 rows (82%) are HMIS tables.

### 4.1 Coverage

The local table's `pii_tested` and `pii_detected` columns read `'0'` on every row since the
lake sync of 29 Sep. The figures below come from the flagged copy the re-scan uploaded to S3
on 2 Sep (`pii-results/dublin_core_metadata_snapshot.parquet`).

| Status | Rows | Share |
|---|---|---|
| Scanned 1-2 Sep 2026 with the working pipeline | 123,578 | 59.7% |
| Result kept from the May pass (3 rows from 3 Aug) | 83,359 | 40.3% |
| No usable result (25 files errored in September and stay untested; 10 are marked tested with no timestamp) | 35 | 0.02% |

**Why 83,359 rows were not re-scanned.** The scan skips any row already marked tested
(`run_pii_s3.py`, `pending["pii_tested"] != True`). Before the September run only part of the
table had been reset, so whole batches were barely touched:

| Batches | Files re-scanned in September |
|---|---|
| 1, 2, 17, 24-42 | all or nearly all 5,000 each |
| 14, 15 | 4,321 and 4,540 |
| 13, 16, 18, 10 | 2,001, 1,739, 1,711, 1,422 |
| 8, 12 | 655 and 133 |
| 3-7, 9, 11, 19-23 | 2 to 17 each |

**Why the May result cannot stand in for a scan.** No May-dated row carries a flag or a
stored detection. The log for that period shows a batch-analyser warning with a fallback to
cell-by-cell analysis on every run (133,608 warnings), 22,677 files that failed to decode and
1,022 that were not found, and the scan code predates the August fixes. Which of these
explains the silence is not established. What shows the result is not equivalent to a scan is
the comparison inside the same catalogues:

| Catalogue | September files with a detection | May files with a detection |
|---|---|---|
| Performance of key HMIS indicators across sub districts of Uttar Pradesh | 256 of 325 | 0 of 75 |
| ... of Bihar | 120 of 152 | 0 of 38 |
| ... of Assam | 93 of 180 | 0 of 27 |
| ... of Punjab | 93 of 113 | 0 of 22 |
| All 34 catalogues where September found detections and some files kept the May result | - | 0 of 4,535 |

Where the 83,359 May-result files sit:

| Their catalogue | Files |
|---|---|
| Re-scanned sibling files produced no detection | 78,715 |
| Re-scanned sibling files produced detections (34 catalogues) | 4,535 |
| Not re-scanned at all (Rural Health Statistics 2017, 77 files; Key Indicators of NFHS, 31; one other) | 109 |

If the May-result files behaved like their re-scanned siblings, about 717 of them would carry
detections. Nearly all of those would be the `Indicator` false positive described below, so
the likely effect on the count of real findings is small. It is not known to be zero: 731 of
the May-result files belong to the "HMIS district level item wise and month wise comparison"
catalogues. That is the family in which six files turned out to hold a Lok Sabha member
directory under an HMIS title ([section 4.4](#44-the-8-permissible-files)), and a mistitled
file cannot be predicted from its catalogue.

Of the 123,577 re-scanned files that logged a scan line, 17,854 (14.4%) had no scannable
column.

### 4.2 What was detected

14,042 detections in 3,917 files (3.2% of the files re-scanned), across 3,997 flagged columns
under 36 distinct headers.

| Detected as | Detections | Share |
|---|---|---|
| Person name | 12,215 | 87.0% |
| Email address | 1,359 | 9.7% |
| Phone number | 468 | 3.3% |

The detections are concentrated: the 8 `permissible` files hold 8,300 of the 14,042 (59%).
The other 3,909 files share 5,742, with a median of one detection per file.

The scan's own flag was set on 281 files: 273 of them were later judged `false_positive` and
8 `permissible`. Another 3,636 files had detections without being flagged; all were judged
`false_positive`.

### 4.3 Verdicts

| Verdict | Flagged columns | Files | Decided by |
|---|---|---|---|
| `false_positive` | 3,946 (98.7%) | 3,909 | `R1-controlled-vocab` 3,809; `R2-column-shape` 86; LLM judge 51 |
| `permissible` | 51 (1.3%) | 8 | `R7-directory-context` 42; `R6-office-allowlist` 6; LLM judge 2; `R4-institutional-channel` 1 |
| `present` | 0 | 0 | - |

Three headers account for 3,806 of the 3,997 flagged columns (95%), all false positives:

| Header | Flagged columns |
|---|---|
| `Indicators - Item` | 1,832 |
| `Indicator` | 1,500 |
| `Indicators` | 474 |

These are HMIS indicator labels read as person names. The remaining false positives are survey
answer columns in Annual Health Survey files (`reason_for_non_vaccination` 55,
`check_up_at_home_by` 18, `healthscheme_1` 16) and a few free-text columns.

### 4.4 The 8 `permissible` files

| Files | What they hold | Flagged columns |
|---|---|---|
| 6, titled "Data Item Comparison Report of Sikkim / All India ..." | The Lok Sabha member directory, uploaded under HMIS titles (confirmed earlier as a backend upload error) | `Member Name`, `Father Name`, `Mother Name`, `Spouse Name`, `Delhi Address`, `Permanent Address`, `Email ID`, `Essential Information` |
| 2, Hospital Directory (National Health Portal) | Hospital contact lists | `Contact Details`, `Email address`, `Telephone`, `Mobile_Number`, `Emergency_Num`, `Address_Original_First_Line` |

The six directory files are `permissible` because the people are MPs. They still carry MPs'
relatives' names and home addresses under titles that say "HMIS comparison report", so the
upload error is worth fixing whatever the verdict.

### 4.5 What lot 1's result means

- Final result: no `present` file, 8 `permissible`, and 3,909 files of false detections
  removed. These are the pipeline's verdicts; lot 1 was not part of the review of
  2026-10-12. The six member directories are marked as a judgment call in the workbooks.
- No file was judged `present`. That holds for the 123,578 re-scanned files only.
- The lot was closed on 2026-10-08 as holding no PII, so the other 83,359 files will not be
  re-scanned.
- The headline for lot 1 is the false-positive pattern, not personal data: one header family
  produced 95% of the flagged columns.
- The scan looks for direct identifiers. The 1,430 Annual Health Survey files appear to be
  unit-level survey records (columns such as `abortion_performed_by`, `death_symptoms`,
  `willing_to_get_pregnant`). They contain no names, so the scan passes them, but whether
  unit-level health records are safe to publish is a separate question this test does not
  answer.

---

## 5. Lot 2: `dublin_core_remaining`

117,721 rows from 156 publishers. Lot 2 was completed on 2026-10-08: the 76,565 files that
were on neither S3 nor this server were downloaded from data.gov.in, and every file was then
scanned and classified in one pass with the current code. That pass replaces the August
result as the result of record; [section 5.7](#57-what-changed-against-the-august-scan)
compares the two.

### 5.1 Coverage

| Status | Rows | Share |
|---|---|---|
| Scanned and classified | 111,638 | 94.8% |
| Not scanned: file could not be downloaded | 6,039 | 5.1% |
| Not scanned: file is not a table (KML, PDF, APK, zip ...) | 43 | 0.04% |
| Scan error (empty file) | 1 | 0.0% |

Where the scanned files came from:

| Source | Files scanned |
|---|---|
| Already on S3 (29,822 CSVs, of which 29,818 were scanned in August, plus 5,148 Excel files never scanned before) | 34,975 |
| Downloaded from data.gov.in on 2026-10-08 | 76,491 |
| Fetched earlier in the retry of the undownloadable list | 172 |

The download got 76,527 of the 76,565 missing files. The 6,039 rows without a file are the
6,001 on the undownloadable list that failed again on its 6 Oct retry, plus 38 new failures:

| Why the file could not be fetched | Rows |
|---|---|
| HTTP 404 from data.gov.in | 5,006 |
| External host not answering (`nlcpr.mdoner.gov.in` 378, `krishi.icar.gov.in` 114, two `164.100.47.x` hosts 179, `api.data.gov.in` 37, `microdata.gov.in` 29, others) | 794 |
| Server returned an HTML page instead of data | 99 |
| Format the downloader does not fetch (zip 49, WMS 21, resource type 5: 22) | 92 |
| Other server errors | 48 |

By publisher, 4,885 of the 6,039 are Census files, 378 Development of North Eastern Region,
122 Rajya Sabha and 117 Agricultural Research and Education.

Of the 111,639 files the scan opened:

- 77,956 (69.8%) had no scannable column.
- 6,320 (5.7%) reached the 250-row limit.
- 6 ragged CSVs were first refused by the reader and were scanned after their rows were
  padded to one width.

### 5.2 What the scan detected, and what is left

The scan stored 235,628 detections in 5,878 files (5.3% of files scanned), across 6,515
flagged columns under 1,491 distinct headers.

| | Files | Detections |
|---|---|---|
| Detected by the scan | 5,878 | 235,628 |
| Left after the review, `present` | 31 | 8,512 |
| Left after the review, `permissible` | 329 | 58,731 |
| Removed as false | 5,518 | 168,385 |

The removed detections include those in rejected columns of the files that were kept. Two
more files were added by the review without any detection
([5.4](#54-the-32-present-files), [5.5](#55-the-330-permissible-files)).

What the scan detected, before the review:

| Detected as | Flagged columns containing it | Files |
|---|---|---|
| Person name | 6,285 | 5,838 |
| Phone number | 217 | 102 |
| Email address | 52 | 47 |
| Aadhaar number | 16 | 12 |
| PAN number | 1 | 1 |

- None of the Aadhaar hits is a real Aadhaar number. They are figures in economic tables, a
  laboratory list and similar, and all were removed.
- The PAN column is real: 65 PAN numbers in a merchant registration survey. The pipeline had
  rejected that column; the review kept it.

### 5.3 Verdicts

Per table row:

| Result | Pipeline | Final |
|---|---|---|
| No detections | 105,760 | 105,758 |
| `false_positive` | 5,391 | 5,518 |
| `permissible` | 256 | 330 |
| `present` | 231 | 32 |

By publisher, final:

| Publisher | `present` | `permissible` |
|---|---|---|
| Rajya Sabha | 13 | 208 |
| Water Resources (Minor Irrigation Census) | 13 | 0 |
| Housing and Urban Affairs (Smart Cities Mission) | 6 | 57 |
| Lok Sabha Secretariat | 0 | 28 |
| Science and Technology (biotechnology institutes) | 0 | 22 |
| All others | 0 | 15 |

How the pipeline reached its verdicts, per flagged column (before the review):

| Pipeline verdict | Flagged columns | By rules | By the LLM judge |
|---|---|---|---|
| `false_positive` | 5,779 (88.7%) | 2,967 | 2,812 |
| `present` | 381 (5.8%) | 306 | 75 |
| `permissible` | 355 (5.4%) | 307 | 48 |

The rules left 2,935 of the 6,515 flagged columns (45%) undecided, and the judge ruled 2,812
of them `false_positive`. Three columns came back unfinished from the judge and were asked
again with its loop-breaking setting (`presence_penalty=1.5`); all three then got a verdict.

How often each rule's `present` verdict held up, for the 231 files the pipeline called
`present`:

| Decided by | Files | Final `present` | Final `permissible` | Removed as false |
|---|---|---|---|---|
| `R10-individual-records` alone | 81 | 16 | 7 | 58 |
| `R11-personal-channel` alone | 61 | 2 | 31 | 28 |
| LLM judge alone | 57 | 9 | 38 | 10 |
| `R11` and the judge | 16 | 0 | 16 | 0 |
| `R5-private-absolute` | 12 | 4 | 4 | 4 |
| `R9-private-contextual`, with or without the judge | 4 | 0 | 4 | 0 |

### 5.4 The 32 `present` files

32 files in 14 catalogues hold personal data of private individuals.

| Dataset | Files | What it holds |
|---|---|---|
| 6th Minor Irrigation Census, Surface Flow and Surface Lift schedules, by state (Water Resources) | 13 | `individual_owner_name` of each irrigation scheme; `enumerator_name`, `enumerator_mobile`, `checked_by_name`, `checked_by_mobile` of the field staff |
| Rajya Sabha answer tables | 13 | Listed below |
| "Pimpri Chinchwad Municipal Corporation COVID 19 Admitted_API" (Smart Cities Mission) | 1 | 100 patients: name, address, age, gender, mobile number, comorbidity, hospital, admission date and outcome |
| "TIRUPPUR Covid Patient as on 29/06/2020" (Smart Cities Mission) | 1 | `Patient Id/Name` beside age, gender, ward, coordinates, test result and current status |
| "Cases of Child Missing : 2020 to 2021" (Smart Cities Mission, Tiruppur) | 1 | `Name and Address`: children (aged 15 to 17 in the rows read) with father's name, home address, mobile number and caste |
| "Traffic Accidents : 2020 to 2021" (Smart Cities Mission, Tiruppur) | 1 | `Name and Address`: victims' names with address, mobile number, caste and occupation |
| "smart_sarth_registration_app" (Smart Cities Mission, Pimpri Chinchwad) | 1 | A merchant registration survey: shop and owner names, 65 PAN numbers, mobile numbers; the export also has respondent email and IP address columns |
| "Building CC Permissions in Thane : 2021" (Smart Cities Mission) | 1 | `Owner Name` beside the property address |

The 13 Rajya Sabha answer tables:

| What is named | Files | Flagged column |
|---|---|---|
| People accused in registered cases | 2 | `Name of accused`, `Name of Accused` |
| People occupying public land in Delhi (encroachment cases) | 2 | `Name of Squatter`, `List of Institutional / Individuals` |
| Soldiers and paramilitary personnel who died, and their next of kin, with the benefits paid | 2 | `Name`, `Name of next of kin` |
| Workers who died in coal-mine accidents | 1 | `NAME OF THE DECEASED` |
| A person killed in a police encounter | 1 | `Victims` |
| Couples given a grant under the Dr. Ambedkar scheme for inter-caste marriages | 1 | `Name of the couple and address` |
| Minority beneficiaries of a micro-finance scheme (name, community, sex, address) | 1 | `Address`, `Name Beneficiary` |
| Sportspersons given welfare-fund assistance or help with medical treatment, with purpose and amount | 3 | `Name`, `Name of sportsperson`, `Name of Sportsperson` |

How these 32 were found matters for what else may be there:

- **One was not detected at all.** The Pimpri Chinchwad patient file is base64-encoded JSON
  saved as `.csv`, so the scan read no text in it. The review found it by opening the other
  files of the same catalogue.
- **Three were caught on something other than the names.** The missing-children and
  traffic-accident files were flagged on a phone number; the names in the same cell were not
  detected. The micro-finance file was flagged on its `Address` column, and the pipeline had
  rejected the beneficiary-name column.
- **Three had been filed under office contacts in the first reading** (missing children,
  traffic accidents, merchant registration). Reading the cells moved them here.
- One of the two "accused" files carries the title "State/ut-wise female literacy rate ...",
  so its title does not describe its content.
- One of the 13 Minor Irrigation Census files (Surface Flow, Gujarat) shows only field
  staff's mobile numbers in the rows read; its owner-name column is empty or undetected there.

### 5.5 The 330 `permissible` files

330 files in 131 catalogues: 229 of the pipeline's 256, 100 moved from `present`, and one
added by the review.

| What | Files |
|---|---|
| Rajya Sabha: attendance registers, bills, special mentions, assurances, member lists; athletes, coaches, artists and award winners named in answers | 208 |
| Lok Sabha: attendance registers and member lists | 28 |
| Smart Cities files: college principals, municipal officers, police stations, hospitals, helplines, service centres | 57 |
| Biotechnology institutes: principal investigators, scientists, faculty, seminar speakers, PhD students | 22 |
| Others: heads of higher-education institutions, jails, hotels, tour operators, laboratories, ICAR contacts | 15 |

The file added by the review is "Pimpri Chinchwad Municipal Corporation COVID-19 API":
hospital in-charge names and contact numbers, base64-encoded like the patient file.

Judgment calls, 21 files. They are `permissible` by the rule in
[section 2](#2-how-to-read-the-numbers) and marked so they can be moved as sets:

| Set | Files | Why it is arguable |
|---|---|---|
| Member directories of the Lok Sabha and Rajya Sabha | 10 | They give the member's father's, mother's and spouse's names, home addresses and phone numbers |
| Lists of PhD awardees, short-term trainees and research fellows | 5 | Students, not office holders |
| Citizen facilitation centre lists (Pimpri Chinchwad) | 2 | Operators' personal email addresses and mobile numbers |
| Volunteer animal rescuers (Thane); child day-care workers (Tiruppur); self-help group contacts (Tiruppur); leaders of insurgent groups | 4 | Individuals named, some with mobile numbers, in a list that is not an office |

Three of the ten member directories carry an unrelated title:

| Title in the catalogue | Publisher |
|---|---|
| Month-wise FEE (Foreign Exchange Earnings) from Tourism in Crores ... | Ministry of Tourism |
| Month-wise FEE (Foreign Exchange Earnings) from Tourism in billion US dollars ... | Ministry of Tourism |
| Implementation Report Under NREGA (All India) upto 2011-12 | Statistics and Programme Implementation |

All three have the columns of the parliamentary member directory (`Member Name`,
`Father Name`, `Mother Name`, `Spouse Name`, `Delhi Address`, `Permanent Address`,
`Email ID`). This is the same upload error as the six lot 1 files in
[section 4.4](#44-the-8-permissible-files), and worth fixing whatever the verdict.

### 5.6 What was removed as false

5,518 files hold no personal data.

**5,391 the pipeline itself judged `false_positive`.** Main families:

| Family | Example headers | Flagged columns |
|---|---|---|
| Census area names | `Name` (village, town and district names in Census tables) | 1,788 |
| Project and facility names | `Project Name`, `Name of the Project`, `Project`, `Facility Name` | 515 |
| Routes and stations | `Bus Route Name`, `STATION`, `Railway Station Name` | 437 |
| NCRB crime categories | `Crime Head`, `Crime Head (Col. 2)`, `Crime Head (Col.3)` | 401 |

**100 the pipeline had called `present`:**

| What was flagged | Files |
|---|---|
| Rajya Sabha answer tables: names of public-sector companies, projects, NGOs, urban local bodies, posts, surveys, and figures read as phone numbers | 36 |
| Higher-education survey 2015-16: the institution's `name` and address | 16 |
| Smart Cities files: coordinates, heritage sites, facility names, ward names, expenditure figures | 16 |
| Economic tables (GDP, GNP, balance of payments, imports, money stock) read as phone and Aadhaar numbers | 8 |
| Census tables: village and town names in a `Name` column | 8 |
| Geological map names | 5 |
| Telephone-subscriber statistics, spring elevations, district GDP, coal receipts, forest produce and others | 11 |

**27 the pipeline had called `permissible`:**

| What was flagged | Files |
|---|---|
| Gram panchayat names in Mission Antyodaya survey files | 11 |
| Ratios, volumes, amounts and project numbers read as office phone numbers | 6 |
| City, locality, project and system names; hospital and institute addresses | 6 |
| College and school names | 4 |

### 5.7 What changed against the August scan

The 29,818 CSVs scanned in August were scanned again. Verdict then against verdict now:

| August verdict | Files | Now no detections | Now `false_positive` | Now `permissible` | Now `present` |
|---|---|---|---|---|---|
| No detections | 27,383 | 27,326 | 57 | 0 | 0 |
| `false_positive` | 2,405 | 1,867 | 533 | 2 | 3 |
| `permissible` | 3 | 1 | 0 | 2 | 0 |
| `present` | 27 | 8 | 0 | 1 | 18 |

- The filter changes made after August removed most false positives at the scan itself: 1,867
  of the 2,405 files flagged then produce no detection now.
- 18 of the 27 files judged `present` in August came back `present` from the pipeline again.
  They are the same over-calls: after the review they are `permissible` (office contacts,
  named officials, the insurgent-leaders file) or removed as false
  ([section 5.6](#56-what-was-removed-as-false)).
- The one column a human reviewer had settled in September (`Accreditation Body`, ruled
  `permissible`) no longer produces a detection, so its file is now "no detections". No
  reviewer verdict was overridden by the new run.
- The August results are still in `pii_detections_lot2` and `pii_column_class`. The new
  results are CSV files in `pii_test/lot2/`; nothing was written to the database.

### 5.8 What lot 2's result means

- Lot 2 is 94.8% checked, and the 5.1% that is not cannot be downloaded.
- 32 files hold personal data of private individuals. The most serious are the two COVID
  patient files, the missing-children and traffic-accident files from Tiruppur, and the Rajya
  Sabha tables naming accused persons, encroachers, the dead and their families.
- The pipeline's `present` was right for 31 of 231 files. `R11` alone was right for 2 of 61,
  `R10` alone for 16 of 81.
- Rajya Sabha's 33,048 files hold 13 `present` and 208 `permissible` ones. Smart Cities
  Mission files are a small part of the lot and hold 6 of the 32 `present` files, including
  the four most serious.
- Four of the 32 were found only because a person read the file. That is the reason to treat
  32 as a floor ([section 9](#9-limits-and-recommended-next-steps)).

---

## 6. Lot 3: `dublin_core_lot3`

29,598 rows (29,597 distinct UUIDs) from 309 publishers. Three publishers hold 79% of the
rows: Tamil Nadu Department of Economics and Statistics (12,215), Tamil Nadu Public Health
and Preventive Medicine (6,140) and Karnataka Agriculture Department (4,934).

### 6.1 Coverage

| Status | Rows | Share |
|---|---|---|
| Scanned | 28,832 | 97.4% |
| Not scanned: no file found | 743 | 2.5% |
| Not scanned: not a table (13 failed JSON downloads, XML, KML, APK) | 22 | 0.1% |
| Scan error (empty file) | 1 | 0.0% |

Of the 28,832 scanned:

- 15,893 (55.1%) had no scannable column.
- 4,694 (16.3%) reached the 250-row limit. 4,349 of those are JSON files, which were scanned
  as their first 250 records.
- 4,767 rows are JSON files in all; 167 of them were judged `false_positive` and the other
  4,600 had no detections.

### 6.2 What the scan detected, and what is left

The scan stored 55,895 detections in 2,386 files, across 2,900 flagged columns under 747
distinct headers.

| | Rows | Detections |
|---|---|---|
| Detected by the scan | 2,387 | 55,895 |
| Left after the review, `present` | 27 | 2,441 |
| Left after the review, `permissible` | 300 | 38,834 |
| Removed as false | 2,060 | 14,620 |

What the scan detected, before the review:

| Detected as | Flagged columns containing it | Files |
|---|---|---|
| Person name | 2,538 | 2,297 |
| Phone number | 265 | 216 |
| Email address | 118 | 115 |
| Aadhaar number | 2 | 2 |
| Farmer registration ID | 1 | 1 |

The two Aadhaar hits are counts in a consumer-commission statistics table, and the farmer-ID
hit is not a farmer ID. Neither is left in the final result.

### 6.3 Verdicts

Per table row:

| Result | Pipeline | Final |
|---|---|---|
| No detections | 26,445 | 26,445 |
| `false_positive` | 2,022 | 2,060 |
| `permissible` | 128 | 300 |
| `present` | 237 | 27 |

By publisher, final:

| Publisher | `present` | `permissible` |
|---|---|---|
| Karnataka departments | 20 | 60 |
| Ministry of Law and Justice (advocate and notary lists) | 5 | 40 |
| Tamil Nadu departments | 1 | 169 |
| Kerala | 1 | 2 |
| All others | 0 | 29 |

How the pipeline reached its verdicts, per flagged column (before the review):

| Pipeline verdict | Flagged columns | By rules | By the LLM judge |
|---|---|---|---|
| `false_positive` | 2,316 (79.9%) | 1,268 | 1,048 |
| `present` | 313 (10.8%) | 216 | 97 |
| `permissible` | 271 (9.3%) | 248 | 23 |

The rules left 1,168 of the 2,900 flagged columns (40%) undecided, against 45% in lot 2 and
1% in lot 1. Lot 3's headers are far more varied (747 against 36 and 200), so fewer match a
rule.

How often the `present` verdict held up, for the 237 rows the pipeline called `present`:

| Decided by | Rows | Final `present` | Final `permissible` | Removed as false |
|---|---|---|---|---|
| LLM judge alone | 73 | 19 | 52 | 2 |
| `R11-personal-channel`, no other `present` rule | 44 | 1 | 41 | 2 |
| `R10-individual-records`, no other `present` rule | 32 | 2 | 6 | 24 |
| Other combinations | 88 | 5 | 79 | 4 |

### 6.4 The 27 `present` rows

27 rows in 7 catalogues hold personal data of private individuals.

| Catalogue | Rows | What it holds |
|---|---|---|
| Distress Relief Fund for Fishermen (Karnataka) | 16 | Names of fishermen paid relief for boat damage, and of those who died |
| All India Advocate List: rolls for Chhattisgarh (2), Tamil Nadu (2) and Uttar Pradesh (1) | 5 | Beside the advocate's name and address: father's or husband's name, date of birth, community, phone number |
| Pradhan Mantri Matsya Sampada Yojana Beneficiary Details | 2 | `Name` of each beneficiary |
| Details of schemes under Karnataka Labour Welfare Board: "Funeral Assistance" | 1 | `Benificiary Name` |
| Marriage Assistance to Differently Abled Women ... Kollam District, Kerala | 1 | `Name` |
| Encouragement Fund provided for SC-ST Students | 1 | Students' names in unnamed columns |
| Property Details within Erode District in Tamil Nadu | 1 | `Mobile number` beside property-tax assessment numbers and an `Ownership` column |

### 6.5 The 300 `permissible` rows

300 rows (299 files) in 118 catalogues: 122 of the pipeline's 128 and 178 moved from
`present`. Almost all are directories of officers, offices and businesses.

| Catalogue | Rows |
|---|---|
| Contact Details of TANGEDCO Officials | 44 |
| State-wise List of Notaries Appointed by the Central Government | 24 |
| Circle Offices of Hand-looms and Textiles Department and Weavers Cooperative Societies, Tamil Nadu | 21 |
| All India Advocate List | 16 |
| Division-wise Contact Details - KKRTC | 10 |
| List of Study Centres under Tamil Nadu Open University in 2020 | 9 |
| List of Non-COVID Essential Services, District wise in Tamil Nadu | 8 |
| Contact particulars of Officials ... Animal Husbandry and Veterinary Services | 7 |
| Tamil Nadu District Hand Books (hotels, voluntary services, education, electricity ...) | 35 |
| Karnataka cultural academies: awardees, authors, performers | 20 |

The rest are election candidates and members of legislatures, film award winners, bank
branches, depots, prisons, hospitals and helplines.

Judgment calls, 44 rows:

| Set | Rows | Why it is arguable |
|---|---|---|
| Advocate rolls and notary lists that give name and address (two also a phone number) | 40 | Advocates and notaries are on a public register, but the address may be a home address |
| Grama One centres (2) and Common Service Centres in Tamil Nadu (2) | 4 | The operator's own mobile number; the operator is an individual running a public service point |

### 6.6 What was removed as false

2,060 rows hold no personal data.

**2,022 the pipeline itself judged `false_positive`.** Most frequent headers: `Hobli` 159,
`Description` 90, `Item` 87, `Crop` 70, `Items` 62, `Unnamed: 1` 44, `Address` 43,
`Name of the Crop` 39, `Name of the Local Body` 33, `MINOR HEAD` 32, `Name of the Vehicle` 29,
`Name of the Prison` 28.

**32 the pipeline had called `present`:**

| What was flagged | Rows |
|---|---|
| `Name of the Disease` in district hand books | 14 |
| `GSTO Name`, `DGSTO Name` (GST offices) | 6 |
| `tender/externalReference` in Assam Public Procurement Data (tender numbers read as phones) | 3 |
| `Group Name` in Punjab SC loan tables | 2 |
| `Longitude`, `Share Capital/ Working Capital` read as phone numbers | 2 |
| `AC Name`, `Pc Name` (constituency names) | 2 |
| Book titles in `Particluars`; a workers' union as `Name of the Beneficiary` | 2 |
| District names in a legacy Kannada font, in "Karnataka Darshan 2019-20" (the text reaches the scan as Latin gibberish) | 1 |

**6 the pipeline had called `permissible`:** political party names (4), department names (1)
and an abbreviation (1).

### 6.7 What lot 3's result means

- Lot 3 is state-level data with many rosters and contact lists. That is why it has 300
  `permissible` rows out of 28,832 scanned, against 330 out of 111,638 in lot 2.
- 27 rows hold personal data of private individuals: 22 are lists of scheme beneficiaries and
  property owners, 5 are advocate rolls with family and birth details.
- The pipeline's `present` was right for 27 of 237 rows. Most of the rest are office and
  officer contact lists that `R11` treated as private because they hold mobile numbers.
- The 40 advocate and notary registers are the largest open question in this lot.

---

## 7. KCC transcripts

The Kisan Call Centre transcripts are not one of the three lots. They are 2,753 quarterly
files in 37 state folders, 2006 to 2026. 863 of the files are empty; the other 1,890 hold
about 23.2 million lines (4.4 GB). Each row is one call: the farmer's question (`QueryText`)
and the agent's answer (`KccAns`), with state, district, crop and date.

### 7.1 What has been run

| Run | Date | What it read | Status |
|---|---|---|---|
| Scan and classification | 21-22 Sep 2026 | The first 250 rows of each file: 318,459 rows, about 1.4% of the corpus | Done; results below |
| Public-contact correction | 22 Sep 2026 | The phone numbers in the columns judged `present` | Done; results below |
| Full-text search for farmer records | 9 Oct 2026 | Every line of every file (plain text patterns, not the scan) | Done; section 7.4 |
| Scan of every row | 9 Oct 2026 | All rows of all 1,890 files: 12.4 million rows | Scan done, no file failed. Not classified yet, so it gives no per-file verdict |

1,175 of the 1,890 files are longer than 250 rows, so the September result describes the top
of each file only.

The scan of every row stored 1,102,047 detections and set the scan flag on 1,149 of the 1,890
files, against 37,936 detections in the first 250 rows. These are raw detections. Going by
lots 2 and 3 and by the September KCC run, most will be helpline and office numbers or false,
so they are not counted as findings in this report.

### 7.2 The September result (first 250 rows)

37,936 detections in 1,525 files, across 2,328 flagged columns: `KccAns` 1,353, `QueryText`
908, `Crop` 67.

| Detected as | Detections |
|---|---|
| Phone number | 27,081 |
| Person name | 8,665 |
| Farmer registration ID | 1,193 |
| Email address | 675 |
| Aadhaar number | 322 |

Verdict per file:

| Verdict | As classified | After the public-contact correction |
|---|---|---|
| `present` | 819 | 376 |
| `permissible` | 252 | 695 |
| `false_positive` | 454 | 454 |
| No detections | 365 | 365 |
| Empty file | 863 | 863 |

- 809 of the 833 `present` columns came from `R11-personal-channel`: a mobile number in an
  answer was treated as a private person's.
- KCC answers quote officers', research stations' and helpline numbers for the farmer to
  call. The correction moved 454 columns to `permissible` where every phone number was a
  landline, a number recurring across files, or introduced by an officer cue. It is a stopgap
  kept in `public_contact_override.csv`; a proper rule has not been written.

### 7.3 What the 376 `present` files hold

21,737 detections, all but 17 of them in `KccAns`:

| Detected as | Detections | Distinct values | Files |
|---|---|---|---|
| Phone number | 17,822 | 3,571 | 370 |
| Person name | 2,064 | 1,743 | 271 |
| Farmer registration ID | 1,078 | 1,000 | 137 |
| Email address | 491 | 344 | 107 |
| Aadhaar number | 282 | 208 | 54 |

Reading a sample of the text around these detections, with digits masked:

- **Farmer records pasted into answers.** From 2019 the agents paste a farmer's PM-KISAN
  status into the answer: farmer's name, father's name, registration number, village address,
  bank branch code, payment references and dates. This is the personal data in KCC. The
  portal masks most of the mobile and Aadhaar digits in what is pasted.
- **Some full Aadhaar numbers.** A few answers quote the 12-digit number the farmer gave
  ("the aadhaar number provided by the farmer ...").
- **Helplines and officers.** 261 phone numbers account for 11,592 of the 17,822 phone
  detections. They are helplines and offices (weather helpline, research institutes, crop
  insurance) mixed into the same column as the farmer records, which is why the correction
  did not clear these files.
- **False Aadhaar hits.** Most of the 282 Aadhaar detections are digits in market-price
  tables that pass the checksum by chance; 41 of the 282 sit beside an Aadhaar or PM-KISAN
  label.

### 7.4 How many files really hold farmer records

A plain text search of every line, for the labels and number shapes of a pasted farmer record:

| Pattern | Lines | Files |
|---|---|---|
| "Farmer Name", "Name Of Farmer", "Father Name", "Farmer Application Status", "Beneficiary Status" | 86,592 | 395 |
| A registration number (two letters and nine digits) | 22,394 | 286 |
| A 12-digit number directly after an Aadhaar label | 53 | 23 |
| Either of the first two | - | 408 |

The 408 files are in 31 states and almost all from 2019 to 2024 (23, 68, 66, 70, 82 and 93
files by year).

Against the September verdicts:

| September verdict (after correction) | Files | With farmer records somewhere in the file | Without |
|---|---|---|---|
| `present` | 376 | 216 | 160 |
| `permissible` | 695 | 154 | 541 |
| `false_positive` | 454 | 33 | 421 |
| No detections | 365 | 5 | 360 |

- **216 of the 376 `present` files hold farmer records.** The other 160 are `present` on
  phone numbers alone; they are mostly from before 2019 and are likely officer and dealer
  numbers the correction could not confirm as public.
- **192 files hold farmer records and are not `present`.** In most of them the records start
  after row 250, which the September scan never read. 118 of the 154 `permissible` ones were
  `present` before the correction.
- The text search only finds records with English labels or a registration number. Answers
  written in Hindi, Gujarati, Malayalam and other languages carry the same records under
  translated labels, so 408 is a lower bound.

### 7.5 What KCC's result means

- KCC holds personal data of farmers: at least 408 files and tens of thousands of calls from
  2019 onwards, in the `KccAns` column.
- With the false detections removed, 216 of the 376 files the September run called `present`
  are confirmed: they hold farmer records. The other 160 were flagged on phone numbers alone
  and are not confirmed as personal data, so they are not counted.
- 192 more files hold farmer records that the September run did not reach, because it read
  the first 250 rows only.
- The scan of every row is done. Classifying it will give the per-file result and the list of
  flagged rows, which is what redaction needs.

---

## 8. Patterns across the lots

**The same false detection in every lot.** A column of labels or place names is read as
person names:

| Lot | Columns | Files removed as false |
|---|---|---|
| 1 | HMIS indicators | 3,909 |
| 2 | Census village and town names, crime heads, routes and stations, project names | 5,518 |
| 3 | `Hobli`, crops, items, local bodies, diseases | 2,060 |

The rules remove them where they know the header. Where the headers are new, the LLM judge
does the removing: 2,812 columns in lot 2 and 1,048 in lot 3.

**Numbers read as phone or Aadhaar numbers.** Lot 2: GDP, balance-of-payments and import
tables, telephone-subscriber statistics, spring elevations, coordinates, evapotranspiration
volumes. Lot 3: tender references, longitude, share capital. No Aadhaar detection in lots 2
and 3 is a real Aadhaar number.

**Two rules produced most of the wrong `present` verdicts.**

| Rule | What it does | How it held up |
|---|---|---|
| `R11-personal-channel` | Treats a mobile-shaped number or a personal-looking email as a private person's | Lot 2: right for 2 of 61 files. Lot 3: right for 1 of 44 rows. The rest are office, depot, hotel and helpline numbers, or not phone numbers at all. |
| `R10-individual-records` | Convicts a name or contact column when the title suggests individual records | Lot 2: right for 16 of 81 files; 58 are college, company and map names. Lot 3: right for 2 of 32 rows; 24 are disease, office and group names. |

`R10` is also the rule that caught the 13 Minor Irrigation Census files, so it cannot simply
be switched off. The LLM judge's `present` verdicts were right for 9 of 57 files in lot 2 and
19 of 73 rows in lot 3; most of its errors are public-role names, not false detections.

**Where the personal data is.**

| Lot | Files | What |
|---|---|---|
| 2 | 13 | Minor Irrigation Census: scheme owners' names, field staff's names and mobile numbers |
| 2 | 13 | Rajya Sabha answer tables: accused, encroachers, the dead and their next of kin, couples, beneficiaries, sportspersons given welfare or medical assistance |
| 2 | 6 | Smart Cities Mission: two COVID patient files, missing children, traffic-accident victims, merchant registrations with PAN numbers, property owners on building permissions |
| 3 | 22 | State scheme beneficiaries (16 are fishermen's relief payments), SC-ST student awardees, property owners' mobile numbers |
| 3 | 5 | Advocate rolls with father's or husband's name, date of birth or community |

In lot 2 it is in open-ended lists from city bodies and in answer tables laid before
Parliament. In lot 3 it is in state departments' beneficiary lists. None of it is in the
large statistical series that make up most of each lot.

---

## 9. Limits and recommended next steps

Limits of this analysis:

- **The review removed false detections; it did not look for misses.** The 11,322 files the
  pipeline judged `false_positive` and the 335,235 with no detections were not read again.
- **Misses exist.** Two were found by chance, in files that are base64-encoded JSON saved as
  `.csv`. Only the files on this server were checked for that encoding (76,700 of lot 2 and
  8,073 of lot 3); the 34,983 lot 2 files and 20,781 lot 3 files that are only on S3 were not.
- **Names go undetected inside long cells.** The missing-children and traffic-accident files
  put name, address, phone and caste in one cell; the scan found the phone number and not the
  name. A file like that with no phone number produces no detection at all.
- **The review is one reviewer's judgment** (an AI assistant's, with no second reviewer),
  per dataset and column, not per value, and nothing
  has been scored against hand labels (`labels.csv` holds 201 rows with the answer column
  empty).
- Lot 1's 83,359 May-result rows are unknown, and 6,039 lot 2 rows have no file to check.
- The scan reads the first 250 rows and only text-like columns, and looks for names, phones,
  emails and ID numbers. It does not assess unit-level survey records that carry no names.
- The KCC figures in sections 7.2 and 7.3 rest on the first 250 rows of each file. Files sent
  through the PII API are not covered.

Recommended, in order:

1. **Act on the 59 `present` datasets.** Start with the four Smart Cities files about
   patients, children and accident victims ([section 5.4](#54-the-32-present-files)). Each
   needs a decision to withdraw, redact or keep.
2. **Decide the judgment calls as sets.** The 16 member directories that give relatives'
   names and home addresses (and fix the nine uploaded under an unrelated title), the 40
   advocate and notary registers, and the 15 smaller lists. Each set is marked in
   `final_results.csv` and in the workbooks, so moving one is a single change.
3. **Look for misses where the finds were.** Read the Smart Cities Mission files that have a
   free-text `Name and Address` or similar column, and check the S3-only files for encoded
   content. This is a few hundred files, not the whole lot.
4. **Fix the two over-calling rules.** `R11` needs to tell an office or business number from
   a private one; `R10` needs more than a title match plus a header called `name`. The
   number-as-phone false detections need the fix chosen for the tender IDs. Lots 2 and 3 can
   then be re-classified without re-scanning, but classification reads each flagged file's
   header row, so the files must be on this server first, and `data/lot2_downloads/` must not
   be deleted before it is uploaded.
5. **Keep the review as a labelled set.** The 852 reviewed verdicts are now labels for the
   `present` and `permissible` classes. Adding about 200 `false_positive` and no-detection
   files, read the same way, would give accuracy figures for the whole pipeline.
6. **Classify the KCC full scan** ([section 7](#7-kcc-transcripts)), which is what gives the
   per-file result and the rows to redact.
7. **Decide what happens to the downloaded lot 2 files.** The 76,527 files fetched on
   2026-10-08 (15 GB) are in `data/lot2_downloads/` on this server only. Uploading them to the
   lot 2 folders on S3 would make lot 2's files complete there.
8. **Lot 1 is closed (decided 2026-10-08).** The lot is taken as holding no PII and the
   83,359 May-result files will not be re-scanned. If that changes, note that running the
   scan as things stand would do the wrong thing twice over:
   - The local table's `pii_tested` reads `'0'` on every row, so the scan would redo all
     206,972 files, not 83,359.
   - After each batch the scan re-uploads the local table to
     `pii-results/dublin_core_metadata_snapshot.parquet`. That file is the only per-row record
     of the September flags, and a run from the current local state would overwrite it.

   The safe order is: copy the snapshot aside, restore the September flags from it into the
   local table for the 123,578 re-scanned rows, then run. That is about 10 hours with three
   workers at the September rate, or roughly 30 hours with the single worker that fits beside
   the judge and the API.

---

## 10. Sources

| Number | Where it comes from |
|---|---|
| Lot 1 tested / flagged / timestamps | `s3://nic-ogdp-datasets/pii-results/dublin_core_metadata_snapshot.parquet` (uploaded 2026-09-02 09:40) |
| Lot 1 batch-by-batch re-scan counts, May-pass warnings, scannable-column share | `pii_test/pii_s3.log` |
| Lot 1 detections | `pii_detections_lot1` in `transformation/metadata.db` |
| Lot 1 verdicts | `pii_column_class`, `pii_dataset_class` in `transformation/metadata.db` (classified 2026-09-02 to 2026-09-10) |
| Lot 2 per-row results | `pii_test/lot2/lot2_pii_result.csv` (one row per table row, with the status or the reason there is none) |
| Lot 2 per-column verdicts, rules, headers | `pii_test/lot2/classification/column_class.csv`, `tier1_column_class.csv`, `tier3_verdicts.csv` |
| Lot 2 scan flags, staged files | `pii_test/lot2/classification/file_summary.csv`, `pii_test/lot2/stage_manifest.csv` |
| Lot 2 downloads | `data/lot2_download_log.csv` (2026-10-08), `data/lot2_retry_download_log.csv` (retry of the undownloadable list) |
| Lot 2 August scan (section 5.7) | `remain_raw_metadata`, `pii_detections_lot2`, `pii_column_class` in `transformation/metadata.db` |
| Lot 2 files on S3 | listing of `s3://nic-ogdp-datasets/downloaded-datasets/` taken 2026-10-07 (34,983 lot 2 files) |
| How lot 2 was run | `pii_test/run_lot2_pii.py`, `scripts/lot2_download_missing.sh` |
| Final result per dataset, what it holds, judgment calls | `pii_test/final_review/final_results.csv` and `kept_columns.csv`, written by `pii_test/build_final_review.py` (review of 2026-10-12) |
| First reading of the `present` files, the starting point of the review | `pii_test/lot2/lot2_present_groups.csv`, `pii_test/lot3/lot3_present_groups.csv` |
| Workbooks with every dataset and detection | `pii_test/results_excel/`, written by `pii_test/export_results_excel.py` |
| Lot 3 per-row results | `pii_test/lot3/lot3_pii_result.csv` |
| Lot 3 per-column verdicts, rules, headers | `pii_test/lot3/classification/column_class.csv`, `tier1_column_class.csv`, `tier3_verdicts.csv` |
| Lot 3 scan flags and reasons | `pii_test/lot3/classification/file_summary.csv` |
| KCC September scan and verdicts | `pii_test/kcc/kcc_scan_summary.csv`, `pii_test/kcc/kcc-transcripts/<STATE>/pii_detections.csv`, `pii_test/kcc/classification/` (`*.before_override.csv` are the verdicts before the correction; `public_contact_override.csv` is its audit) |
| KCC full-text search (section 7.4) | `grep` over `pii_test/kcc/kcc-transcripts/` on 2026-10-09 |
| KCC scan of every row | `pii_test/run_kcc_full_scan.py`; totals from `pii_test/kcc/full/kcc_full_scan_summary.csv`; detections in `data/kcc_full_stage/<STATE>__<YEAR>/pii_detections.csv` |
| Titles, catalogues, publishers | `dublin_core_metadata`, `dublin_core_remaining`, `dublin_core_lot3` |

Small discrepancies to know about:

- `dublin_core_lot3` holds one UUID twice ("Karnataka Agricultural Market Data for 2012"), so
  the 300 `permissible` rows are 299 files and the workbooks list 637 `permissible` datasets
  where this report counts 638.
- One UUID is in both lot 2 and lot 3 ("Annual Report 2012-13"). It had no detections in
  either.
- Lot 1 has 3 rows dated 3 Aug 2026 among the "May result" rows.
- Lot 3 file counts differ slightly between the per-column file (2,386 files with detections)
  and the per-row file (2,387 rows) because of the duplicated UUID.

## 11. Rule glossary

| Rule | Verdict | What it tests |
|---|---|---|
| `R1-skip-header` | `false_positive` | The header cannot hold personal data |
| `R1-controlled-vocab` | `false_positive` | The header marks a closed category list and only names were detected |
| `R2-column-shape` | `false_positive` | The values are not name-shaped, or the column has few distinct values |
| `R3-not-a-number` | `false_positive` | The "phone numbers" fit no numbering plan |
| `R4-institutional-channel` | `permissible` | Every contact value is toll-free, a landline or an institutional domain |
| `R5-private-absolute` | `present` | The header says beneficiary, patient, victim or accused |
| `R6-office-allowlist` | `permissible` | At least 30% of distinct values are known public office holders |
| `R7-directory-context` | `permissible` | The dataset is a directory of office bearers |
| `R8-office-header` | `permissible` | The header names a public office |
| `R9-private-contextual` | `present` | The header names a relative or a private role, outside a directory |
| `R10-individual-records` | `present` | The dataset holds individual records |
| `R11-personal-channel` | `present` | A subscriber mobile number or a personal email address |
| `R12-residual` | undecided | No rule applies; goes to the LLM judge |
| `T3-judge` | any | Local LLM judge (Qwen3-8B) |
| `T4-reviewer` | any | Set by a human reviewer |
