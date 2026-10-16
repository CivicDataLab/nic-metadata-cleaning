# Batch N3 Collection Decisions - Notes

## Summary
Batch N3 (18 collections, 135 members) contains NCRB crime statistics, mostly single-year datasets spanning 1966-2010. All decisions follow rules 1-6 with high confidence where data structures are consistent.

## Key Decision Points

### C4-C5 Merged
C4 (schema 1, 1988-93) and C5 (schema 2, 1966-71) merged into one collection spanning 1966-1993. Same series (Comparative Statement of Incidence of Suicides) with reconcilable headers despite different years in column labels ("Incidence 1988" vs "Number of Suicides 1966"). Rule 1 confirms this merge. Both are change_in_header collections with 1-2 year-labelled columns (rule 4 exception).

### C7 Split into 3 Separate Collections
Original collection C7 contained three distinct accident types:
1. Other Railway Accidents (G660: nids 1914001, 1310521)
2. Rail-Road Accidents (G661: nids 1913981, 1310501)
3. Road Accidents (G662: nids 1913961, 1310481)

Split per rule 5 (different subject/measure) into three separate change_in_header collections, each covering 1999-2000.

### C9 Non-Mergeable (Rule 4)
C9 contains 6 members with 82% year-labelled columns (Quinquennial Average + percentage changes over QA and previous year). Overlapping sliding windows (1996-2001 through 2003-2008) with different year sets in columns → non-mergeable per rule 4. Wide table format prevents merging despite consistent structure.

### C14 Split into 2 Collections (Rule 5)
Original collection C14 contained two distinct crime offences:
1. Dacoity (G684, G686, G688: nids for 1982-1986)
2. Robbery (G685, G687, G689: nids for 1984-1986)

Split per rule 5 into separate collections, each with year and value columns for property stolen by place.

### C11 vs C12 - Both Kept Separate (Rule 5)
C11: "Juveniles Apprehended by Sex for Committing Crimes under Local and Special Laws" (16 members, 1972-1987)
C12: "Juveniles Apprehended by Sex for Committing Crime under IPC" (16 members, 1972-1987)

Different legal provisions (Local & Special Laws vs IPC) keep these as separate collections despite identical structure and overlapping years. Rule 5 applies.

## MAC Tokens Used
- `year`: All change_in_header collections except those split by type (mac list below)
  - Single-year datasets where year appears only in titles, not in header columns
  - Examples: C1, C2, C3, C6, C8, C10, C11-C13, C15-C18

For split collections (C7, C14), `year` is still the only varying dimension - accident type and offence type are NOT set as mac because they differentiate separate collections (rule 5), not variants within a collection.

## Remarks
- C4-C5, C8: "Year in the header can be changed to previous year or last year" - 50% year-labelled columns exception (only 1-2 columns per row, rule 4 exception)
- All others: Blank (no special header edits needed after reconciling)

## Similar/Outside Rows (Rule 6)
All collections note free-status similar rows outside the collections (e.g., 2017 versions of C1, 2015+ versions of C2). None marked LOCKED or "do not claim", so no rule 6 pull-ins were made. Batch N3 appears internally consistent without need to claim cross-batch rows.

## Confidence Assessment
All decisions are **high confidence**:
- Rule 1: All reconcilable headers verified through H1/H2 variants
- Rule 4: Year-labelling percentages match classification (0% or 50% exception)
- Rules 2-3: No nested/overlapping editions within collections (except C9 non-mergeable by rule 4)
- Rule 5: Separate offences/accident types correctly split
- Single-year structure consistent across most collections → straightforward mac=year application

No low-confidence look-alike calls detected.

## Output Coverage
- **Total collections: 18 (C1-C18)**
  - Merged: 2 (C4+C5 = 1 output row each)
  - Split: 5 (C7 into 3, C14 into 2 = 5 output rows total)
  - Standalone: 11 (C1-C3, C6, C8-C13, C15-C18)
- **Total output rows: 20** (18 collections + 1 merged pair + 1 split extra)
- **Total members: 135** (all accounted for exactly once)
