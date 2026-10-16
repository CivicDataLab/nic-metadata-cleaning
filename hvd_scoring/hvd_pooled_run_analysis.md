# HVD scoring across all three lots: what gets detected, and why Rajya Sabha ranks high

Run date: 6 October 2026, against `transformation/metadata.db`.

## 1. What was run

All three lots were scored together as one pool of 354,291 datasets, so every scale and every cut is taken over the whole pool rather than per table.

| Lot | Table | Rows |
|---|---|---|
| Lot 1 | `dublin_core_metadata` | 206,972 |
| Lot 2 | `dublin_core_remaining` | 117,721 |
| Lot 3 | `dublin_core_lot3` | 29,598 |
| **Pool** | | **354,291** |

Command:

```
python3 hvd_scoring/hvd_score_api.py --db transformation/metadata.db --table all \
    --cut-value 10 --extra-cuts 5 1 --out hvd_scoring/hvd_scores_all.csv
```

Output: `hvd_scoring/hvd_scores_all.csv`, one row per dataset, with the columns `hvd_candidate` (top 10%), `hvd_candidate_p95` (top 5%) and `hvd_candidate_p99` (top 1%).

| Cut | Meaning | Score threshold | Candidates |
|---|---|---|---|
| p90 | top 10% | 0.2580 | 35,443 |
| p95 | top 5% | 0.3319 | 17,715 |
| p99 | top 1% | 0.4245 | 3,543 |

## 2. Summary

- **Rajya Sabha is 9.4% of the pool and about 40% of every cut.** It supplies 14,446 of the 35,443 candidates at p90, 6,256 of 17,715 at p95 and 1,391 of 3,543 at p99.
- **API-fed datasets do rank first, but there are only 6,277 of them.** The top 100 rows are all API-fed. All 6,277 pass p90 and p95. Only 1,105 pass p99, because most have the API flag and nothing else and score about 0.38.
- **The remaining places are decided by the other four signals, and Rajya Sabha leads on three of them.** Its rows are recent, national, multi-year tables with some traffic.
- **58% of the pool is one publisher at the bottom of every scale.** Lot 1 is 206,968 Health Ministry HMIS rows: single-year, mostly single-state, with a median of one lifetime view.
- **A dataset with no date range does better than one known to cover a single year.** Missing signals have their weight redistributed; a one-year range scores zero.
- **Large statistical series are almost entirely excluded.** Census, School Education and HMIS each pass p90 at under 3%.

## 3. Who passes each cut

"Share" is the group's share of all candidates at that cut. "Rate" is the share of the group's own rows that pass.

| Group | Rows | % of pool | p90 passed | p90 share | p90 rate | p95 passed | p95 share | p95 rate | p99 passed | p99 share | p99 rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Lot 1 (all HMIS) | 206,972 | 58.4% | 4,323 | 12.2% | 2.1% | 370 | 2.1% | 0.2% | 99 | 2.8% | 0.05% |
| Lot 2, excluding Rajya Sabha | 84,551 | 23.9% | 8,916 | 25.2% | 10.5% | 4,326 | 24.4% | 5.1% | 1,685 | 47.6% | 2.0% |
| Rajya Sabha (all in lot 2) | 33,170 | 9.4% | 14,446 | 40.8% | 43.6% | 6,256 | 35.3% | 18.9% | 1,391 | 39.3% | 4.2% |
| Lot 3 | 29,598 | 8.4% | 7,758 | 21.9% | 26.2% | 6,763 | 38.2% | 22.8% | 368 | 10.4% | 1.2% |
| **Total** | 354,291 | 100% | 35,443 | | | 17,715 | | | 3,543 | | |

## 4. How the score is built

The score is a weighted sum of five signals, each between 0 and 1. The weights below are the ones in the code's `weights` dict, which is what this run used.

| Signal | Weight | What it measures | Rows with a value |
|---|---|---|---|
| demand | 0.20 | Downloads and views per month since publication | 323,078 (91.2%) |
| temporal | 0.25 | Number of years the data spans | 331,107 (93.5%) |
| geo | 0.15 | Share of the 36 States/UTs covered | 335,749 (94.8%) |
| api | 0.30 | 1 if `field_from_api` is set, otherwise 0 | 354,291 (100%) |
| liveness | 0.10 | How recently it was modified (halves every 365 days) | 354,289 (100%) |

When a signal has no value for a row, its weight is shared out across the signals that do. The maximum a non-API dataset can score is 0.70.

## 5. Where the API-fed datasets land

| Table | `field_from_api` = 1 | = 0 | blank |
|---|---|---|---|
| Lot 1 | 0 | 206,972 | 0 |
| Lot 2 | 957 (10 of them Rajya Sabha) | 64,533 | 52,231 |
| Lot 3 | 5,320 | 23,769 | 509 |
| **Pool** | **6,277 (1.8%)** | 295,274 | 52,740 |

Composition of the top of the ranking:

| Top N by score | API-fed | Rajya Sabha (not API-fed) | Other (not API-fed) | Lowest score in band |
|---|---|---|---|---|
| 100 | 100 | 0 | 0 | 0.7640 |
| 500 | 468 | 11 | 21 | 0.5737 |
| 1,000 | 723 | 121 | 156 | 0.5182 |
| 3,543 (p99) | 1,105 | 1,381 | 1,057 | 0.4245 |
| 5,000 | 1,106 | 2,274 | 1,620 | 0.3970 |
| 10,000 | 4,566 | 3,058 | 2,376 | 0.3816 |
| 17,715 (p95) | 6,277 | 6,246 | 5,192 | 0.3319 |
| 35,443 (p90) | 6,277 | 14,436 | 14,730 | 0.2580 |

Why most API-fed rows miss p99:

- 5,169 of the 5,320 lot 3 API-fed rows score between 0.380 and 0.386. Most of them (4,759) are single-season crop survey files: no traffic data, a one-year range, one state.
- A row like that scores (0.30 + small amounts for geo and liveness) ÷ 0.80 ≈ 0.38, because the demand weight is redistributed.
- The p99 threshold is 0.4245, so they fall just below it. The 957 lot 2 API-fed rows score a median of 0.565 and 955 of them pass p99.

So the API flag guarantees a place in the top 5%, but it fills only 6,277 of the 17,715 places at p95 and 1,105 of the 3,543 at p99.

## 6. Why Rajya Sabha wins the remaining places

Mean signal value by group, and the points each signal contributes to the group's mean score:

| Signal | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) | Lot 3 |
|---|---|---|---|---|
| demand | 0.27 | 0.10 | 0.02 | no data |
| temporal | 0.41 | 0.19 | 0.06 | 0.10 |
| geo | 0.72 | 0.81 | 0.31 | 0.03 |
| api | 0.00 | 0.01 | 0.00 | 0.18 |
| liveness | 0.11 | 0.03 | 0.01 | 0.04 |
| **Mean score** | **0.246** | 0.189 | 0.068 | 0.112 |
| Median score | 0.242 | 0.183 | 0.008 | 0.009 |

| Points contributed to mean score | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) | Lot 3 |
|---|---|---|---|---|
| demand | 0.062 | 0.024 | 0.004 | 0.000 |
| temporal | 0.064 | 0.043 | 0.016 | 0.034 |
| geo | 0.107 | 0.113 | 0.047 | 0.005 |
| api | 0.000 | 0.005 | 0.000 | 0.068 |
| liveness | 0.013 | 0.004 | 0.001 | 0.006 |

### 6.1 Demand

The pool has very little traffic, so a small amount of use reads as high demand.

| | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) |
|---|---|---|---|
| Lifetime views, median | 55 | 10 | 1 |
| Lifetime views, 99th percentile | 793 | 1,019 | 21 |
| Lifetime downloads, median | 3 | 0 | 0 |
| Rows with zero downloads | 22.2% | 55.2% | 52.1% |
| Age in months, median | 52 | 114 | 87 |
| Issued in 2021 or later | 63.8% | 24.4% | 6.9% |
| Views per month, median | 1.02 | 0.09 | 0.01 |
| Views per month, 90th percentile | 5.98 | 1.20 | 0.04 |
| Downloads per month, median | 0.06 | 0.00 | 0.00 |

- The demand scale is capped at the pool's 99th percentile: **8.3 views a month and 1.5 downloads a month**. Anything at or above that gets full marks.
- Rajya Sabha rows that pass p99 have a median of 9.2 views and 0.84 downloads a month.
- Lot 3 has no traffic counts at all, so demand is missing on all 29,598 rows.

### 6.2 Geo

No Rajya Sabha row belongs to a collection, so none is scored on how many states its collection covers. They are scored by two fallback rules instead.

| | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) | Lot 3 |
|---|---|---|---|---|
| Rows with a `Collection` | 0.0% | 69.7% | 99.1% | 77.4% |
| `Spatial Coverage` is "India" | 87.7% | 28.1% | 2.1% | 0.7% |
| Title says "State/UT-wise" | 38.1% | 7.9% | 0.5% | 0.2% |
| **Rule that set the geo value** | | | | |
| Collection's share of 36 States/UTs | 0.0% | 62.4% | 97.9% | 77.2% |
| "India" → 0.5 | 49.8% | 20.4% | 1.6% | 0.5% |
| "State/UT-wise" title → 1.0 | 38.1% | 7.9% | 0.5% | 0.2% |
| No rule applies (no value) | 12.0% | 9.4% | 0.05% | 22.0% |
| Rows scoring 2/36 or less | 0.0% | 0.2% | 68.2% | 77.1% |
| Mean geo value | 0.72 | 0.81 | 0.31 | 0.03 |

The lowest geo value a Rajya Sabha row can get is 0.5. The typical lot 1 or lot 3 row gets 1/36 (0.03).

### 6.3 Temporal

| Years spanned | Signal value | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) | Lot 3 |
|---|---|---|---|---|---|
| No usable date range | none | 38.8% | 11.0% | 0.1% | 2.8% |
| 1 year | 0.00 | 9.4% | 28.7% | 78.0% | 83.4% |
| 2 to 4 years | 0.23 to 0.51 | 34.1% | 55.6% | 21.7% | 4.7% |
| 5 to 9 years | 0.61 to 0.90 | 16.1% | 2.3% | 0.1% | 2.2% |
| 10 years or more | 0.95 to 1.00 | 1.7% | 2.4% | 0.1% | 6.9% |
| Median span | | 3 | 2 | 1 | 1 |

- The scale is capped at 11 years, the pool's 99th percentile. A span of 11 years or more scores 1.0.
- 51.8% of Rajya Sabha rows span two or more years. Their titles typically read "… from 2015-16 to 2024-25".

### 6.4 Liveness

| Year last modified | Rajya Sabha | Lot 2, others | Lot 1 (HMIS) | Lot 3 |
|---|---|---|---|---|
| 2019 or earlier | 0.7% | 37.1% | 69.9% | 19.9% |
| 2020 | 0.0% | 3.5% | 20.7% | 17.3% |
| 2021 | 38.8% | 35.2% | 9.4% | 26.2% |
| 2022 | 20.3% | 18.5% | 0.0% | 29.2% |
| 2023 | 15.8% | 1.3% | 0.0% | 2.0% |
| 2024 | 12.7% | 1.0% | 0.0% | 1.6% |
| 2025 | 11.7% | 2.0% | 0.0% | 3.1% |
| 2026 | 0.0% | 1.4% | 0.0% | 0.6% |
| Median liveness value | 0.053 | 0.003 | 0.007 | 0.020 |

60.5% of Rajya Sabha rows were modified in 2022 to 2025. 90.6% of lot 1 was last modified in 2020 or earlier. This signal has the smallest weight and adds about 0.013 to the Rajya Sabha mean.

## 7. An unknown date range beats a known one-year range

A row with no usable date range has the temporal weight redistributed. A row known to cover one year scores 0 on temporal and keeps the full weight against it.

| Years spanned | Rajya Sabha rows | Mean score | Pass p90 | Other rows | Mean score | Pass p90 |
|---|---|---|---|---|---|---|
| No usable date range | 12,853 | 0.227 | 33.9% | 10,331 | 0.195 | 26.0% |
| 1 year | 3,122 | 0.145 | 6.7% | 210,424 | 0.057 | 2.8% |
| 2 to 4 years | 11,312 | 0.246 | 41.8% | 93,358 | 0.179 | 6.6% |
| 5 to 9 years | 5,333 | 0.334 | 86.1% | 2,751 | 0.307 | 73.7% |
| 10 years or more | 550 | 0.417 | 100% | 4,257 | 0.372 | 100% |

4,363 of the 14,446 Rajya Sabha candidates at p90 have no date range.

## 8. What the result is sensitive to

Each row re-scores the pool with one change and recomputes the cuts. Figures are Rajya Sabha rows passing, and their share of all candidates at that cut.

| Change | p90 rows | p90 share | p95 rows | p95 share | p99 rows | p99 share |
|---|---|---|---|---|---|---|
| **Baseline (weights in code)** | **14,446** | **40.8%** | **6,256** | **35.3%** | **1,391** | **39.3%** |
| Geo from collection coverage only (neither fallback rule) | 6,697 | 18.8% | 4,394 | 24.8% | 887 | 18.7% |
| Drop demand | 8,268 | 23.2% | 5,803 | 32.5% | 1,003 | 28.3% |
| Remove only the "State/UT-wise" title rule | 10,336 | 28.8% | 4,999 | 28.2% | 1,122 | 31.7% |
| Score every missing signal as 0 | 12,336 | 34.8% | 6,926 | 39.1% | 1,772 | 50.0% |
| Rank demand within each table | 12,399 | 35.0% | 7,956 | 44.9% | 1,312 | 37.0% |
| Score a missing date range as 0 | 12,560 | 35.4% | 5,538 | 31.3% | 1,518 | 42.8% |
| Remove only the "India" → 0.5 rule | 13,104 | 37.0% | 6,347 | 35.8% | 1,414 | 39.9% |
| Demand on lifetime totals, not per month | 13,488 | 38.1% | 6,091 | 34.4% | 1,019 | 28.8% |
| Drop liveness | 14,003 | 39.5% | 5,630 | 31.8% | 1,261 | 31.9% |
| Drop temporal | 14,276 | 40.3% | 6,839 | 38.6% | 10 | 0.2% |
| Drop geo | 15,282 | 43.1% | 5,012 | 28.3% | 142 | 3.7% |
| Docstring weights (demand 0.35, api 0.15) | 16,969 | 47.9% | 9,056 | 51.1% | 1,878 | 53.0% |
| Drop api | 17,658 | 49.8% | 9,215 | 52.0% | 1,766 | 49.8% |

Reading the table:

- No single change removes Rajya Sabha, because it leads on three signals at once. The largest single effect at p90 is a 54% reduction.
- The API weight of 0.30 is what holds Rajya Sabha to about 40%. Without it, or with the docstring weights, it is about half of every cut.
- The p99 figures for "drop temporal" and "drop geo" fall for a different reason. Removing a signal raises the effective API weight, so the 6,277 API-fed rows rise and take most or all of the 3,543 places.

## 9. Publishers: who is detected and who is not

All 16 publishers with at least 400 rows, out of 186 in the pool, ordered by the share of their rows that pass p90.

| Publisher | Rows | Pass p90 | Pass p95 | Pass p99 | p90 rate | demand | temporal | geo | api | liveness | Mean score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Petroleum and Natural Gas | 485 | 372 | 177 | 51 | 76.7% | 0.28 | 0.63 | 0.60 | 0.00 | 0.10 | 0.306 |
| Statistics and Programme Implementation | 2,774 | 1,631 | 951 | 406 | 58.8% | 0.43 | 0.50 | 0.58 | 0.01 | 0.03 | 0.277 |
| Civil Aviation | 907 | 416 | 39 | 5 | 45.9% | 0.06 | 0.52 | 0.50 | 0.00 | 0.02 | 0.213 |
| **Rajya Sabha** | 33,170 | 14,446 | 6,256 | 1,391 | 43.6% | 0.27 | 0.41 | 0.72 | 0.00 | 0.11 | 0.246 |
| Road Transport and Highways | 2,708 | 1,065 | 595 | 145 | 39.3% | 0.19 | 0.33 | 0.77 | 0.00 | 0.13 | 0.244 |
| Publisher blank (all lot 3) | 29,170 | 7,652 | 6,689 | 326 | 26.2% | none | 0.10 | 0.03 | 0.18 | 0.04 | 0.111 |
| Home Affairs, National Crime Records Bureau | 10,367 | 1,452 | 648 | 78 | 14.0% | 0.10 | 0.23 | 0.68 | 0.00 | 0.06 | 0.186 |
| Animal Husbandry and Dairying | 1,745 | 217 | 85 | 4 | 12.4% | 0.12 | 0.25 | 0.89 | 0.00 | 0.03 | 0.222 |
| Higher Education | 404 | 46 | 35 | 4 | 11.4% | 0.20 | 0.13 | 0.54 | 0.00 | 0.03 | 0.157 |
| NITI Aayog | 1,602 | 169 | 25 | 6 | 10.5% | none | 0.18 | 0.64 | 0.00 | 0.02 | 0.166 |
| Power, Central Electricity Authority | 601 | 61 | 22 | 1 | 10.1% | 0.15 | 0.05 | 0.50 | 0.00 | 0.16 | 0.134 |
| Jal Shakti | 2,249 | 170 | 93 | 28 | 7.6% | 0.17 | 0.02 | 0.71 | 0.01 | 0.03 | 0.139 |
| Central Pollution Control Board | 917 | 64 | 10 | 1 | 7.0% | 0.18 | 0.21 | 0.72 | 0.00 | 0.03 | 0.199 |
| Home Affairs, Registrar General and Census Commissioner | 36,279 | 997 | 199 | 2 | 2.7% | 0.05 | 0.22 | 0.85 | 0.00 | 0.00 | 0.190 |
| School Education and Literacy | 14,635 | 369 | 174 | 22 | 2.5% | 0.02 | 0.00 | 0.99 | 0.00 | 0.05 | 0.159 |
| Health and Family Welfare (HMIS, lot 1) | 206,968 | 4,319 | 368 | 99 | 2.1% | 0.02 | 0.06 | 0.31 | 0.00 | 0.01 | 0.068 |

- The score rewards recent, national, multi-year summary tables that have some traffic.
- It largely excludes series published as many small files: Census, School Education and HMIS.
- Lot 1 is a single publisher. Its 206,968 rows are mostly district-level and monthly slices of 5,665 collections, compared against Rajya Sabha rows that are each a whole table.

## 10. Examples

Signal values are shown as demand / temporal / geo / api / liveness. A dash means the signal has no value for that row.

### Highest-scoring rows overall (all API-fed)

| Score | Signals | Publisher | Title |
|---|---|---|---|
| 0.9753 | – / – / 1.00 / 1 / 0.86 | Science and Technology | State-wise Sanctioned ongoing proposals in DBT through EProMIS As on Date |
| 0.9664 | – / – / – / 1 / 0.87 | Panchayati Raj | Local Government Directory (LGD) - Villages |
| 0.9664 | – / – / – / 1 / 0.87 | Panchayati Raj | Local Government Directory (LGD) - Local Bodies |
| 0.9579 | – / – / – / 1 / 0.83 | Panchayati Raj | Local Government Directory (LGD) - Villages with PIN Codes |
| 0.9559 | 0.92 / – / 1.00 / 1 / 0.83 | Commerce and Industry | State-wise IEM part-A data on Investment and Employment from August 1991 to till last month |
| 0.9544 | – / – / – / 1 / 0.82 | Panchayati Raj | Drone Flown Villages |

Several of these rest on two signals only. Of the top 100 rows, 5 are scored on two signals or fewer, 21 on three and 74 on four or five.

### Highest-scoring Rajya Sabha rows

| Score | Signals | Views | Downloads | Age (months) | Title |
|---|---|---|---|---|---|
| 0.6319 | 1.00 / 0.95 / 1.00 / 0 / 0.44 | 242 | 38 | 15 | State/UT-wise Details of Applications Received and Religious Data for Loans under Pradhan Mantri Mudra Yojana (PMMY) from 2015-16 to 2024-25 |
| 0.6195 | 0.88 / 1.00 / 1.00 / 0 / 0.43 | 66 | 25 | 15 | State/UT-wise Details of Wetlands of International Importance (in Reply to Unstarred Question on 13 February 2025) |
| 0.6151 | 0.92 / 0.95 / 1.00 / 0 / 0.44 | 159 | 17 | 15 | State/NES/UT-wise Details of Number of Houses Completed under Pradhan Mantri Awas Yojana- Urban (PMAY-U) 1.0 from 2015-16 to 2024-25 |
| 0.6137 | 1.00 / 0.95 / 1.00 / 0 / 0.26 | 1,665 | 104 | 23 | State-wise Details of Multidimensional Poverty in India Estimates from 2013-14 to 2022-23 |
| 0.6137 | 1.00 / 0.95 / 1.00 / 0 / 0.26 | 445 | 59 | 23 | State/UT-wise Number of Heavy Rainfall Events in the Country from 2014 to 2023 |
| 0.6039 | 1.00 / 0.84 / 1.00 / 0 / 0.44 | 152 | 25 | 15 | State/UT-wise Details of the Physically Completed Projects under Pilgrimage Rejuvenation and Spiritual, Heritage Augmentation Drive (PRASHAD) Scheme from 2014-15 to 2021-22 |
| 0.5974 | 1.00 / 0.95 / 1.00 / 0 / 0.10 | 1,176 | 98 | 41 | State-wise Per Capita Net State Domestic Product (NSDP) at Current Prices and Constant Prices for the North Eastern States during 2020-21 |
| 0.5953 | 0.97 / 0.00 / 0.50 / 1 / 0.26 | 167 | 96 | 23 | Rajya Sabha Synopsis List (English) |
| 0.5946 | 0.92 / 0.95 / 1.00 / 0 / 0.24 | 262 | 29 | 25 | State/UT-wise Details of Deaths Due to Heat/Sun Stroke from 2013 to 2022 |
| 0.5937 | 0.88 / 1.00 / 1.00 / 0 / 0.18 | 287 | 31 | 30 | State-wise Details of Food Subsidy Released to Decentralized Procurement (DCP) States from 2013-14 to 2023-24 |

### Highest-scoring rows that are neither API-fed nor Rajya Sabha

| Score | Signals | Views | Downloads | Publisher | Title |
|---|---|---|---|---|---|
| 0.6602 | 0.88 / 1.00 / 1.00 / 0 / 0.83 | 708 | 690 | National Crime Records Bureau | State/UT-wise distribution of accidental deaths by natural causes during 2001-2012 |
| 0.6158 | 0.66 / 1.00 / 1.00 / 0 / 0.83 | 165 | 442 | National Crime Records Bureau | State/UT-wise distribution of accidental deaths by un-natural causes during 2001-2012 |
| 0.6063 | 1.00 / 1.00 / 0.50 / 0 / 0.81 | 163 | 85 | Road Transport and Highways | Year-wise Details of Road Accidents, Persons Killed and Injured from 1970 to 2024 |
| 0.6027 | 0.85 / 1.00 / 1.00 / 0 / 0.32 | 406 | 346 | Road Transport and Highways | State/ UT-wise Total Number of Persons Injured in Road Accidents in India from 2003 to 2016 |
| 0.6024 | 0.97 / 1.00 / 0.50 / 0 / 0.84 | 772 | 382 | Statistics and Programme Implementation | All India level Mining Production from 2000-01 to 2015-16 |
| 0.6003 | 1.00 / 1.00 / 1.00 / 0 / 0.00 | 1,708 | 1,560 | Statistics and Programme Implementation | State-wise Percentage Of Distribution Of Rural And Urban Households Having Electricity |

### Typical rows from groups that are mostly excluded

Each is a row at its group's median score. The p90 threshold is 0.2580.

| Group | Score | Signals | Views | Downloads | Title |
|---|---|---|---|---|---|
| Lot 3 API-fed crop survey | 0.3816 | – / 0.00 / 0.03 / 1 / 0.01 | none | none | Crop Survey of HONNAVALLI Hobli of Tiptur Taluk of Tumkur District of Karnataka for Kharif Season 2019-20 |
| Census | 0.1883 | 0.01 / 0.23 / 0.86 / 0 / 0.00 | 8 | 0 | Ever married and currently married population by age at marriage and duration of marriage for Scheduled Castes, 2011 - JHARKHAND |
| School Education (UDISE) | 0.1539 | 0.00 / 0.00 / 1.00 / 0 / 0.04 | 0 | 0 | Number of Teachers by Gender, Academic Qualification, Professional Qualification, Classes Taught, School Category and School Management in Latehar District of Jharkhand (UDISE plus) during 2018-19 |
| HMIS (lot 1) | 0.0083 | 0.02 / 0.00 / 0.03 / 0 / 0.00 | 5 | 2 | Item-wise report for Baloda Bazar of Chhattisgarh Upto August-2013-14 |

The lot 3 crop survey row passes p90 and p95 on its API flag alone, and misses p99.

## 11. Inside Rajya Sabha: which rows pass

| Tier | Rows | demand | temporal | geo | liveness | "State/UT-wise" title | Has a date range | Median span (years) | Median views | Median downloads | Median age (months) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Passes p99 | 1,391 | 0.75 | 0.71 | 0.87 | 0.25 | 72.4% | 73.4% | 6 | 244 | 22 | 25 |
| Passes p95, not p99 | 4,865 | 0.50 | 0.61 | 0.80 | 0.21 | 57.6% | 68.3% | 5 | 118 | 6 | 32 |
| Passes p90, not p95 | 8,190 | 0.29 | 0.49 | 0.79 | 0.12 | 54.2% | 70.0% | 4 | 70 | 3 | 49 |
| Below p90 | 18,724 | 0.16 | 0.27 | 0.64 | 0.07 | 23.5% | 54.7% | 2 | 32 | 3 | 68 |

What the Rajya Sabha rows are:

- All 33,170 are standalone tables with no collection. 19.0% of titles say they are a reply to a question.
- 69.2% of titles carry a year range ("from … to …" or "during …").
- The most common title openings are "Year-wise Details of" (2,301), "State/UT-wise Details of" (2,120), "State/UT-wise Number of" (1,651) and "Statement showing analysis" (867).

The rows that reach p99 are recent, state-wise, multi-year tables with a few hundred views.

## 12. Known issues in this run

| Issue | Effect | Status |
|---|---|---|
| Weights in the code differ from the docstring (code: demand 0.20, api 0.30; docstring: demand 0.35, api 0.15) | The run used the code's weights. With the docstring weights Rajya Sabha rises to about half of every cut. | Not changed |
| Lot 1 date ranges are read by year label, not duration | 44,865 lot 1 rows get a longer span than they cover; 27,853 are read as two years instead of one. This favours lot 1, so it does not explain Rajya Sabha's lead. | Not changed |
| Lot 3 has no download or view counts | Demand is missing on all 29,598 rows and its weight is redistributed. | By design |
| Lot 3 publisher is blank on 29,170 of 29,598 rows | Lot 3 cannot be broken down by publisher. | Data gap |
| Lot 1 traffic counts are far below lot 2's (99th percentile views 21 against 1,019) | Lot 1 scores near zero on demand. Not established whether this is real or the counters cover different periods. | Unverified |
| `hvd_scores_lot3.csv` (the earlier lot 3-only run) predates the fill of lot 3's `Spatial Coverage` | Its geo column is stale: 64 rows had a value then, 23,073 do now. | Needs a re-run if still used |
| Some top rows rest on very few signals | For example the Local Government Directory rows score 0.97 on api and liveness alone. | By design; visible in `n_signals` |

## 13. Suggested next steps

1. Score each collection as one unit (its combined span, states covered and traffic), so that series compete with whole tables on equal terms.
2. Decide how a missing date range should score relative to a one-year range. At present missing is the better outcome.
3. Review the two geo fallback rules for rows with no collection ("India" → 0.5 and "State/UT-wise" title → 1.0).
4. Settle which set of weights is intended, the code's or the docstring's.
5. Read lot 1 date ranges by duration, as the other two lots already are.
6. Fill the lot 3 publisher field before any per-publisher review of lot 3.
