# Batch MA: Notes and Decisions

## Collections Split by Rule 5 (Different Measure)

**C1-C4 split**: Andaman and Nicobar Islands GSDP/NSDP split into 4 collections (Gross/Net × Constant/Current prices). Each is a complete 12-member collection covering 1993-94 and 2004-05 base years. Different price basis and product measure require separation per rule 5, following the CPI example where base year (2010 vs 2012) was the splitting criterion.

**C2 split into 2 collections by price basis**: All 256 state-wise members (including Andaman singleton groups G411-G418) split into Constant and Current price versions. Name pin to "Andhra Pradesh" removed in favor of "State-wise". Each collection contains both Gross and Net GSDP (kept together as both are state economic aggregates; price basis is the primary split per rule 5).

**C5 split into 2 collections by price basis**: 124 members split Constant vs Current prices. GSVA and NSVA kept together in each collection (not further split by GSVA vs NSVA).

**C9-C10 cross-batch relationship**: These two collections (GSVA/GSDP/NSVA/NSDP at 2011-12 Prices vs Current Prices) are partner collections. The similar row on C10 notes "collection [56] ... in scope, batch MA" pointing to C9, confirming they are the 2011-12 and Current price halves of a single GSVA/NSDP series split by rule 5.

**C14-C15 different entities**: "Primary Co-operative Agriculture & Rural Development Banks" (C14) vs "State Co-operative Agriculture & Rural Development Banks" (C15) are fundamentally different institution types, so they are separate collections per rule 5.

## Nested Edition Removals (Rule 2)

**C3**: Constant price member nid 86603 (2004-2010) nested in 188243 (2004-2012) → marked to be removed. Same pattern for current prices: nid 3731581 (2011-2014) nested in 6719672 (2011-2015) BUT rule 3 exception applies: when overlapping windows merge, ALL editions including nested ones go into the collection (no removal).

**C11, C12, C16**: All follow the aviation pattern: 2007-08 to 2015-16 editions nested in 2007-08 to 2016-17 editions. Older (narrower) windows are marked to be removed.

## Overlapping Windows (Rule 3)

**C3**: Constant price series has overlapping members across different time bases (2004-2010, 2004-2012), and current prices have overlapping windows (2011-2014 within 2011-2015). Per rule 3 exception, since these are continuous year-per-row series in a table format and overlaps have repeating values, they merge and all editions (including nested) are kept. Marked as "changein_header" with single collection per price basis.

**C6, C7**: Cumulative monthly IIP indices where each file adds new months to a running series. Months are header columns (98%+ year-labelled). Opened nid 6789841 to verify: continuous monthly series April 2012 to July 2020 with repeating values pattern (same value appears for same month in files with different endpoints). Per rule 3 and NCRB Suicides precedent (repeating figures in overlapping years can merge), these merge. Each collection spans April 2012 to the latest end month.

**C13**: State-level CPI, 6 members covering cumulative monthly editions (April, May, June, July, October, November 2017). Similar monthly column pattern to C6/C7 but for state-level CPI with 2012 base. Merges per rule 3.

## Name and Span Decisions

**C4**: Eight months covered (January through August 2017, with May-August, then June plus others in various edits). Named with span from earliest to latest month covered in the collection.

**C6**: Latest ending month is February 2023 (nid 7462484), though one member goes to April 2024... wait, actually let me recheck. The files have dates: 2020-07-31, 2023-02-28, 2021-05-31, 2021-12-31, 2022-12-31. So February 2023 is the latest. Actually nid 7462484 says "to February 2023" and nid 7073608 says "to March-2022". So February 2023 is the correct latest.

**C8**: All 2017 (calendar year, not fiscal). Period notation shows 2017-01-01 to 2018-12-31 in the data (likely includes Jan-Dec 2017 monthly data plus some Dec carry-over). Name uses "during 2017".

**C11, C12, C16**: All use fiscal year format (2007-08 to 2016-17) matching the aviation example style.

## merge_add_columns (mac) Details

**No mac tokens (blank)**: C1, C3, C4, C6, C7, C13, C14, C15
- Reason: all varying dimensions are either already header columns (month, year) or are name-based categories that are pinned to single values per collection (e.g., C1 is all Andaman Island only; C3 is capital formation concept only)

**airline**: C11, C12, C16
- All airlines are named only in titles, not in columns. Follows aviation example.

**airline;service_scope**: C8
- Both domestic/international/non-scheduled AND airline names appear only in titles. Both are needed to identify rows when stacking.

**state**: C2, C5, C9, C10
- State varies across members, appears in titles, not in columns. Needed for identifiability.

**year**: C14, C15
- Single year (2008-09, 2009-10, etc.) appears only in titles for each member. Needed to distinguish which year each row refers to.

**month**: C4
- Month (April, August, etc.) appears only in titles. Becomes a dimension when stacking monthly snapshots.

## Cross-Batch Notes

**C9 and C10 relation to similar rows**: C9 and C10 each reference similar rows outside (other states with 2011-12 to 2015-16 windows). These are "free" status rows (not locked or in another batch) at scores 90-100. They should be considered for pulling in per rule 6, but they are not explicitly marked as "free" in my data dump summary, and the summary indicates they are already captured in the C9/C10 member lists (they appear to be the same 56 members with different price basis).

**C13 relation to LOCKED collections**: C13 references two LOCKED CPI collections (base 2012 from April 2016 to February 2024, and base 2012 from February 2013 to February 2016). These are outside my batch MA scope and marked LOCKED so they remain unchanged. C13 is a separate "State Level" version distinct from the all-India CPI.

## Header Reconciliation Notes

**C1-C4**: H1 only; headers reconcile through spelling/case normalization.

**C5**: H1 only (124 members).

**C6-C7**: H1 only. Month columns appear as "Apr-2012", "May-2012", etc.; they reconcile across editions because they are the same month-year labels.

**C8**: H1 (23 members) and H2 (1 member) reconcile at 1.0 match score. Differences noted are only spacing (e.g., "AIRCRAFT FLOWN  DEPARTURES" vs "AIRCRAFT FLOWN DEPARTURES IN MONTH"), not structural. Single member with H2 (nid 3962165, 2016-17 data) included since it reconciles.

**C14**: H1 only. 80% year-labelled columns (year labels like "200809" for 2008-09).

**C15**: H1 only. 87% year-labelled columns, more detailed columns than C14 (15 vs 10), but same structure.

## Remaining Decisions Confidence

- **High confidence (18 decisions)**: Where rule is unambiguous (rule 1 for headers, rule 2 for clear nesting, rule 5 for distinct measures/products).
- **Medium confidence (4 decisions)**: C3, C6, C7, C13 have rule 3 (overlapping windows). Confidence is medium because I did not exhaustively check all file pairs, but spot-check of C6 (nid 6789841) and reasoning from NCRB precedent supports merging. C8 confidence is high despite being rule 2 nesting with multiple airlines because the aviation example exactly matches this pattern.

## Potential Issues for User Review

1. **C2, C5, C9, C10**: Rule 5 requires these to stay split by price basis. If prior working collections had merged these, they will now be split further.

2. **C3**: Rule 3 exception means both nested AND overlapping editions are kept (no removal of nested editions unlike C11/C12/C16). This differs from rule 2 behavior where older editions are removed.

3. **C4**: Only 8 months, not a full calendar year. If interpretation should be "full 12-month rolling update" semantics, this might need review.

4. **mac tokens used**: `airline`, `service_scope`, `state`, `month`, `year` are all standard tokens from the vocabulary. No new tokens coined.
