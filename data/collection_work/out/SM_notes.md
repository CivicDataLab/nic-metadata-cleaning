# Notes for batch SM (23 collections)

Files opened (8 total, well under the ~30 budget): 2 rainfall files (C15, rule 2/entity check),
6 NRI-arrivals files (C12, rule 3 overlap check). Everything else was decided from the pack text
and `table_index.tsv` greps.

## New mac tokens coined (not in the brief's vocabulary list)

- `insurer` - C3 (Financial Performance of Insurance Companies by Quarter). The company name
  (Oriental/National/United India Insurance) behaves exactly like `airline` in the worked
  examples - named only in title, same measure - but no insurer-style token existed in the
  vocab, so I coined one.
- `plan` - C19 (State-wise Outlay and Expenditure for Power Sector by Five Year Plan). The plan
  number (Seventh…Eleventh) is pinned in title only, like `state`/`airline`; no existing token
  fit a Five Year Plan number.

## Things worth a second look

**C3 (insurance quarters).** `Financial Performance of (The Oriental|National|United India)
Insurance...` matches 45 rows total in `table_index.tsv`; I only enumerated the ~20 rows the
pack listed explicitly as "similar rows outside the collection" (plus the 5 in-pack). There
are roughly 24-25 more loose quarter/year rows for the same 3 companies I did not individually
pull in - a grep sweep (`grep -Ei "Financial Performance of (The Oriental Insurance|National
Insurance|United India Insurance)" table_index.tsv`) would find the rest for the same
collection name.

**C11 (MSME Udyog Aadhaar).** The H2 group (15 states, group G859) never had headers extracted
by the pipeline - I merged them in on the strength of the identical title template (rule 1) but
this is unverified; worth spot-checking a couple of those 15 files aren't themselves broken
downloads before executing. Separately, nid 6690671 (Andhra Pradesh) and nid 6690685
(Maharashtra) are literal "Download Token Expired" error pages (H3) - decided with the rest of
the series per your instruction, at confidence `low`; they need re-downloading before the merge
can actually run.

**C13 (Monthly Coal Statement).** I named the merged collection identically to the existing
108-member `Monthly Coal Statement of Thermal Power Stations (direct merge)` collection
(nid 86712 etc., 2008-2013 coverage). That's deliberate - this is literally the same monthly
report for other months (Apr 2017-Nov 2023, plus Jan 2024 pulled in) - flagging per the naming
rule's "unless you are deliberately merging into it (say so)" clause.

**C15 (Rainfall by region).** I opened the 2021 All-India file (nid 7175407) and the 2015
All-India file (nid 1090561) to check rule 2's "same series and entity." They are the same
region/series, but two things are worth your attention before this executes:
- The 2015-edition file also carries five "Departure Percentage: <month>" columns that the
  2021 edition dropped entirely (2021 only has raw JUN/JUL/AUG/SEP/JUN-SEP rainfall, no
  departure %). I treated this as normal supersession (rule 2 just drops the older file, it
  isn't stacked), but you may want the departure-percentage figures preserved from an older
  edition if the newer one truly never re-added them.
- JUN values for the same year (e.g. 1901) differ slightly between the two editions (112.3 vs
  109.1) across *every* shared year, not just one - more than the "one small revision" rule 3
  tolerates for a *merge*. Since these are "to be removed" (dropped, not stacked), I don't think
  it blocks rule 2, but it means the historical series was quietly revised at some point and
  you may want to note that in the final dataset's description.
- I could not identify nid 7175424, titled only "Rainfall in sub-division and its departure
  from normal for Monsoon session from 1901-2021" (no region named) - left it untouched
  (non-mergeable, not claimed).
- I did not open files for Central/NE/NW/South Peninsula the way I did for All India; the
  "widest edition wins" cascade for those four regions is by title-window analogy only
  (medium confidence throughout that block).

**C16 (Tourist arrivals by country).** There is a separate, undecided-looking series
"International Tourist Arrivals in World and India" (nid 6651741, 6819426, 6879856, 7060623,
7280494) with its own NESTED/OVERLAP relationships parsed by the pack, sitting right next to
C16 in the same outside list. It is a different measure (World vs India totals + rank, not
per-country share) so I left it alone, but it isn't one of batch SM's 23 collections either -
it may be worth a dedicated pass later.

**C21 (toilets).** I split Girls/Boys/CWSN-Friendly/generic Toilets into four separate
collections rather than merging them with a `toilet_type` mac token. This is the opposite call
from C8/C9/C14/C23 (Rural/Urban/Combined merge via the sanctioned `urban_rural` token) - the
distinguishing point is that Girls/Boys/CWSN/generic Toilets are four different *facility
indicators* sitting in the same list as obviously-unrelated indicators (Electricity, Solar
Panels, Tinkering Labs), not a symmetric population partition of one indicator the way
Rural+Urban=Combined is. No `toilet_type` token exists in the vocab. Please double check this
reasoning since it's a judgment call in an area the brief didn't give a worked example for.

**C12 (NRI arrivals).** Opened all 5 in-pack files plus the outside 2015-2017 edition
(nid 6649046/cf65451a). The 2015-2017 edition's 2016/2017 monthly figures disagree substantially
(not a minor revision) with the kept 2016-2018/2017-2019 files, so per rule 3 I left it out
(it and its "to be removed" duplicate nid 6651716 already sit outside our batch, untouched). I
did not check nid 604708545/604709535 ("Month-wise Details of Break-up... 2019 to 2021") -
its window is identical to the kept nid 7278577's 2019-2021 edition, so it may be a further
duplicate worth a look, but I didn't want to spend more of the file-open budget confirming it
since it isn't required for pack coverage.

**C1.** nid 100563 ("Sale of power from 2009-10 to 2013-14") looks like the same subject but its
header has one column per year (`200910 Actual, 201011 Actual, 201112 Prov., 201213 RE, 201314
AP`) - years in every column, rule 4 - so I left it out rather than pulling it in.

**C4 (Forest and Tree Cover, 2013).** There is a separate, already-complete 33-member
`Forest and Tree Cover 2011` collection (change_in_header) sitting right outside this one. I did
not attempt to merge the two years together - no header text was available for the 2011
collection in the pack, and verifying it would have meant opening several more files for a
collection outside our batch scope. Worth a look if the user wants one continuous series
instead of two year-editions.

**C18 (Annual Plan outlay/expenditure).** 2010-11 and 2011-12 editions combine "Revised Outlay"
and "Expenditure" into a single per-state column instead of H1's two separate columns - a real
structural change, not just relabeling. I merged anyway (same evolving report, same subject) at
confidence `medium` with a Remark describing the column split needed.

**C6.** nid 100544 (the single H2 member, "Gross power generation (mkwh) from 2006-07 to
2011-12") is a long-format 3-column rollup of the same span the other 6 wide yearly files
cover - kept it non-mergeable/standalone rather than folding it in, since it's a different
table shape, not a header edit.
