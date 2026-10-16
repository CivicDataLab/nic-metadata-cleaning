# Collection decisions: C1 (Census of India, 1991)

## Summary

All 14 collections decided as **change_in_header**, merged fully with all member groups (H1 and H2).

**Total members across all collections:** 6,202 rows
**Total decision rows in output:** 14 (one per collection)
**Common characteristics:**
- All 1991 Census of India data (single year)
- All from Ministry of Home Affairs / Registrar General
- No nested editions or overlapping windows
- No year-labelled columns (0% across all variants)
- State and District both present as columns

## Admin level handling (district vs state)

Each collection has two administrative levels:
- **H1 (district-level):** ~420–425 members with "District Name" column
- **H2 (state-level):** ~25–26 members without "District Name" column

**Decision:** Merge all district and state files together per Rule 1 (reconcilable headers).

The prior proposal to split was based on different admin levels, but Rule 1 clearly applies: headers reconcile perfectly (1.0 match score), differing only in District Name column presence. This is a reconcilable difference, not a fundamental column change. State and District are both header columns, not varying dimensions, so no merge_add_columns tokens needed.

## SC vs ST separation

Five collections have SC/ST pairs kept separate (as different subjects per Rule 5):

| SC Collection | ST Collection | Reason |
|---|---|---|
| C1: Fertility | C2: Fertility | Different key columns: Caste Category vs Tribe Category |
| C4: Children Born | C7: Children Born | Caste vs Tribe categories differ |
| C5: Surviving Children | C6: Surviving Children | Caste vs Tribe categories differ |
| C8: Age at Marriage | C9: Age at Marriage | Caste vs Tribe categories differ |
| C13: School Attendance | C14: School Attendance | Caste vs Tribe categories differ |

Collections C3 (SC distribution), C10–C12 (ST religion/mother tongue) have no SC/ST pair in this batch.

## Confidence notes

All decisions are **high confidence** based on clear Rule 1 application. All headers reconcile perfectly (match scores ≥0.90). No ambiguity in grouping.

No merge_add_columns tokens needed: State and District are already columns in the data structure.

## No cross-collection claims

All similar rows listed in the pack's "Similar rows outside this collection" were either:
- Already assigned to C1/C2 collections in scope (cross-references between SC and ST pairs)
- Not downloaded (file status N/A for decision)

No rows from other batches or collections needed to be claimed.
