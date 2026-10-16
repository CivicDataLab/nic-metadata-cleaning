# Batch N1 Decision Notes

## Rule 5 (Different Subject) Applications

Multiple collections required rule 5 splits because they mixed different legal categories or victim groups:

- **C1**: Female Inmates vs. All Inmates - separate collections by inmate_group dimension
- **C4**: IPC vs. LSL (Local & Special Laws) - three separate collections by law type
- **C14**: Scheduled Castes vs. Scheduled Tribes - two separate collections by victim_group  
- **C18**: Children vs. Women - two separate collections by victim_group

These splits were prioritized before rule 3 (overlapping windows) was applied. All follow the pattern established in the examples (e.g., inmates example shows female and all-inmates as separate collections).

## Rule 3 (Overlapping Windows) Applications

Collections C2, C3, C6, and C7 have overlapping sliding windows with continuous year-per-row data:

- **C2**: 18 members spanning 1960-1987 with extensive overlaps. Includes nested editions (e.g., 1960-1969 inside 1960-1970). All merged per rule 3 exception.
- **C3**: 6 members spanning 1963-1973 with overlaps and nested pairs. Merged with full span.
- **C6**: 6 members spanning 1969-1986 with overlaps and nested pairs. Merged with full span.
- **C7**: 7 members spanning 1972-1983 (plus outside rows spanning 1968-1971). In-collection merged with full span; outside rows handled separately by rule 6.

All four collections have **Year as a row column** (header includes "Year" or "Years"), so mac=blank per the stated rule: "A token belongs in mac only if... not already a header column."

## Rule 4 (Years in Column Names) Application

**C10 (Juvenile Delinquency LSL)** is the only non-mergeable collection:

- Header variant shows 60% year-labelled columns
- Column names include years: "Number of Cases Reported During 1990", "Percentage change in 1991 Over 1990"
- Overlapping windows exist (1987-1992 period) but year-columns prevent merge per rule 4
- This is analogous to the crime_wide example in the guidance

## mac Tokens: "year" vs. blank

Careful distinction maintained:
- **mac=year** when Year is **only in titles** (e.g., "Single years 1988-1993" in titles, but Year is not a data column): C1, C4, C5, C8-C9, C11-C13, C15-C18
- **mac=blank** when Year is **a row column** in the data (header includes "Year" or "Years"): C2, C3, C6, C7

This follows the rule: "A token belongs in mac only if the dimension varies across members AND is not already a header column."

## Collection Naming

All collection names follow the guidance:
- Pinned airline/city/law type names replaced with generic "Various", "in the Country", "States/UTs", or "Metropolitan Cities" where applicable
- Edition tails dropped ("at the end of", "during", "as on 31st December", etc.)
- Span included with "from <first> to <last>" format where members span multiple years/editions
- Fiscal year format (YYYY-YY) would apply to fiscal series if present, but N1 contains calendar years only

## Cross-Batch References

No LOCKED rows or rows marked "decided in batch X - do not claim" were encountered in N1. Rule 6 (pull in same series from outside) was not applicable as all similar outside rows were marked "non-mergeable" or belonged to different collection types.
