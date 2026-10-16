# Lot 3 merge summary

Source: `dublin_core_lot3` in `transformation/metadata.db`, refreshed from DuckLake on 2026-09-30.

## Before and after

| | Count |
|---|---:|
| Datasets before merging | 29,598 |
| Datasets being merged into collections | 22,922 |
| **Collections after merging** | **897** |

## By merge_method

| merge_method | Datasets | Collections | Datasets per collection (min / median / max) |
|---|---:|---:|---|
| change_in_header | 20,783 | 790 | 5 / 8 / 4,801 |
| curate | 2,089 | 100 | 5 / 7 / 707 |
| direct | 50 | 7 | 5 / 6 / 13 |
| **Merged total** | **22,922** | **897** | |
| non-mergeable | 6,531 | – | stays as individual datasets |
| to be removed | 145 | – | older editions dropped |
| **All rows** | **29,598** | | |

## Notes

- Every collection has at least 5 member datasets, and each collection uses a single merge_method.
- The largest collection is *Crop Survey (FY 2018-19 to 2021-22)*, with 4,801 datasets.
- Counting the 6,531 non-mergeable datasets that stay as they are, the catalogue after merging
  holds 897 + 6,531 = **7,428** entries, down from 29,598. The 145 "to be removed" rows are excluded.
- The 29,598 rows include one duplicate nid (88731, which appears in two source CSVs) and one row
  with a null nid. Both are non-mergeable.
