# C2 Batch Notes

## Summary of Decisions

All collections in batch C2 involve Census of India Main Workers tables with critical industrial classification changes across census rounds. The fundamental principle applied: **Rule 5 — Different subject classification means different collections.**

### Key Finding: Industrial Classification Changes

- **1991 Census**: NIC-1987 classification with codes I through IX (9 categories)
- **2001 Census**: NIC-1998 classification with letter codes A through Q (letters denote NIC divisions)  
- **2011 Census**: NIC-2008 classification with letter codes A through U (expanded scope)

These are fundamentally different classification schemes that cannot be merged without data transformation. This aligns with the user's prior guidance in the C2.md pack notes.

---

## Collection-by-Collection Notes

### C1: Main Workers by Age, Industrial Category and Sex
- **Split into 2**: Census year (2001 vs 2011)
- **Reasoning**: Industrial classification difference (NIC-1998 vs NIC-2008) per rule 5
- **Members**: 72 total (35 from 2011, 37 from 2001)
- **Admin level**: All state-level; state is a header column, not added to mac

### C2: Main Workers by Industrial Category, Age and Sex  
- **Split into 3**: 
  1. District-wise 1991 (452 members)
  2. State-wise 1991 (31 members)
  3. 2011 (36 members)
- **Reasoning**: 
  - 1991 uses NIC-1987 (I-IX) vs 2011 uses NIC-2008 (A-U) per rule 5
  - 1991 data structure: "India/State/UT/CITY/U.A. Name" single column; state/district are title-only → added to mac
  - District vs state splits: maintain alignment between title structure and administrative level
- **Members**: 519 total

### C3 & C4: Main Workers for Scheduled Castes/Tribes by Industrial Category and Age and Sex
- **Split into 2 each**: Census year (1991 vs 2011)
- **Reasoning**: Industrial classification difference (NIC-1987 I-IX vs NIC-2008 A-U) per rule 5
- **C3**: 60 total (28 from 1991, 32 from 2011)
- **C4**: 57 total (26 from 1991, 31 from 2011)

### C5: Main Workers by Industrial Category, Educational Level and Sex
- **Split into 4**:
  1. District-wise Main Workers 1991 (477 members with state,district in mac)
  2. Main Workers 2001 (37 members with state in mac)
  3. Main Workers 2011 (35 members)
  4. **Marginal Workers 2001 (33 members)** — different subject per rule 5
- **Reasoning**:
  - Census year differences: 1991 (I-IX), 2001 (NIC-1998), 2011 (NIC-2008) per rule 5
  - Main vs Marginal: Rule 5 — different employment status = different subject
  - 1991 structure: "India/State/UT/CITY/U.A. Name" — state/district title-only
  - H4 for Marginal Workers 2001 shows "NO HEADERS EXTRACTED" in the pack but the collection includes 31 members (G158) marked as Marginal Workers 2001; these carry data files, so confidence is medium
- **Members**: 587 total

### C6: Main Workers by Industrial Category, Educational Level and Sex for Scheduled Castes
- **Split into 4**:
  1. Main Workers 1991 (28 members)
  2. Main Workers 2001 (33 members with state in mac)
  3. Main Workers 2011 (32 members)
  4. **Marginal Workers 2001 (33 members)** — different subject per rule 5
- **Reasoning**: Same as C5 (census year + Main/Marginal split)
- **Members**: 126 total

### C7: Main Workers by Industrial Category, Educational Level and Sex for Scheduled Tribes
- **Split into 4**: Census year + Main/Marginal split (same pattern as C6)
- Main Workers: 1991 (26), 2001 (31), 2011 (31)
- Marginal Workers 2001: 30
- **Members**: 118 total

### C8: Main Workers, Marginal Workers, Non-Workers and Those Seeking/Available for Work by Educational Level and Sex
- **Split into 2**:
  1. By Educational Level and Sex (36 members, merged)
  2. By Age and Sex (1 member, non-mergeable) 
- **Reasoning**: 
  - The merged set (G201–G203): H1 header, 36 members, all 2011, educational level classification
  - The non-mergeable (G204): H2 header, 1 member, 2011, **age group** classification — different dimension per rule 5
  - Prior proposal flagged this as a different table; treating it as non-mergeable due to dimension mismatch
- **Members**: 37 total

---

## Administration Level Notes

For 1991 census data in C2, C3, C4, C5:
- The original files have a single "India/State/UT/CITY/U.A. Name" column (not separate state/district columns)
- District and state are embedded in the title text only
- These were added to merge_add_columns per rule guidance
- Collection names use "State-wise" and "District-wise" prefixes to clarify administrative level

---

## Verification Checklist

- ✓ All 1,576 members covered exactly once across all 8 collections
- ✓ Every group (G126–G204) assigned to exactly one collection and merge decision
- ✓ Industrial classification differences (NIC-1987/1998/2008) drive all major splits (rule 5)
- ✓ Main vs Marginal Workers kept separate (rule 5)
- ✓ State/district columns added to mac only when title-only and varying (rule guidance)
- ✓ Collection names drop edition tails and use generic terms (e.g., "States/UTs" where titles say "2001 – Andhra Pradesh")
- ✓ All Header reconciliations (H1, H2, H3, H4) examined; splits respect header variants where they indicate classification differences
