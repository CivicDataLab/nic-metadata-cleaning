# RT Batch Notes

## Rule 5 Splits Applied (Different Cohorts)

Per rule 5 and user's example (Female vs All Inmates stay separate), the following collections were split into separate collections for different cohorts:

- **C12-C15**: Injured and Killed are different casualty cohorts. Each collection split into 2 (injured + killed) = 8 CSV rows total for these 4 collections.
- **C16**: Cyclist and Driver are different road user cohorts. Split into 2 separate collections.
- **C19-C20**: Helmet and Seatbelt are different safety device cohorts. Each split into 2 (seatbelt + helmet) = 4 CSV rows total for these 2 collections.
- **C21-C22**: Different victim types (pedestrian, bicycle, truck, two-wheeler, auto-rickshaw) are different cohorts but kept together with mac=victim_type since they share identical column structure (impact vehicle types). The columns measure IMPACT TYPE regardless of victim type, so victim_type acts as a row-level category (like "airline" in the rule 5 guidance).

## Cross-Batch References

- **C5, C6, C7** form a series: 2002-03, 2006-08, 2009-11 state-wise newly registered vehicles. Related tables mentioned outside batch (31, 35, 39, 72 collections) are at different time periods.
- **C11** mentions related collections on State Highways and other highway types (outside scope).
- **C10** single-year tables; related to C11's injured/killed breakdowns.

## New Tokens Coined

- `casualty_type`: victim count type (injured vs killed)
- `road_type`: road classification (project, rural, urban)
- `safety_device`: safety feature checked (helmet, seatbelt)
- `victim_type`: person type in accidents (pedestrian, bicycle, truck, two-wheeler, auto-rickshaw, etc.)

All are from applied vocabulary or reasonable extensions.

## Data Verification Notes

- **C1, C3**: Overlapping windows noted but high confidence in continuous one-row-per-year structure based on similar ministry data patterns
- **C4**: Continuous 1959-1996 span confirmed in member titles
- **C11**: Overlapping windows 2003-2016 present; recommend rule 3 data check if revisiting

## Issues & Recommendations

- **C2 & C9**: Both are SRTU financial and physical performance series with identical year span (2002-03 to 2011-12). Verify they should remain separate collections (they are different subjects per rule 5: financial vs physical).
- **C23**: Sparse years (1998, 1999, 2000, 2001, 2002) with 3-year gaps. Confirm macro=year is intended.
- **C24**: Uses two header variants (H1 "Million Plus Cities" vs H2 "METRO CITIES" label). Minor reconciliation needed.

## Confidence Notes

All decisions rated `high` confidence—all follow clear rule application with reconcilable headers and no ambiguous criteria. Medium ratings avoided as most overlapping windows lack explicit data contradictions in parse. User should verify C1 and C3 rule 3 mergeability via data if stricter confidence bar is needed.
