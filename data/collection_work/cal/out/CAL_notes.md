# Notes on batch CAL

## Rule 7 look-alikes (flagged low confidence in the CSV)

Three of this batch's nine collections match the *description* of sets the brief says the
user already decided non-mergeable "without a stated reason" and locked:

- **C2** "All India level Disposal of Crime under Local and Special Laws by Police (schema 1)"
  (1972-1977) = "Disposal of Crime under L&SL 1972-77".
- **C9** "All India level Juveniles Apprehended by Age Group (schema 2)" (1978,79,80,81,83)
  = "Juvenile by Age Group and Sex 1978-83".
- **C1** "...Female Inmates in the Country and Percentage Share at the end" (1998-2000)
  = "Inmates and Percentage Share 1998-2000".

I checked `table_index.tsv`: all of these nids carry status `batch CAL` (not `LOCKED` /
`decided in batch ...`), so they are genuinely ours to decide, not the actual locked rows.
Per the brief's instruction for look-alikes, I decided each purely by rules 1-6 (all three
came out mergeable/splittable, not non-mergeable) but marked them **low** confidence and
named the resemblance in the rationale, so you can sanity-check against whatever reason you
had for the original calls. Worth a second look, especially C2 - see the header-schema
finding below.

## C2: schema change found mid-series

File-checked 1972 (core) against the 1987 free row. The header is stable across 1972-1977
(one consistent 6-column schema) but by 1987 it splits "cases investigated" into two extra
outcome columns. Because of that, I did **not** pull the free "...by Police" collection
(1978-1982) or the individual free 1983-1987 rows into C2's merge, even though they're the
same series by title and status=free. If you know the schema break happened later than 1978
(or not at all until 1987), the range 1972-1987 (or 1972-1982) could still be merged as one
collection - I just didn't have header evidence for 1978-1986 to confirm it.

## C3/C4 (Accidental Deaths / Suicides): large merges built from many free outside rows

Both became big collections (Accidental Deaths 1964-1991, Suicides 1966-1991) by pulling in
many `free` rows outside the pack via rule 6 - grepped from `table_index.tsv`, not just the
examples the pack listed. I file-checked several overlap joints in each and the year-over-year
figures repeat almost exactly (this matches the brief's own NCRB Accidental Deaths/Suicides
merge precedent). Two things worth flagging:

- **1967 Accidental Deaths discrepancy**: the 1964-72 edition (nid 2952801) reports 123672
  deaths for 1967; the 1967-74 edition (2950821) and a 1966-67 comparative snapshot (2957781,
  now folded in as `to be removed`, redundant) both report 126762. I went with the
  majority figure (126762) in the Remark instead of blocking the merge.
- **Deliberately NOT pulled in**: "All India level Incidence and Rate of Accidental Deaths"
  (curate, free) and "All India level Incidence and Rate of Suicides" (change_in_header,
  free), plus the "Forces of Nature" (6722426/6748881/6748923) and "Natural/Unnatural"
  (1916641/1310081/1310141) clusters. Their headers break the simple
  Year/Population/Total/Volume shape (cause-categorised columns instead), so I treated them
  as a different measure under rule 5 rather than the same series. Worth a look if you want
  those extended too - I did not open their files.

## C5: gap and an unverified extension

- There's a real coverage gap for 1975-1978 - I could not find any row in `table_index.tsv`
  matching this series for those years.
- The free collection "All India Level Incidence of Accidental Deaths by Causes" (extends
  1979-1988, merge_method already change_in_header) was pulled in at **medium** confidence
  only - the pack didn't show its members' headers and none had a filename I could open, so
  I trusted the title match and its existing change_in_header status rather than verifying
  columns directly.
- A further extension exists but was **not** pulled: nids 2905381, 2906001, 2909861, 2910421,
  2911121, 2912721 (1989-1994), status `curate`, free. No header evidence available in the
  pack; flagging in case you want to fold those in too.

## Data-quality artifact: skip these nids if you see them elsewhere

Several "similar rows outside" listed in the C6/C7/C8/C9 sections carry a header that is
obviously wrong for the series - `Date,Code,CommodityId,CommodityName,DistrictName,
DistrictCode,Stock,CommodityStock,TotalStock` (looks like a mis-linked commodity/stock
file). I excluded these from every pull: **1897801, 1897821, 1898201, 1898241**. 1898201
would otherwise have been the only 1971 candidate for C9's merged series (so that series has
a one-year gap at 1971), and 1898241 would have been the only 1960-1971 candidate feeding
into C8's chain (C8's chain reaches 1960 via 1912881/2010201 instead, so no gap there).

## merge_add_columns

No new tokens were coined - every mac used here is `year`, already in the brief's
vocabulary list. Note the vocabulary's own distinction mattered a lot in this batch: `year`
is a header column (mac blank) for C3, C4 and C8 (each has a literal `Year`/`Years` column),
but is *not* a header column (mac=`year` needed) for C1, C2, C5 and C9, where the year only
appears in the title or is baked into one column's label suffix.

## C1 split (rule 5)

Split the pack's single "Female Inmates" collection into two by subject (Female Inmates vs
Jail/All Inmates), per rule 5's own explicit example. This directly contradicts my own prior
(NOT approved) proposal shown in the pack, which had merged them with an `inmate_group` mac
token - that approach was rejected per the rules, so I did not reuse it.

## Budget

~24 source files opened (under the ~30 cap), concentrated on the rule-3 overlapping-window
collections (C3, C4, C8) and the C2 schema check. C1, C5's core, C6, C7 and C9 were decided
without file opens - rules 1, 4 and 7 don't require them, and the header evidence already in
the pack was sufficient.
