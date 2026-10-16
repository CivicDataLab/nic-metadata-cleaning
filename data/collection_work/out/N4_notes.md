# Notes on batch N4 (NCRB) decisions

## Rule 4 (Year-labelled Columns) Non-Mergeable Decisions

Four collections are non-mergeable due to Rule 4: year columns that differ between members.

- **C2** (Cyber Crimes Incidence): Headers have "IT ACT - 2002, IT ACT - 2003" (2002-03 member) vs "IT Act - 2003, IT Act - 2004" (2003-04 member). The year-labelled columns vary across members (50%+ of header).

- **C7** (Railways Act Incidence) and **C9** (Total IPC Crimes by GRP): Both have overlapping sliding windows (2003-05, 2004-06, 2005-07, etc.) with year-labelled data columns (2003, 2004, 2005, 2006, …) plus percentage variation columns. The data year columns differ between members (71-83% year-labelled), triggering Rule 4 rather than Rule 3 (overlapping windows exception).

- **C16** (Accidental Deaths Variation): Headers contain year values in column names ("Deaths due to Forces of Nature - 2018, Deaths due to Forces of Nature - 2019" for 2018-19 member vs "Deaths due to Forces of Nature 2021, ..." for 2021-22 member). Year values differ between members across different year pairs.

## Multi-Collection Splits (Rule 5: Different Measures)

Two collections are split by law type per Rule 5:

- **C6** (Disposal of Persons Arrested): Split into four collections
  - IPC crimes only (G715)
  - SLL crimes only (G716)
  - Cyber crime cases (G717, G720)
  - IPC and SLL combined (G718, G721)
  
  The three law types (IPC, SLL, Cyber) are different subjects and belong in separate collections.

- **C12** (Juveniles Apprehended): Split into two collections
  - IPC crimes (G732, G734: 2001-2003)
  - SLL crimes (G733, G735: 2001-2003)
  
  These are different law categories and belong in separate collections.

## Structural Notes

- **C10 vs C11** (Police Housing): Two separate schema versions in the same batch covering different years. C10 covers 2001-2005 (original ranking groups: "For Officers", "Upper Subordinates", "Lower Subordinates"). C11 covers 2006-2010 (modified ranking: "Officers Dy.SP Above", "Upper Subordinates ASI to Inspectors", "Lower Subordinates Constables Head Constables Class IV Subordinate Staff"). These merit separate collections due to the structural change.

- **C8** (IPC Crimes by GRP): Headers H1 and H2 have very low surface match (0.21) but are reconcilable—H2 adds IPC section numbers (e.g., "Murder Sec 302 303 IPC") to the same columns as H1 (e.g., "Murder"). These formatting differences fall within Rule 1 (reconcilable headers).

## All Collections Verified

Every member of C1-C17 appears exactly once in the output CSV. No "LOCKED" or "decided in batch" rows are claimed. All decisions follow the user's confirmed rules.
