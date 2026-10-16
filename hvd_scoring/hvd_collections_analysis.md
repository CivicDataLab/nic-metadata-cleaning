# HVD scoring with collections as merged datasets

Run date: 9 October 2026, against `transformation/metadata.db`. This follows `hvd_pooled_run_analysis.md`, which scored every file separately.

## 1. What was run

A collection will become one merged dataset, so each collection is scored here as a single unit. A file that is not in a collection stays a unit of its own. The scoring is `hvd_score_v2.py`'s: same five signals, same weights, same rules.

| Step | Command | Output |
|---|---|---|
| Per file, for comparison | `python3 hvd_scoring/hvd_score_v2.py --table all --cut-value 10 --extra-cuts 5 1 --out hvd_scoring/hvd_scores_v2.csv` | `hvd_scoring/hvd_scores_v2.csv` (354,291 rows) |
| Per merged dataset | `python3 hvd_scoring/hvd_score_collections.py` | `hvd_scoring/hvd_scores_collections.csv` (74,070 rows) |
| API-fed only, per file | `python3 hvd_scoring/hvd_score_v2.py --table all --api-only --cut-value 10 --extra-cuts 5 1 --out hvd_scoring/hvd_scores_v2_api_only.csv` | `hvd_scoring/hvd_scores_v2_api_only.csv` (6,277 rows) |
| API-fed only, per merged dataset | `python3 hvd_scoring/hvd_score_collections.py --api-only --abs-cuts 0.42 --out hvd_scoring/hvd_scores_collections_api_only.csv` | `hvd_scoring/hvd_scores_collections_api_only.csv` (591 rows) |

`hvd_score_collections.py` is new. It imports `hvd_score_v2.py` for loading and scoring, and adds one step in between: rolling each collection's files up into one row. `hvd_score_v2.py` itself is unchanged. Sections 2 to 11 are the run over all datasets; section 12 is the run over API-fed datasets only.

How a collection's inputs are built from its files:

| Signal | Rule for a collection |
|---|---|
| demand | Sum of the files' downloads per month and views per month |
| temporal | Earliest start year to latest end year across the files |
| geo | The widest file: the collection's share of the 36 States/UTs, or higher where a file is national or State/UT-wise. The collection's own name is also checked for "State/UT-wise" |
| api | 1 if any file is API-fed |
| liveness | The most recently refreshed file |

The 1,017 files marked `to be removed` are left out, because they will not exist after the merge. Counts are the tables' own columns; the live portal counts (`--stats`) were not fetched.

## 2. Summary

- **354,291 files become 74,070 future datasets.** 7,781 collections hold 286,985 files; 66,289 files stand alone.
- **The largest series are now detected.** All 19 collections with 1,000 or more files pass the top 10%, and 13 pass the top 1%. The top 10% of datasets now holds 120,191 files (34% of all files), against 34,991 files when scored one by one.
- **Rajya Sabha is no longer over-represented, but it is still half the list.** It passes the top 10% at 11.4%, close to the 10% average, down from 43.5% per file. It is 44.6% of all future datasets, so it is 50.9% of the top 10%.
- **Most collections still fail, because most cover one state.** 6,393 of the 7,781 collections cover a single state, and 0.7% of those pass. Collections that cover 28 or more states pass at 33%.
- **Lot 1 is mostly one report split by district.** 5,446 of its 5,664 collections are HMIS sub-district reports, one collection per district. None of them pass.
- **The result depends on summing traffic.** If a collection's demand is the average of its files instead of the sum, the collections passing the top 10% fall from 558 to 254.
- **A dataset with no date range still does better than one covering 1 to 4 years.**
- **Scored on their own (`--api-only`), the API-fed datasets are ranked by what is missing.** 6,203 API-fed files become 591 datasets. The top 10% is 60 datasets; all 18 that have only the API flag and a refresh date are in it. The fixed threshold of 0.42 passes 563 of the 591 (section 12).

## 3. From files to datasets

| | Files | Collections | Files in collections | Files on their own | Future datasets |
|---|---|---|---|---|---|
| Lot 1 | 206,929 | 5,664 | 205,151 | 1,778 | 7,442 |
| Lot 2 | 116,892 | 1,220 | 58,912 | 57,980 | 59,200 |
| Lot 3 | 29,453 | 897 | 22,922 | 6,531 | 7,428 |
| **Total** | **353,274** | **7,781** | **286,985** | **66,289** | **74,070** |

Of lot 2's 57,980 standalone files, 33,057 are Rajya Sabha. No Rajya Sabha file is in a collection.

Cuts over the 74,070 datasets, with the per-file cuts for comparison:

| Cut | Per file: threshold | Per file: candidates | Per dataset: threshold | Per dataset: candidates | Of which collections | Files they hold |
|---|---|---|---|---|---|---|
| p90 (top 10%) | 0.2580 | 35,430 | 0.2931 | 7,407 | 558 | 120,191 |
| p95 (top 5%) | 0.3318 | 17,721 | 0.3363 | 3,704 | 288 | 102,627 |
| p99 (top 1%) | 0.4244 | 3,543 | 0.4507 | 741 | 69 | 63,398 |

## 4. Who passes each cut

"Share" is the group's share of all candidates at that cut. "Rate" is the share of the group's own datasets that pass.

| Group | Datasets | % of datasets | Files | p90 passed | p90 share | p90 rate | p95 passed | p95 share | p95 rate | p99 passed | p99 share | p99 rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lot 1 collections | 5,664 | 7.6% | 205,151 | 50 | 0.7% | 0.9% | 42 | 1.1% | 0.7% | 11 | 1.5% | 0.2% |
| Lot 1 single files | 1,778 | 2.4% | 1,778 | 215 | 2.9% | 12.1% | 97 | 2.6% | 5.5% | 12 | 1.6% | 0.7% |
| Lot 2 collections | 1,220 | 1.6% | 58,912 | 465 | 6.3% | 38.1% | 226 | 6.1% | 18.5% | 55 | 7.4% | 4.5% |
| Rajya Sabha (single files) | 33,057 | 44.6% | 33,057 | 3,769 | 50.9% | 11.4% | 1,527 | 41.2% | 4.6% | 68 | 9.2% | 0.2% |
| Lot 2 other single files | 24,923 | 33.6% | 24,923 | 2,331 | 31.5% | 9.4% | 1,319 | 35.6% | 5.3% | 510 | 68.8% | 2.0% |
| Lot 3 collections | 897 | 1.2% | 22,922 | 43 | 0.6% | 4.8% | 20 | 0.5% | 2.2% | 3 | 0.4% | 0.3% |
| Lot 3 single files | 6,531 | 8.8% | 6,531 | 534 | 7.2% | 8.2% | 473 | 12.8% | 7.2% | 82 | 11.1% | 1.3% |
| **Total** | 74,070 | 100% | 353,274 | 7,407 | | | 3,704 | | | 741 | | |

Files held by the collections that pass:

| Group | Files held at p90 | at p95 | at p99 |
|---|---|---|---|
| Lot 1 collections | 63,391 | 62,589 | 51,030 |
| Lot 2 collections | 43,509 | 30,483 | 6,479 |
| Lot 3 collections | 6,442 | 6,139 | 5,217 |

Collections as a whole pass slightly less often than single files: 7.2% against 10.3% at p90, 3.7% against 5.2% at p95, and 0.9% against 1.0% at p99. Section 6 shows why.

## 5. Per file against per dataset, by publisher

All 15 publishers with at least 400 files. "Files inside passing datasets" is the share of the publisher's files that sit in a dataset passing p90.

| Publisher | Files | Datasets | Collections | Files in collections | Per file: pass p90 | Per dataset: pass p90 | Files inside passing datasets | Datasets passing p90 / p95 / p99 |
|---|---|---|---|---|---|---|---|---|
| School Education and Literacy | 14,635 | 446 | 13 | 97% | 2.5% | 38.6% | 98.1% | 172 / 64 / 5 |
| Road Transport and Highways | 2,642 | 2,094 | 47 | 23% | 39.3% | 23.4% | 36.6% | 491 / 203 / 18 |
| Statistics and Programme Implementation | 2,630 | 2,424 | 12 | 8% | 58.8% | 23.4% | 29.4% | 568 / 284 / 41 |
| Petroleum and Natural Gas | 484 | 480 | 1 | 1% | 76.7% | 17.3% | 18.0% | 83 / 36 / 1 |
| Animal Husbandry and Dairying | 1,741 | 473 | 43 | 75% | 12.4% | 13.5% | 43.0% | 64 / 27 / 1 |
| Power, Central Electricity Authority | 600 | 227 | 28 | 67% | 10.1% | 11.5% | 58.7% | 26 / 22 / 5 |
| **Rajya Sabha** | 33,057 | 33,057 | 0 | 0% | 43.5% | 11.4% | 11.4% | 3,769 / 1,527 / 68 |
| Registrar General and Census Commissioner | 36,072 | 1,165 | 447 | 98% | 2.7% | 9.4% | 65.5% | 109 / 45 / 5 |
| Publisher blank (all lot 3) | 29,025 | 7,067 | 889 | 79% | 26.2% | 7.5% | 23.9% | 529 / 447 / 49 |
| National Crime Records Bureau | 10,325 | 7,190 | 516 | 35% | 14.0% | 7.3% | 19.1% | 523 / 225 / 14 |
| Jal Shakti | 2,248 | 1,366 | 14 | 40% | 7.6% | 4.0% | 38.5% | 54 / 48 / 29 |
| Health and Family Welfare (HMIS, lot 1) | 206,925 | 7,438 | 5,664 | 99% | 2.1% | 3.5% | 30.7% | 263 / 138 / 23 |
| Central Pollution Control Board | 917 | 214 | 4 | 77% | 7.0% | 2.8% | 76.3% | 6 / 5 / 3 |
| Civil Aviation | 831 | 555 | 24 | 36% | 45.9% | 2.3% | 4.5% | 13 / 5 / 1 |
| NITI Aayog | 1,598 | 1,246 | 14 | 23% | 9.6% | 1.2% | 3.3% | 15 / 9 / 0 |

- **Publishers of large series gain.** School Education goes from 2.5% of files to 98.1% of files inside a passing dataset; Census from 2.7% to 65.5%; HMIS from 2.1% to 30.7%.
- **Publishers of standalone summary tables lose their lead.** Rajya Sabha, Statistics, Petroleum and Civil Aviation all pass far less often per dataset than per file.

How the per-file list and the per-dataset list overlap, counted in files:

| Cut | Files that are per-file candidates | Files inside a passing dataset | In both | Per-file only | Per-dataset only |
|---|---|---|---|---|---|
| p90 | 34,991 | 120,191 | 18,990 | 16,001 | 101,201 |
| p95 | 17,524 | 102,627 | 10,129 | 7,395 | 92,498 |
| p99 | 3,447 | 63,398 | 1,167 | 2,280 | 62,231 |

At p90, 10,611 of the 16,001 files dropped from the list are Rajya Sabha tables. The 101,201 files added are 59,681 in lot 1 collections, 41,311 in lot 2 collections and 209 in lot 3 collections.

## 6. What a merged collection looks like

| | Lot 1 collections | Lot 2 collections | Lot 3 collections |
|---|---|---|---|
| Collections | 5,664 | 1,220 | 897 |
| Files per collection, median | 24 | 11 | 8 |
| **States/UTs covered** | | | |
| None named (national files) | 32 | 657 | 8 |
| Exactly 1 | 5,492 | 14 | 887 |
| 2 to 9 | 115 | 28 | 1 |
| 10 to 27 | 6 | 49 | 1 |
| 28 or more | 19 | 472 | 0 |
| **Years spanned** | | | |
| No usable date range | 0 | 83 | 8 |
| 1 | 662 | 61 | 75 |
| 2 | 1,837 | 461 | 211 |
| 3 to 4 | 2,018 | 33 | 148 |
| 5 to 9 | 1,058 | 361 | 192 |
| 10 or more | 89 | 221 | 263 |
| Views per month (summed), median | 0.23 | 2.77 | no counts |
| Days since last refresh, median | 2,494 | 1,764 | 1,891 |
| **Mean signal: demand** | 0.09 | 0.36 | none |
| **temporal** | 0.22 | 0.34 | 0.38 |
| **geo** | 0.03 | 0.76 | 0.03 |
| **liveness** | 0.01 | 0.08 | 0.05 |
| **Mean score** | 0.080 | 0.286 | 0.133 |

For comparison, the mean score is 0.199 for Rajya Sabha and 0.157 for the other lot 2 single files.

**Lot 1.** The 5,664 collections are two different things:

| Lot 1 collections | Collections | Files | Pass p90 |
|---|---|---|---|
| "HMIS Item-wise Monthly Report for Sub-districts of ⟨district⟩" | 2,902 | 65,657 | 0 |
| "HMIS Item-wise Cumulative Report for Sub-districts of ⟨district⟩" | 2,544 | 65,334 | 0 |
| All other lot 1 collections | 218 | 74,160 | 50 |

The sub-district reports are one collection per district (733 districts appear in the names) and financial-year range. Each covers one state, a few years and almost no traffic, so merging the files does not lift them. The 50 that pass are the national series.

**Lot 2.** Most collections are national or span 28 or more states, and they carry real traffic. This is the strongest group: 38.1% pass p90.

**Lot 3.** 887 of 897 collections are one state's data, and the lot has no view or download counts. Only 43 pass.

What decides whether a collection passes p90:

| States/UTs covered | Collections | Files | Mean geo | Pass p90 | Rate |
|---|---|---|---|---|---|
| None named (national files) | 697 | 7,366 | 0.69 | 310 | 44.5% |
| Exactly 1 | 6,393 | 161,895 | 0.03 | 46 | 0.7% |
| 2 to 9 | 144 | 3,103 | 0.08 | 21 | 14.6% |
| 10 to 27 | 56 | 6,208 | 0.73 | 19 | 33.9% |
| 28 or more | 491 | 108,413 | 0.90 | 162 | 33.0% |

| Files in the collection | Collections | Files | Pass p90 | Rate | Pass p99 |
|---|---|---|---|---|---|
| 1 | 504 | 504 | 0 | 0.0% | 0 |
| 2 to 9 | 1,499 | 8,739 | 250 | 16.7% | 27 |
| 10 to 99 | 5,606 | 158,221 | 217 | 3.9% | 22 |
| 100 to 999 | 153 | 44,797 | 72 | 47.1% | 7 |
| 1,000 or more | 19 | 74,724 | 19 | 100% | 13 |

Lot 2 collections by publisher:

| Publisher | Collections | Files | Pass p90 | Rate | Pass p99 |
|---|---|---|---|---|---|
| National Crime Records Bureau | 516 | 3,651 | 203 | 39% | 3 |
| Registrar General and Census Commissioner | 447 | 35,354 | 107 | 24% | 5 |
| Road Transport and Highways | 47 | 595 | 37 | 79% | 7 |
| Animal Husbandry and Dairying | 43 | 1,311 | 24 | 56% | 0 |
| Power, Central Electricity Authority | 28 | 401 | 20 | 71% | 4 |
| Civil Aviation | 24 | 300 | 1 | 4% | 0 |
| Development of North Eastern Region | 21 | 257 | 21 | 100% | 21 |
| NITI Aayog | 14 | 366 | 2 | 14% | 0 |
| Jal Shakti | 14 | 896 | 4 | 29% | 2 |
| School Education and Literacy | 13 | 14,202 | 13 | 100% | 2 |
| Statistics and Programme Implementation | 12 | 218 | 12 | 100% | 3 |

Census has 403 collections covering 28 or more states, but their median span is 2 years and they were last refreshed long ago, so only 107 of 447 pass.

## 7. Rajya Sabha and the API-fed datasets

**Rajya Sabha.** Its files are unchanged by the roll-up, since none is in a collection. What changed is the pool around them.

| | Per file | Per dataset |
|---|---|---|
| Share of the pool | 9.4% | 44.6% |
| Pass rate at p90 | 43.5% | 11.4% |
| Share of p90 candidates | 40.8% | 50.9% |
| Share of p95 candidates | 35.3% | 41.2% |
| Share of p99 candidates | 39.2% | 9.2% |
| Mean signal: demand / temporal / geo / liveness | 0.27 / 0.41 / 0.72 / 0.11 | 0.17 / 0.25 / 0.72 / 0.11 |

Its demand and temporal values fell because the scales it is measured against moved up (section 8). 1,732 of its 3,769 p90 candidates have no date range.

**API-fed datasets.** 591 datasets are API-fed, holding 6,383 files: 558 single files and 33 collections. Their scores run from 0.379 to 0.974, so all 591 pass p95. 564 pass p99, where they are 76% of the list.

| Top N datasets | API-fed | Rajya Sabha | Collections (not API) | Other single files (not API) | Lowest score |
|---|---|---|---|---|---|
| 100 | 100 | 0 | 0 | 0 | 0.6609 |
| 500 | 471 | 10 | 7 | 12 | 0.5148 |
| 741 (p99) | 564 | 65 | 37 | 75 | 0.4511 |
| 1,000 | 579 | 133 | 69 | 219 | 0.4264 |
| 2,000 | 591 | 568 | 123 | 718 | 0.3753 |
| 3,704 (p95) | 591 | 1,517 | 255 | 1,341 | 0.3363 |
| 7,407 (p90) | 591 | 3,759 | 525 | 2,532 | 0.2931 |

The 4,759 API-fed crop survey files that crowded the per-file p95 list are now one dataset. 18 of the top 100 datasets are scored on two signals only (API flag and liveness). Section 12 scores the 591 API-fed datasets on their own, as `--api-only` does.

## 8. The scales moved

Each signal is normalised against the pool, so changing the pool changes the scale.

| Scale ceiling (99th percentile) | Per file | Per dataset |
|---|---|---|
| Views per month for full marks | 8.3 | 26.8 |
| Downloads per month for full marks | 1.5 | 5.8 |
| Years spanned for full marks | 11 | 37 |

| Years spanned | Temporal value per file | Temporal value per dataset |
|---|---|---|
| 1 | 0.00 | 0.00 |
| 2 | 0.23 | 0.14 |
| 3 | 0.39 | 0.24 |
| 5 | 0.61 | 0.37 |
| 10 | 0.95 | 0.58 |
| 11 | 1.00 | 0.61 |

- The traffic ceilings rise because large collections add up their files' traffic.
- The temporal ceiling rises to 37 years because 546 datasets span 37 years or more. Most are single files (292 in lot 3, 155 in lot 2) rather than collections.
- A ten-year table that scored 0.95 on temporal per file now scores 0.58.

## 9. A missing date range still wins

| Years spanned | Single files | Pass p90 | Collections | Pass p90 |
|---|---|---|---|---|
| No usable date range | 21,633 | 12.9% | 91 | 40.7% |
| 1 | 14,411 | 1.5% | 798 | 1.6% |
| 2 to 4 | 19,679 | 3.8% | 4,708 | 3.0% |
| 5 to 9 | 7,434 | 19.3% | 1,611 | 10.6% |
| 10 to 19 | 2,290 | 36.1% | 487 | 27.9% |
| 20 or more | 842 | 98.0% | 86 | 72.1% |

A file with no date range passes more than three times as often as one known to cover 2 to 4 years. Collections almost always have a date range, so this works against them: only 91 of 7,781 have none, against 21,633 of 66,289 single files.

## 10. What the result is sensitive to

Each row re-scores the 74,070 datasets with one change and recomputes the cut. Figures are datasets passing p90.

| Change | Lot 1 collections | Lot 2 collections | Lot 3 collections | All collections | Rajya Sabha | Rajya Sabha share | Files held |
|---|---|---|---|---|---|---|---|
| **Baseline** | **50** | **465** | **43** | **558** | **3,769** | **50.9%** | **120,191** |
| Demand: average of the files, not the sum | 11 | 200 | 43 | 254 | 3,987 | 53.8% | 47,624 |
| Demand: busiest file, not the sum | 30 | 264 | 43 | 337 | 3,931 | 53.1% | 90,870 |
| Temporal: distinct years covered, not first-to-last | 50 | 454 | 39 | 543 | 3,782 | 51.1% | 120,016 |
| Temporal: ceiling held at 11 years | 54 | 544 | 25 | 623 | 3,386 | 45.7% | 115,447 |
| Score a missing date range as 0 | 53 | 631 | 58 | 742 | 3,608 | 48.7% | 124,296 |
| Score every missing signal as 0 | 53 | 670 | 24 | 747 | 3,887 | 52.5% | 124,805 |
| Geo: collection's share of states only (no "India" or title rule) | 153 | 753 | 145 | 1,051 | 2,949 | 39.8% | 138,846 |
| Drop geo | 297 | 421 | 301 | 1,019 | 2,966 | 40.0% | 136,837 |
| Drop demand | 39 | 363 | 40 | 442 | 4,053 | 54.7% | 84,566 |
| Drop temporal | 38 | 482 | 4 | 524 | 4,401 | 59.4% | 123,677 |
| Drop api | 48 | 337 | 50 | 435 | 4,174 | 56.4% | 109,865 |
| Drop liveness | 52 | 556 | 57 | 665 | 3,707 | 50.0% | 123,143 |

- **Summing traffic is the assumption that matters most.** Averaging instead halves the collections that pass and cuts the files they hold from 120,191 to 47,624.
- **Geo is what holds single-state collections down.** Without it, 297 lot 1 and 301 lot 3 collections pass, against 50 and 43.
- **First-to-last against distinct years makes almost no difference.** 424 collections have gaps in their years, but the list barely changes.
- **Rajya Sabha stays between 40% and 59% in every variant**, because it is 44.6% of the pool.

## 11. Examples

Signal values are demand / temporal / geo / api / liveness. A dash means the signal has no value.

### Highest-scoring datasets overall (all API-fed single files)

| Score | Signals | Publisher | Title |
|---|---|---|---|
| 0.9744 | – / – / 1.00 / 1 / 0.86 | Science and Technology | State-wise Sanctioned ongoing proposals in DBT through EProMIS As on Date |
| 0.9652 | – / – / – / 1 / 0.86 | Panchayati Raj | Local Government Directory (LGD) - Villages |
| 0.9652 | – / – / – / 1 / 0.86 | Panchayati Raj | Local Government Directory (LGD) - Local Bodies |
| 0.9568 | – / – / – / 1 / 0.83 | Panchayati Raj | Local Government Directory (LGD) - Villages with PIN Codes |
| 0.9533 | – / – / – / 1 / 0.81 | Panchayati Raj | Drone Flown Villages |
| 0.9510 | – / – / – / 1 / 0.80 | Coal | Coal/Lignite Production and Dispatch CIL,SCCL,NLCIL As on date |
| 0.8889 | 0.67 / – / 1.00 / 1 / 0.83 | Commerce and Industry | State-wise IEM part-A data on Investment and Employment from August 1991 to till last month |
| 0.8812 | 1.00 / – / 0.50 / 1 / 0.86 | Commerce and Industry | Wholesale Price Index (Base Year 2011-12) till last month |

### Highest-scoring collections that are not API-fed

| Score | Signals | Files | States | Years | Publisher | Collection |
|---|---|---|---|---|---|---|
| 0.5737 | 1.00 / 0.93 / 0.92 / 0 / 0.04 | 365 | 33 | 30 | Environment, Forest and Climate Change | Location wise daily Ambient Air Quality |
| 0.5598 | 1.00 / 0.51 / 1.00 / 0 / 0.82 | 6 | national | 8 | School Education | State/UT-wise District Score from 2018-19 to 2023-24 |
| 0.5349 | 1.00 / 0.71 / 0.50 / 0 / 0.83 | 61 | national | 15 | Statistics | State Level Consumer Price Index (Rural/Urban) |
| 0.5253 | 0.83 / – / 1.00 / 0 / 0.79 | 12 | national | – | Road Transport and Highways | State/UT-wise Persons Killed in Accidents by Victim Type from 2019 to 2022 |
| 0.5246 | 1.00 / 0.68 / 1.00 / 0 / 0.04 | 15,701 | 36 | 14 | Health (HMIS) | HMIS district level item wise and month wise comparison of various indicators |
| 0.5236 | 1.00 / 0.66 / 0.50 / 0 / 0.83 | 68 | 1 | 13 | Statistics | All India Consumer Price Index (Rural/Urban) (Base: 2012=100) from April 2016 to November 2025 |
| 0.5214 | 0.82 / 0.61 / 1.00 / 0 / 0.55 | 5 | national | 11 | National Crime Records Bureau | State/UT-wise Classification of Railway Accidents |
| 0.5086 | 1.00 / 0.66 / 0.94 / 0 / 0.02 | 1,745 | 34 | 13 | Health (HMIS) | Performance of Key HMIS Indicators for Maternal Health |
| 0.5048 | 1.00 / 0.64 / 0.97 / 0 / 0.00 | 70 | 35 | 12 | Census | Primary Census Abstract from 2001 to 2011 |
| 0.5032 | 1.00 / 0.58 / 0.50 / 0 / 0.83 | 108 | national | 10 | Central Electricity Authority | Monthly Coal Statement of Thermal Power Stations (direct merge) |

### The 19 collections with 1,000 or more files

| Score | Passes | Files | States | Years | Lot | Collection |
|---|---|---|---|---|---|---|
| 0.5246 | p99 | 15,701 | 36 | 14 | 1 | HMIS district level item wise and month wise comparison of various indicators |
| 0.5086 | p99 | 1,745 | 34 | 13 | 1 | Performance of Key HMIS Indicators for Maternal Health |
| 0.5086 | p99 | 1,745 | 34 | 13 | 1 | Performance of Key HMIS Indicators for Child Health |
| 0.5086 | p99 | 1,744 | 34 | 13 | 1 | Performance of Key HMIS Indicators for Family Planning |
| 0.5086 | p99 | 1,729 | 34 | 13 | 1 | Performance of Key HMIS Indicators for All Indicators |
| 0.5086 | p99 | 1,714 | 34 | 13 | 1 | Performance of Key HMIS Indicators for Other Indicators |
| 0.4890 | p99 | 1,783 | 34 | 13 | 1 | Performance on Reproductive Child Health (RCH) Indicators |
| 0.4860 | p99 | 4,060 | 35 | 9 | 1 | Performance of Key HMIS Indicators Across Sub Districts |
| 0.4829 | p99 | 4,801 | 1 | 4 | 3 | Crop Survey (FY 2018-19 to 2021-22) (API-fed) |
| 0.4800 | p99 | 7,783 | 34 | 9 | 1 | District-wise Monthly Range-wise Performance of Public Facilities for IPD, Allopathic and Ayush Attendance, 2012-13 to 2019-20 |
| 0.4800 | p99 | 6,515 | 34 | 9 | 1 | Monthly Range-wise Performance of Public Facilities for Operation Major and Minor, 2012-13 to 2019-20 |
| 0.4800 | p99 | 6,511 | 34 | 9 | 1 | District-wise Monthly Range-wise Performance of Public Facilities for Deliveries and C-Section, 2012-13 to 2019-20 |
| 0.4718 | p99 | 4,421 | 36 | 7 | 2 | Number of Schools by Availability of Infrastructure and Facilities (UDISE plus), 2012-13 to 2018-19 |
| 0.4505 | p95 | 2,165 | 34 | 9 | 1 | District-wise Quarterly Range-wise Performance of Public Facilities for Operation Major and Minor, 2012-13 to 2019-20 |
| 0.4399 | p95 | 2,586 | 34 | 9 | 1 | District-wise Quarterly Range-wise Performance of Public Facilities for IPD, Allopathic and Ayush Attendance, 2012-13 to 2019-20 |
| 0.4325 | p95 | 2,165 | 34 | 9 | 1 | District-wise Quarterly Range-wise Performance of Public Facilities for Deliveries and C-Section, 2012-13 to 2019-20 |
| 0.4305 | p95 | 2,827 | 36 | 4 | 2 | Number of Teachers by Gender, Qualification, Classes Taught (UDISE plus), 2015-16 to 2018-19 |
| 0.4275 | p95 | 2,781 | 35 | 4 | 2 | Enrolment by Location, School Management, School Category and Social Category (UDISE plus), 2015-16 to 2018-19 |
| 0.4064 | p95 | 1,948 | 35 | 3 | 2 | Enrolment by Location, School Management, School Category and Social Category (UDISE plus), 2012-13 to 2014-15 |

Some names are shortened here; the CSV has them in full.

### A typical dataset from each group (at the group's median score)

The p90 threshold is 0.2931.

| Group | Score | Signals | Files | Title |
|---|---|---|---|---|
| Lot 2 collections | 0.2750 | 0.45 / 0.14 / 1.00 / 0 / 0.00 | 28 | State-wise Distribution of Scheduled Caste Population by Sex, 1991 |
| Rajya Sabha | 0.2014 | 0.21 / 0.31 / 0.50 / 0 / 0.06 | 1 | State/UTs-wise Approval of ICT and Smart Classrooms under Samagra Shiksha from 2018-19 to 2021-22 |
| Lot 3 collections | 0.1261 | – / 0.37 / 0.03 / 0 / 0.03 | 5 | Details Of Ferry Service Managed Departmentally (FY 2016-17 to 2020-21) |
| Lot 1 collections | 0.0709 | 0.03 / 0.24 / 0.03 / 0 / 0.02 | 27 | HMIS Item-wise Cumulative Report for Sub-districts of Firozabad, Uttar Pradesh (FY 2018-19 to 2020-21) |

## 12. API-fed datasets only (`--api-only`)

`hvd_score_v2.py` reads `field_from_api` in two places. The API signal, 30% of the score, is in every run above. The `--api-only` flag is separate: it scores only the API-fed rows and takes every scale and every cut over those alone. The earlier sections did not run it; this section does. The README gives that mode, with a fixed score threshold, as the production setting.

`hvd_score_collections.py` now has the same flag. A dataset is kept when at least one of its files is API-fed, and it keeps all of its files.

### The pool

| | Files | Future datasets |
|---|---|---|
| API-fed files in the three lots (lot 1: none, lot 2: 957, lot 3: 5,320) | 6,277 | |
| Of those, marked `to be removed` and left out | 74 | |
| Single files | 558 | 558 |
| Collections | 5,825 (5,645 API-fed, 180 not) | 33 |
| **Scored** | **6,383** | **591** |

### Cuts

| | Per file (6,277 files) | Per dataset (591 datasets) |
|---|---|---|
| Top 10% | 0.6981 → 1,605 files | 0.6544 → 60 datasets (4 collections), 206 files |
| Top 5% | 0.6981 → 1,605 files | 0.7578 → 31 datasets (1 collection), 66 files |
| Top 1% | 0.8495 → 95 files | 0.8641 → 6 datasets (no collection), 6 files |
| Score of 0.42 or more | 6,275 files | 563 datasets (32 collections), 6,326 files |

The per-file run is `hvd_score_v2.py --api-only` as it stands, so it still includes the 74 files marked `to be removed`.

**Per file, the 10% and 5% cuts are the same list.** 5,184 of the 6,277 files score between 0.69 and 0.70, so both cuts fall on 0.6981 and return the same 1,605 files. 1,318 of them are files of one Karnataka crop survey. Per dataset that survey is a single row, ranked 484 of 591, and the three cuts are distinct.

**The fixed threshold of 0.42 no longer filters.** It passes 563 of the 591 datasets. The value comes from the README, which describes `hvd_score.py`, where the API flag is not part of the score. In v2 the flag is 30% of the weight and every row in this run has it. The scores that match the percentile cuts today are 0.654, 0.758 and 0.864.

### Who passes

| Group | Datasets | Files | No view or download counts | Top 10% | Top 5% | Top 1% | Median score |
|---|---|---|---|---|---|---|---|
| Lot 2 collections | 29 | 578 | 0 | 3 | 1 | 0 | 0.527 |
| Lot 2 single files | 482 | 482 | 3 | 23 | 9 | 1 | 0.530 |
| Lot 3 collections | 4 | 5,247 | 4 | 1 | 0 | 0 | 0.512 |
| Lot 3 single files | 76 | 76 | 76 | 33 | 21 | 5 | 0.586 |
| **Total** | **591** | **6,383** | **83** | **60** | **31** | **6** | **0.530** |

Lot 3 is 80 of the 591 datasets and 34 of the 60 in the top 10%. None of its datasets has view or download counts, so none has a demand value to pull its score down.

| Publisher | Datasets | Files | Top 10% | Top 5% | Top 1% | Median score | Median days since last refresh |
|---|---|---|---|---|---|---|---|
| North Eastern Region (MDoNER) | 141 | 377 | 1 | 0 | 0 | 0.558 | 604 |
| Smart Cities Mission (16 cities) | 133 | 133 | 2 | 0 | 0 | 0.522 | 1,716 |
| Agricultural Research (ICAR) | 81 | 115 | 0 | 0 | 0 | 0.518 | 2,129 |
| Lot 3, publisher blank | 44 | 5,287 | 9 | 5 | 0 | 0.465 | 2,017 |
| MoSPI | 37 | 41 | 3 | 0 | 0 | 0.484 | 1,120 |
| Jal Shakti | 28 | 130 | 1 | 0 | 0 | 0.506 | 922 |
| Commerce and Industry (DPIIT) | 14 | 14 | 8 | 3 | 0 | 0.687 | 101 |
| Culture | 13 | 13 | 10 | 9 | 0 | 0.776 | 639 |
| MSME | 12 | 47 | 5 | 3 | 0 | 0.605 | 2,620 |
| Panchayati Raj | 12 | 12 | 6 | 6 | 4 | 0.745 | 90 |
| Rajya Sabha | 10 | 10 | 0 | 0 | 0 | 0.411 | 1,167 |
| Space (ISRO) | 7 | 7 | 7 | 0 | 0 | 0.752 | 2,503 |
| 21 other publishers | 59 | 197 | 8 | 5 | 2 | 0.576 | 147 |
| **Total** | **591** | **6,383** | **60** | **31** | **6** | **0.530** | **1,377** |

The three largest groups, 355 of the 591 datasets, put 3 in the top 10%. They are project lists for one state, city feeds and publication lists, all with low traffic, and 338 of the 355 have no date range.

### Fewer signals, higher score

Every dataset in this run has the API flag, so the order is set by the other four signals and by how many of them are missing. A dataset with only the API flag and liveness scores 0.75 + 0.25 × liveness. That is above the top 10% cut whatever its liveness.

| Signals with a value | Datasets | In the top 10% | Pass rate | Median score |
|---|---|---|---|---|
| 2 (API flag and liveness) | 18 | 18 | 100% | 0.758 |
| 3 | 281 | 17 | 6.0% | 0.541 |
| 4 | 182 | 20 | 11.0% | 0.524 |
| 5 | 110 | 5 | 4.5% | 0.497 |

All 18 two-signal datasets are lot 3 files. Five of the six datasets in the top 1% are among them.

Signal values below are demand / temporal / geo / api / liveness. A dash means the signal has no value.

| Rank | Score | Signals | Days since last refresh | Dataset |
|---|---|---|---|---|
| 2 | 0.965 | – / – / – / 1 / 0.86 | 79 | Local Government Directory (LGD) - Villages |
| 7 | 0.854 | 0.95 / – / 1.00 / 1 / 0.01 | 2,472 | List of MSME Registered Units under Udyog Aadhaar Memorandum (collection, 36 files) |
| 18 | 0.776 | – / 0.70 / – / 1 / 0.30 | 639 | Museum Grant Scheme Data (Culture) |
| 34 | 0.752 | – / – / – / 1 / 0.01 | 2,503 | Ground water Prospects Information System (ISRO) |
| 56 | 0.661 | 1.00 / 0.00 / 0.50 / 1 / 0.86 | 80 | Variety-wise Daily Market Prices Data of Commodity |
| 210 | 0.558 | 0.02 / – / – / 1 / 0.32 | 604 | List of ongoing projects with funds status under NLCPR for Arunachal Pradesh for Sports as on Date (MDoNER) |
| 372 | 0.518 | 0.06 / – / 0.50 / 1 / 0.02 | 2,129 | ICAR Publication Repository as on date: ICAR Headquarters and DKMA Collection |
| 484 | 0.503 | – / 0.38 / 0.03 / 1 / 0.04 | 1,652 | Crop Survey (FY 2018-19 to 2021-22) (collection, 4,801 files) |
| 591 | 0.366 | 0.04 / 0.00 / – / 1 / 0.04 | 1,715 | D-19 Solid Waste Disposal Dhramshala 2021 |

The daily market prices feed is at the top of the traffic scale and was refreshed 80 days ago. It ranks 56th, below seven ISRO datasets that were last refreshed almost seven years ago and have no other signal.

### Most API-fed datasets are not being refreshed

| Days since last refresh | Datasets | In the top 10% |
|---|---|---|
| 90 or fewer | 39 | 16 |
| 91 to 365 | 28 | 10 |
| 1 to 2 years | 146 | 13 |
| 2 to 5 years | 169 | 8 |
| 5 to 10 years | 199 | 13 |
| More than 10 years | 10 | 0 |

The median is 1,377 days, about 3.8 years. 67 of the 591 datasets were refreshed in the last year; 378 were last refreshed more than two years ago.

v2 also checks each API-fed file against its own declared refresh period (punctuality). It carries no weight in the score. Of the 6,203 API-fed files, 5,230 have a period that can be checked: 10 were refreshed inside it and 5,220 were not. By dataset, 296 can be checked and 10 have a file that is on time. For 5,288 of the files, which are external links, v2 measures freshness from the last date the data covers and not from the modification date.

### One API-fed file makes a whole collection API-fed

5 of the 33 collections contain files that are not API-fed. In three of them a single file carries the flag.

| Collection | Files | API-fed files | Rank here (of 591) | Score in the full run | Full-run score without the API flag |
|---|---|---|---|---|---|
| Crop Survey (FY 2018-19 to 2021-22) | 4,801 | 4,759 | 484 | 0.4829 | |
| Evapotranspiration 2018 to 2020 | 103 | 1 | 59 | 0.7316 | 0.4316 |
| Hobli Wise and Gram Panchayat Wise Level Average Yield for Kharif Season (FY 2016-17) | 30 | 1 | 587 | 0.3863 | 0.0113 |
| KSRTC Ticket Booking Franchisee Counters Outside the State | 6 | 3 | 51 | 0.6898 | 0.1443 |
| Household Consumer Expenditure, NSS 50th Round | 5 | 1 | 43 | 0.7714 | 0.4714 |

Three of the four collections in this run's top 10% are in this table; the fourth, Udyog Aadhaar, is API-fed on all 36 files. In the full run (cuts 0.2931 / 0.3363 / 0.4507) the last four all pass the top 5%. Without the flag, two of them would not pass the top 10%.

### Against the full run

The order of these 591 datasets is close to their order in the full run: rank correlation 0.94, and 46 of the top 60 are the same. The differences come from the scales, which are now set by API-fed datasets alone. The views ceiling is 937 per month against 26.8 in the full run, and the downloads ceiling 426 per month against 5.8. In the full run 127 of these datasets had a demand value of 0.5 or more; here 42 do.

## 13. Open points

| Point | Effect | Status |
|---|---|---|
| A collection's demand is the sum of its files' traffic | The largest assumption in this run; averaging instead halves the collections that pass | Needs a decision |
| 5,446 lot 1 collections are the same two HMIS reports, one per district | They stay at the bottom as merged; none passes | A question about how collections are drawn, not about scoring |
| 504 collections have a single file | They score exactly as the file would; none passes | For information |
| Lot 3 has no view or download counts | Demand is missing for all 7,428 lot 3 datasets | `--stats` would fetch live counts from the portal, about 1.7 hours for all lots |
| Lot 3 publisher is blank on 29,025 files | Lot 3 cannot be broken down by publisher | Data gap |
| A missing date range scores better than a 1 to 4 year range | Favours single files, 33% of which have no date range | Carried over from the per-file analysis |
| The temporal ceiling is now 37 years | Tables of 5 to 10 years score much lower on temporal than per file | Follows from the pool; could be fixed at a chosen number of years |
| Lot 1 date ranges are read by year label | A single financial year reads as 2 years; 1,837 lot 1 collections span "2 years" | Not changed |
| 18 of the top 100 datasets rest on the API flag and liveness only | They rank above every dataset with full evidence | By design in v2 |
| `--api-only` with the fixed threshold of 0.42 | Passes 563 of the 591 API-fed datasets; the value predates the API signal | Needs a new value if that mode is used with v2; 0.654 matches the top 10% today |
| A collection counts as API-fed if any one file is | 3 collections (138 files) are API-fed through a single file; 2 of them are in the API-only top 10% | Needs a decision: any file, or most files |
| Lot 3 API-fed datasets have no counts | 34 of the 60 in the API-only top 10% are lot 3 | `--api-only --stats` fetches counts for these 6,383 files only, about 2 minutes at the script's stated rate; not run |
| 452 of the 472 API-fed files inside lot 2 collections are marked `failed to download` | Those collections have no downloaded files to merge yet | For information |
