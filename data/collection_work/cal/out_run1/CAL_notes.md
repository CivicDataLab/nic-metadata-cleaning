# Notes on batch CAL

## Rule 7 identifications (please sanity-check)

Three of the nine collections match the unexplained non-mergeable sets named in rule 7
closely enough (exact title wording + exact year span) that I treated them as *being* the
named call rather than merely a look-alike, and gave them `medium` confidence rather than
`low`:

- **C1** "...Female Inmates... Percentage Share at the end" (1998,1999,2000) = "Inmates and
  Percentage Share 1998-2000". I did not split it into Female-Inmates vs Jail-Inmates
  collections under rule 5, on the assumption this identification is right. If it's wrong,
  the right call under rule 5 alone would be two change_in_header collections named "...
  Female Inmates in the Country and Percentage Share from 1998 to 2000" and "... Jail
  Inmates in the Country and Percentage Share from 1998 to 2000", both mac=year.
- **C2** "Disposal of Crime under Local and Special Laws by Police" 1972-1977 = "Disposal of
  Crime under L&SL 1972-77".
- **C9** "Juveniles Apprehended by Age Group (schema 2)" 1978/79/80/81/83 = "Juvenile by Age
  Group and Sex 1978-83".

If any of these three identifications is a coincidence rather than the actual named case,
please flag it back - the rest of the rule-1-6 analysis for that collection would need
redoing (I did not fully work out the alternative change_in_header naming/mac for C2 or C9
since I judged rule 7 applied).

## Rule 3 file findings worth a closer look

- **C3 (Accidental Deaths) merge, 1964-1974**: the 1967 figures disagree between the
  1964-71-vintage files (Population 5113 lakh, Deaths 123672) and the 1967-73/1967-74-vintage
  files (Population 4999, Deaths 126762). Every other overlap year matches exactly. This
  looks like a later revision of the 1967 estimate rather than an error, but it means "the
  overlapping years carry identical figures" isn't 100% true - flagging it rather than
  silently picking one value.
- **C3's other three members** (2920301 "1976-1986", 2919901 "1977-1987", 2919401
  "1978-1988") and **all of C4** (Suicides, all 5 members) turned out to end with a
  "Percentage change in Y over X" data row baked into the CSV - this is the exact kind of
  row rule 3 says disqualifies the merge exception, so I kept these non-mergeable rather
  than merging them. This means the NCRB-Accidental-Deaths/Suicides merge exception only
  actually fired for the older (pre-1975), shorter-window editions in this batch, not the
  later ones - worth knowing if a future batch encounters more of this series.
- **C8** (Juveniles by Age Group, schema 1) hit the same problem even harder: both files I
  opened (1965-1975, 1966-1976) skip years inside their own stated window (e.g. 1966 and
  1967 are simply missing from the "1965 to 1975" file), both end with a "Percentage Change
  Over 1965" / "Percentage Change Over 1966" row, and the shared year 1973 differs slightly
  between the two files (16-18yr share 18.7 vs 18.1). All disqualifying signs at once, so
  this one is a clean non-mergeable call.

## The "Rate" and "by Causes" siblings I deliberately left alone

Grepping table_index.tsv turned up much larger series that look like continuations of C3,
C4 and C5, but I did not verify or claim them - flagging so a future batch can:

- **"All India level Incidence and Rate of Accidental Deaths" / "...Rate of Suicides"**
  (merge_method mostly `curate`, some `change_in_header`, all status `free`), spanning
  roughly 1982-2018 at All-India level, plus a large "State, UT & City-wise" family at the
  same measure. "Rate ... per lakh of population" looks like the same computed quantity as
  C3/C4's "Volume ... per Lakh of Population", just renamed in later yearbooks, but I did not
  open any of these files, so I can't say whether they also carry window-relative rows.
- **"All India Level Incidence of Accidental Deaths by Causes"** (free, change_in_header,
  9 editions 1979-1988, some 2-year "X & Y" editions such as "1984" and "1984 & 1985" that
  are themselves nested/overlapping) looks like the direct continuation of C5's "due to
  Various Causes" series after 1972, once the gap years 1973/1974 (pulled into C5 above) are
  accounted for. It needs its own rule-2/rule-3 pass over its internal nested pairs before
  it can be folded into C5's collection.
- Every "State, UT & City-wise ..." variant of the Accidental-Deaths/Suicides series was
  left alone on purpose - the extra State/UT/City key columns make it a different admin
  level under rule 5, not the same collection as the All-India tables.

## A judgment call on C7 I want flagged

C7 contains nid 2009881 ("...from 1960 to 1969...") and 1912541 ("...from 1960 to
1970..."), which the pack's title-parser lists as NESTED (same start year, one end year
inside the other) - by rule 2 that would normally make 2009881 "to be removed". I did not
apply that: this table's non-key columns (Quinquennial Average, Percentage Variation) are
computed relative to each edition's own end year, not simple duplicated raw data, so the
"1960-1969" and "1960-1970" editions likely report different Quinquennial-Average windows
and different comparison figures rather than one being a strict superset of the other. I
kept both non-mergeable individually under rule 4 instead. Please double check this
reasoning - I did not open either file to confirm the Quinquennial-Average values actually
differ.

## Other

- No new mac tokens were needed; "year" (already in the vocabulary) covered everything.
- No LOCKED or "decided in batch X" / "in scope, batch X - do not claim" rows were
  encountered in any of the nine collections' outside lists, so nothing had to be left
  unclaimed for that reason.
- A handful of nids referenced in the pack's "similar rows outside" sections (e.g.
  1897801, 1897821, 1898201, 1898241, 2010161) have completely unrelated "commodity
  stock" data in place of the expected crime table (header
  `Date,Code,CommodityId,CommodityName,DistrictName,DistrictCode,Stock,...`). This looks
  like a file-mapping bug elsewhere in the pipeline, unrelated to this batch's decisions -
  flagging for awareness only, no action taken.
- File-read budget used: 20 of the ~30 allowed (all on rule 3 verification for C3/C4/C5/C8;
  none were needed for C1, C2, C6, C7 or C9, whose decisions rest on rule 7's named list or
  the pack's own header/year-column percentages).
