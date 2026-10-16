# HMIS Item-wise sub-district reports merged to state level — Odisha

Every district of Odisha, every financial year, transposed so that each
sub-district-month is a row and each indicator is a column, and stacked into one
table per report basis and indicator framework.

## What was merged

| Basis | Format Version | Datasets | Districts | Rows | Indicator columns | Cells |
|---|---|---|---|---|---|---|
| cumulative | Old (pre 2017-18) | 1,660 | 30 | 20,553 | 318 | 6,466,392 |
| cumulative | Revised (2017-18 onwards) | 1,166 | 30 | 72,725 | 286 | 20,799,350 |
| monthly | Old (pre 2017-18) | 1,660 | 30 | 20,553 | 318 | 6,466,392 |
| monthly | Revised (2017-18 onwards) | 1,168 | 30 | 72,725 | 286 | 20,799,350 |

FY 2011-12 – 2020-21.

## Orientation: indicators are columns

The source files are indicator-per-row, sub-district-per-column. They are
transposed: **one row per sub-district per month**, **one column per indicator**.

The alternative — fully long form, one row per indicator per sub-district per
month — would be 54,531,484 rows for Odisha alone, each
repeating the indicator's full description. Transposing carries exactly the same
cells in 186,556 rows. (`--layout long` writes that form
if it is ever wanted.)

Indicator column labels are `<S.No.> <Parameters>`, with `[<Type>]` appended where
the indicator has a breakdown other than TOTAL (age bands and similar). The full
mapping — group, S.No., description, breakdown — is in `odisha_indicator_columns.csv`.

### Why columns are keyed on the description, not on S.No.

`S.No.` is not a stable identifier even inside one framework:

- the same indicator is published as `8.1` in some files and `8.10` in others
  (`9.1`/`9.10`, `10.1`/`10.10`, `14.1`/`14.10`, `14.2`/`14.20` likewise) — keying
  on it would split one indicator across two columns;
- `10.1` is used for two *different* indicators in the same file (Childhood
  Diseases – Malaria and – Pneumonia) — keying on it would collapse two indicators
  into one column;
- some files export the code as a quoted literal (`'1.1'`) and others bare (`1.1`).

Columns are therefore identified by (Indicator group, Type, Parameters), which is
stable across every file checked. Every `S.No.` variant observed for a column is
recorded in the dictionary's `S.No. variants`.

## Why monthly and cumulative are separate files

Each district-month is published twice:

- `Item-wise report for <District> of Odisha **for** <Month>-<FY>` — that month alone
- `Item-wise report for <District> of Odisha **upto** <Month>-<FY>` — cumulative from
  the start of the financial year

Same indicators, same sub-districts, different basis. In one table the two are
indistinguishable without reading a column, and any sum over the table
double-counts every month. So they are written to separate files, and the basis
is still carried as a column so the files can be concatenated deliberately.

## Key columns

Every row is identified by these; everything after them is an indicator.

| Column | Source |
|---|---|
| `State` | the catalog the datasets belong to |
| `District` | dataset title (`Item-wise report for **<District>** of …`) |
| `Sub District` | source column name |
| `Level` | `subdistrict`, or `district_total` for the `_<District>` roll-up column |
| `Report FY` | dataset title |
| `Month` | dataset title |
| `Report Basis` | `monthly` / `cumulative`, from `for` / `upto` in the title |
| `Format Version` | FY < 2017-18 vs 2017-18 onwards |
| `Facility Category` | `Total` / `Public` / `Private` / `Urban` / `Rural`, from the column name |
| `source_uuid` | provenance — the filename in `data/first_batch_downloads/` |

Values are copied verbatim, read and written as text, so the literal `NA` token
and large integer counts survive the round-trip.

### `Level` exists so aggregates do not double-count

A source column named `SubDistrict-_<District>` (leading underscore) is the
district total, not a sub-district. It is kept — nothing is dropped — but marked
`district_total`. Summing the table without filtering on
`Level = 'subdistrict'` counts every district twice.

### The two indicator frameworks are separate files

HMIS renumbered its indicators in 2017-18. In these datasets the pre-2017-18
framework has 318 indicators and the 2017-18-onwards one
has 286; only 33 codes appear in both, and all 33 mean
something different (`13.2` is *Intraocular Lens implantations* before and *DOTS
cases completed successfully* after). One set of columns cannot hold both, so each
framework gets its own file.

The revision also changed the source header: from 2017-18 each sub-district is
split into five sub-columns (Total / Public / Private / Urban / Rural), which is
where `Facility Category` comes from. Pre-2017-18 files have one column per
sub-district and are recorded as `Total`. The run cross-checks the FY-derived
framework against the observed header shape:

```
header_shape               categorised  plain
format_version                               
Old (pre 2017-18)                    0   3320
Revised (2017-18 onwards)         2334      0
```

## Re-published datasets dropped

5 dataset(s) repeat a district-month already published under
another UUID (4 byte-identical once line endings are normalised).
Keeping both would duplicate every row of that district-month. The dropped
UUIDs are listed in `odisha_duplicates.csv`.

| Dropped | Kept | District | FY | Month | Basis | Identical? |
|---|---|---|---|---|---|---|
| `0915626a-250e-4ab2-babe-7d8f10aeb98f` | `36799aed-eb8b-4d68-bd12-4588425b716f` | Gajapati | 2014-15 | December | cumulative | yes |
| `42b4ed53-db59-43aa-9c8f-3482cb5954f1` | `dd0eadbd-3c53-4a61-8e1c-9b0cc77a7cd6` | Deogarh | 2014-15 | December | cumulative | yes |
| `59052920-2f68-4a03-9602-3a77e49e728c` | `fc2e08f8-7af1-41fb-85a4-98cd11328ea8` | Dhenkanal | 2014-15 | December | cumulative | no |
| `7682b2c2-e368-40f7-b7ad-87a001d46fc5` | `01d3b130-e751-4988-bce5-e7b2ec8a90c5` | Cuttack | 2014-15 | December | cumulative | yes |
| `b5d1dec0-f82e-45f0-a2cf-6fcc47ad19ab` | `fc2e08f8-7af1-41fb-85a4-98cd11328ea8` | Dhenkanal | 2014-15 | December | cumulative | yes |

## Verification

| Check | Result |
|---|---|
| every dataset parsed to state+district+FY+month+basis | PASS (0 unparsed) |
| title basis agrees with Collection (Monthly/Cumulative) | PASS (0 conflicts) |
| title district agrees with Collection district | PASS (0 conflicts) |
| all source files present | PASS (0 missing) |
| every header parsed | PASS (0 problems) |
| file header width == DB `Conforms To` width | PASS (0 differ) |
| file rows == DB row_count (5654/5654 covered) | PASS (0 mismatched) |
| no ragged rows (row width == header width) | PASS (0 rows) |
| every indicator landed in a column | PASS (0 unplaced) |
| cells preserved (file rows x data columns) | PASS (54,531,484 cells) |
| output rows == source data columns | PASS (186,556 rows) |
| (district, FY, month) unique within each basis | PASS (0 colliding keys) |
| FY-derived era matches header shape | PASS ({'categorised': {'Old (pre 2017-18)': 0, 'Revised (2017-18 onwards)': 2334}, 'plain': {'Old (pre 2017-18)': 3320, 'Revised (2017-18 onwards)': 0}}) |
| output row keys unique within a source file | PASS (0 duplicates) |

The row-count check compares each file's actual length against the `row_count`
recorded in `dublin_core_metadata` — an independent number, so it can genuinely
fail on a truncated download or a stale DB row.

## Rows per financial year

| FY | Basis | Datasets | Districts | Rows |
|---|---|---|---|---|
| 2011-12 | cumulative | 14 | 2 | 133 |
| 2011-12 | monthly | 14 | 2 | 133 |
| 2012-13 | cumulative | 206 | 30 | 2,468 |
| 2012-13 | monthly | 206 | 30 | 2,468 |
| 2013-14 | cumulative | 360 | 30 | 4,488 |
| 2013-14 | monthly | 360 | 30 | 4,488 |
| 2014-15 | cumulative | 360 | 30 | 4,488 |
| 2014-15 | monthly | 360 | 30 | 4,488 |
| 2015-16 | cumulative | 360 | 30 | 4,488 |
| 2015-16 | monthly | 360 | 30 | 4,488 |
| 2016-17 | cumulative | 360 | 30 | 4,488 |
| 2016-17 | monthly | 360 | 30 | 4,488 |
| 2017-18 | cumulative | 360 | 30 | 22,440 |
| 2017-18 | monthly | 360 | 30 | 22,440 |
| 2018-19 | cumulative | 360 | 30 | 22,440 |
| 2018-19 | monthly | 360 | 30 | 22,440 |
| 2019-20 | cumulative | 356 | 30 | 22,235 |
| 2019-20 | monthly | 359 | 30 | 22,320 |
| 2020-21 | cumulative | 90 | 30 | 5,610 |
| 2020-21 | monthly | 89 | 30 | 5,525 |

## Reproduce

```bash
python transformation/merge_hmis_itemwise_subdistrict.py --state 'Odisha'
```

| Output | Contents |
|---|---|
| `hmis_itemwise_subdistrict_odisha_monthly_pre-2017-18.csv` | monthly figures, pre-2017-18 indicators, all districts, all years |
| `hmis_itemwise_subdistrict_odisha_monthly_2017-18-onwards.csv` | monthly figures, 2017-18-onwards indicators, all districts, all years |
| `hmis_itemwise_subdistrict_odisha_cumulative_pre-2017-18.csv` | cumulative figures, pre-2017-18 indicators, all districts, all years |
| `hmis_itemwise_subdistrict_odisha_cumulative_2017-18-onwards.csv` | cumulative figures, 2017-18-onwards indicators, all districts, all years |
| `odisha_indicator_columns.csv` | column dictionary: label, group, S.No. (+ variants), description, breakdown |
| `odisha_manifest.csv` | one row per source dataset: district, FY, month, basis, columns, row counts |
| `odisha_duplicates.csv` | datasets dropped as re-publications |
| `odisha_merge_notes.md` | this note |
