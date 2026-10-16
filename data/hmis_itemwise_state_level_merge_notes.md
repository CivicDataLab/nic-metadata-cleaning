# Vertical merge example — HMIS Item-wise reports at State level

Two collections merged into one table. This note records *why* they were
selected for merging and what the merge did.

## The two collections

| # | Collection | Datasets | FY span | Header variants (raw files) |
|---|---|---|---|---|
| A | Item-wise HMIS report at State level from financial year 2008-09 to 2013-14 | 144 | 2008-09 – 2013-14 | 1 |
| B | Item-wise HMIS report at State level from financial year 2014-15 to 2016-17 | 72 | 2014-15 – 2016-17 | 1 |

Both sit under the same catalog and publisher:

- Catalog: `Item-wise Monthly HMIS Report of All India Across States`
- Publisher: `Ministry of Health and Family Welfare,Department of Health and Family Welfare`

## Why they were selected

**1. Same normalized title base.** Every member is titled
`Item-wise HMIS report at State level for {Month}-{FY}`. Strip the temporal
suffix and both collections collapse to the identical `new_title`: `Item-wise HMIS report at State level`.
The only thing that varies across all 216 datasets is the reporting month and
financial year — the classic signature of a series that was published as one
file per period and should be one table.

**2. Same semantic schema.** Every file is `District, S.No., Parameters, Type`
followed by one wide value column per State. Same indicator rows
(`M1 [Ante Natal Care Services ANC]` …), same `Type` breakdown, same units.

**3. The header delta is one known event.** A has 42 columns, B has 43.
The difference is entirely:

- only in A: `State - Andhra Pradesh Old`
- only in B: `State - Andhra Pradesh`, `State - Telangana`

That is the June-2014 bifurcation of Andhra Pradesh into Andhra Pradesh and
Telangana. Every other column matches exactly. The header change is *why* the
series was split into two collections in the first place, and it is a change in
the world, not a change in what the dataset measures — so the two collections
belong in one merged table.

**4. The DB already classifies them the same way.**

- `merge_method` = `curate` for both
- `merge_add_columns` = `financial year, month` for both

`curate`, not `direct`: the temporal axis lives in the *title* and the
geographic axis lives in *column names*, so there is no standalone temporal
column to merge on. This pair is deliberately outside the exact-header rule in
`dataset_vertical_merge_exact.py`, which excludes wide-form groups. Merging it
requires adding the dimensions that `merge_add_columns` names — which is
exactly what the merge below does.

## Which siblings the rule rejects

The naming family `Item-wise HMIS report at State level from financial year…` has 3 collections in the DB,
of which the rule selects 2. Showing the rejections matters: a selection rule
that only ever says yes is not a selection rule.

| Collection | Datasets | `new_title` | Selected? |
|---|---|---|---|
| Item-wise HMIS report at State level from financial year 2008-09 to 2013-14 | 144 | `Item-wise HMIS report at State level` | **yes** |
| Item-wise HMIS report at State level from financial year 2014-15 to 2016-17 | 72 | `Item-wise HMIS report at State level` | **yes** |
| Item-wise HMIS report at State level from financial year 2017-18 to 2019-20 | 72 | `Item-wise HMIS report at State leve from financial year 2017-18 to 2019-20` | no |

**Rejected: Item-wise HMIS report at State level from financial year 2017-18 to 2019-20**

- Its `new_title` is `Item-wise HMIS report at State leve from financial year 2017-18 to 2019-20` — it does *not* collapse to the shared
  base `Item-wise HMIS report at State level`, so criterion 1 already fails.
- Its header opens with `Indicator`, `S.No.`, `Parameters`, `Type`, `State  All India  Total AB or CD`, `State  All India  Public A`, `State  All India  Private B` … — the first column is renamed and every
  State is split into five sub-columns (Total AB or CD / Public A / Private B /
  Urban C / Rural D). That is a change to *what is measured and at what
  breakdown*, not a change to the map. Stacking it onto A and B would put
  incomparable numbers in the same table.

This is the discriminating contrast that makes the example worth reading: the
A↔B delta is three columns caused by a state boundary moving, so they merge;
the A↔C delta is a different measurement breakdown, so it does not.

## What the merge did

Row-wise union of all 216 source files with these columns prepended:

| Column | Source |
|---|---|
| `Financial_Year` | dimension named by `merge_add_columns`, from the dataset title |
| `Month` | dimension named by `merge_add_columns`, from the dataset title |
| `Report_Basis` | `monthly` / `cumulative`, from the dataset title — see below |
| `source_collection` | provenance |
| `source_title` | provenance |
| `source_uuid` | provenance — the filename in `data/first_batch_downloads/` |

The data columns are an order-preserving union, so
`State - Andhra Pradesh Old`, `State - Andhra Pradesh` and `State - Telangana`
all coexist and are left blank in the years where the source file did not carry
them. Nothing is dropped, renamed, or retyped: values are read and written as
text so the literal `NA` token and large integer counts survive the round-trip.

Result: **97,920 rows x 50 columns** (44 data + 6 added).

### `merge_add_columns` names two dimensions; the data needs three

Both collections interleave two report bases, visible only in the title:

- `Item-wise HMIS report at State level **for** April-2008-09` — that month alone
- `Item-wise HMIS report at State level **upto** April-2008-09` — cumulative from
  the start of the financial year

Each (collection, financial year, month) has exactly **2** datasets, one of each
basis. So merging on `financial year, month` alone — the two dimensions
`merge_add_columns` records — would produce two rows per indicator per month that
nothing in the table distinguishes, silently mixing monthly and cumulative
figures in the same column. `Report_Basis` (`monthly` / `cumulative`) is derived
from the title to keep them apart, and the verification below asserts that the
added dimensions now identify a source dataset uniquely.

Worth feeding back: for this family `merge_add_columns` is under-specified.

## Verification

| Check | Result |
|---|---|
| all 216 source files read | PASS (216) |
| file rows == DB row_count (216/216 covered) | PASS (0 mismatched) |
| merged rows == sum of file rows | PASS (97920 vs 97920) |
| added dimensions present on every dataset | PASS (0 blank) |
| added dimensions identify a dataset uniquely | PASS (0 colliding keys) |
| Report_Basis labelled the right way round | PASS (Dec 2008-09 cumulative 19,389,794 > monthly 2,157,344) |
| columns == added dims + union of source columns | PASS (50) |

The row-count check compares each file's actual length against the `row_count`
already recorded in `dublin_core_metadata` — an independent number, so it can
genuinely fail on a truncated download or a stale DB row. (Comparing the merged
length to the sum of the frames just concatenated would always pass and prove
nothing.)

### Rows per financial year

| Collection | Financial year | Datasets | Rows |
|---|---|---|---|
| A | 2008-09 | 24 | 10,848 |
| A | 2009-10 | 24 | 10,848 |
| A | 2010-11 | 24 | 10,848 |
| A | 2011-12 | 24 | 10,848 |
| A | 2012-13 | 24 | 10,848 |
| A | 2013-14 | 24 | 10,848 |
| B | 2014-15 | 24 | 10,848 |
| B | 2015-16 | 24 | 10,992 |
| B | 2016-17 | 24 | 10,992 |

## Observations worth carrying forward

- The first column is named `District` but holds the indicator group
  (`M1 [Ante Natal Care Services ANC]`). That is a source mislabel; it is left
  as-is here rather than silently renamed.
- `Conforms To` in the DB is normalized (`State  A  N Islands`) while the raw
  files keep the original punctuation (`State - A & N Islands`). Header
  comparisons for selection must be raw-to-raw, or the punctuation stripping
  manufactures mismatches.
- A further optional step would unpivot the 40 `State - *`
  columns into a single `State` column, giving fully long-form
  `(Financial_Year, Month, Report_Basis, State, Indicator, Value)`. Doing that
  would also collapse `Andhra Pradesh Old` / `Andhra Pradesh` + `Telangana` into a
  question about pre/post-2014 comparability. That is a reshape of the
  data; the merge above is not.

## Reproduce

```bash
python transformation/merge_hmis_itemwise_example.py
```

| Output | Contents |
|---|---|
| `data/hmis_itemwise_state_level_merged.csv` | the merged table |
| `data/hmis_itemwise_state_level_manifest.csv` | one row per source dataset: FY, month, header variant, row count |
| `data/hmis_itemwise_state_level_headers.csv` | raw header signature of each source file |
| `data/hmis_itemwise_state_level_merge_notes.md` | this note |
