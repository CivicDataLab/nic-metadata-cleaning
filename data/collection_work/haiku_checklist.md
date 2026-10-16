# Mandatory checklist (reviewers found these mistakes in earlier batches — do not repeat them)

1. **Look at "year-labelled cols N%" on every header variant.** If N ≥ 50% AND members cover
   different windows/years, the table has years in its columns → rule 4 → `non-mergeable`.
   Example seen: "States/UTs | 2003 | 2004 | … | 2016" (93%) — that is NOT mergeable.
   Exception: exactly one or two year-labelled columns (e.g. "Newly registered 2002-03",
   "Total registered as on 31.3.2003") → merge, with Remark
   "Year in the header can be changed to previous year or last year".
2. **Nested editions of a wide table** ("during 2008-12", "during 2008-14", "during 2008-16" — note
   the pack's window parser may show these as a single year like 2008; read the TITLE):
   the widest edition → `non-mergeable` (standalone), every older edition it contains →
   `to be removed`.
3. **Rule 3 merges need evidence.** Only merge overlapping windows after opening ≥2 files and
   counting rows: a "1965 to 1975" file must contain every year 1965…1975. Write the counts in
   the rationale. No file check → `non-mergeable`. Rule 3 merges are never `high`.
4. **Different measures are different collections** (killed vs injured, IPC vs LSL, SC vs ST
   when key columns differ, constant vs current prices).
5. **CSV quoting:** wrap every field that contains a comma in double quotes — especially
   merge_add_columns like "year,state" and every rationale. Use commas (not semicolons)
   between tokens and between group ids.
6. `high` only when a rule applies clearly AND you checked the evidence; otherwise `medium`.
