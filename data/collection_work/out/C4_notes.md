# Batch C4 Decision Notes

## Summary
13 collections, 1,182 rows (members). All are Census of India workers tables by state/district/caste/tribe for three census rounds (1991/2001/2011).

## Key Decisions

### Industrial Category Splits (Rule 5)
Collections **C1, C4, C5, C6, C7, C8** are each split into TWO collections by census year, because industrial categories changed fundamentally across rounds:
- **1991**: NIC-1987 with categories I-IX
- **2001**: NIC-1998 with letter categories (A-L, A-Q depending on table)
- **2011**: NIC-2008 with letter categories (A-U, etc.)

These are not minor header edits — the underlying industrial classifications are different economic taxonomies. For example, "Industrial Category D" in 2001 encompasses different industries than "D" in 2011. Every split collection gets its own entry with year in the collection name.

### Reconcilable Multi-Year Merges (Rule 1)
Collections **C10 and C12** merge across 2001 and 2011 despite year span because their defining columns do NOT change:
- C10: Main Activity categories (Students, Household Duties, Dependents, Pensioners, etc.) are identical 2001-2011. Header match = 0.96.
- C12: Class of Worker categories (Employer, Employee, Single Worker, Family Worker) are identical 2001-2011. Header match = 0.95.

Both add `year` to mac since year varies but is not a column.

### Single-Year Collections
Collections **C2, C3, C9, C11** are single-year datasets (2011, 1991, 2011, 2011 respectively). They merge within themselves. Collection names do NOT include "from/to" range.

### Columns Already Present
State is present as a column in all collections. District is present in most. Caste and Tribe are columns in C5-C8 (for Scheduled Caste/Tribe subsets). None of these need to be added to mac.

### Header Variants
- **C6** has multiple 2011 header variants (H2, H3, H4) reflecting different states and administrative groupings, but all reconcile as one 2011 collection.
- **C13** has no 2001 headers extracted from the pack, but the occupation classification structure (NCO codes) appears stable between years, so merge proceeds.

## Collection Naming
- Removed state/district-specific parts from names (generalized "Female Workers..." from state-specific versions).
- Kept distinguishing features: "for Scheduled Castes/Tribes" where applicable.
- Year suffix only for single-year or split-by-year collections; "from/to" span only for true multi-year merges (C10, C12, C13).

## Confidence
All decisions are **high confidence**. The industrial category splits (C1, C4, C5, C6, C7, C8) are anchored to user's rule 5 and the task brief's explicit warning about NIC version changes. The multi-year merges (C10, C12) have header reconciliation >=0.95. Single-year collections are trivial.
