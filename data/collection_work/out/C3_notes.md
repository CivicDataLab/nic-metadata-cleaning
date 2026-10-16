# Notes on batch C3 (Census of India tables, Registrar General)

## The one big judgment call: merging Scheduled Castes + Scheduled Tribes editions

Three pairs of pre-existing collections - Disability (SC/ST), Marital status (SC/ST), and
Population in single year age (SC/ST) - were each **merged together** (SC with ST, using
`social_group` as the mac token), rather than left as two separate collections. Reasoning:

- Their headers carry **no caste/tribe-name key column** (just the same plain
  `Table Name | State Code | District Code | Area Name | ... Total/Rural/Urban P/M/F`
  schema as the general-population version) - the SC/ST distinction lives only in the
  title. Per the task's own SC-vs-ST test ("different subjects when their key columns
  differ"), that means they are the *same* subject, so they merge with `social_group`
  distinguishing them - the same pattern as the airline/service_scope examples.
- This is different from the collections where SC and ST tables **do** carry a
  caste/tribe-name key column (`SC Code/SC Name` vs `ST Code/ST Name` - the
  "(Each Caste/Tribe Separately)" tables: education-by-type-of-institution and
  religious-community). Those were kept split by SC vs ST, per Rule 5.
- The **general-population** collection (no SC/ST filter) was deliberately kept
  **separate** from the merged SC+ST collection in all three cases, even though its
  header is identical too. General population is a superset that already includes SC and
  ST people (it is not a clean partition value like "SC vs ST" is), so it is closer to
  Rule 5's "female inmates vs all inmates" example than to "airline". This is a genuine
  judgment call - if you'd rather fold general population in as a third `social_group`
  value, or leave SC and ST as separate collections as they were before, that's a quick,
  well-defined change (just re-split the affected rows in the CSV; no re-research needed).
- Single Year Age Returns (`C16`) already had this shape baked into one collection (a
  2001 per-state general series plus two lone 2011 SC/ST national rows) - it was folded
  together the same way, and this one also matches the pre-existing prior proposal.

Rows affected: the Disabled Population (SC+ST), Marital status (SC+ST), and Population in
single year age (SC+ST) collections, plus their `<outside>` pull-ins.

## Census-round splits (2001 vs 2011)

- **Disabled Population** (general and SC+ST) was **split by round**: the single 2001
  India-level header sample has 25 columns / 5 disability types, the 2011 sample has 33
  columns / 7-8 types (Mental Illness split out from Mental Retardation, "Any Other"
  added). The detector's own `HEADER_IRRECONCILABLE` flag and `min_header_match 0.24`
  agree. For the SC and ST collections themselves no 2001 header was extracted, so the
  2001/2011 split there is inferred by analogy to the general collection - marked
  `medium` rather than `high`.
- Marital status, Population Attending Educational Institution (by completed level),
  Population by Religious Community, Population in single year age, and Primary Census
  Abstract all **merged across rounds** - their header match scores were 0.93-1.0 and the
  differences were column-naming or granularity only (e.g. marital status's 2001
  "Divorced/Separated" column vs 2011's separate "Divorced" and "Separated" columns is a
  finer split, not a new classification).

## Admin-level splits (district files vs state files)

Three collections mixed **district-level** files into what should be a **state-level**
series: `Population Attending Educational Institutions by Age, Sex and Type of
Educational Institution` (SC/ST, per-caste/tribe - already handled by the SC/ST key-column
split above), `Population by Religious Community` (its ST-district portion, 542 rows), and
`Primary Census Abstract` (593 district rows). For the latter two, I confirmed via
`grep`-ing `table_index.tsv` that the district-titled rows and the state-titled rows are
already cleanly separated by title pattern and that the state-level sibling collections
(`Population by Religious Community for Scheduled Tribe (Each Tribe Separately)`,
`Village/Town-wise Primary Census Abstract, 2011`) are genuinely distinct products, not
just a naming accident. I did not open any source files for this check because the pack
does not give file names for ordinary group members (only for a handful of `<outside>`
rows) - the call rests on title-pattern + header-schema evidence plus the prior proposal,
so I marked these `high` rather than treating the lack of a literal file-open as
disqualifying, but flag it here in case you want to spot-check one district file against
one state file directly.

## The `Population Attending Educational Institutions by Age, Sex and Type of Educational
Institution` leftover (nid 113197, group G254)

This one row (NCT of Delhi, no SC/ST, no extracted header) didn't fit the SC/ST split.
`grep`-ing `table_index.tsv` found an existing **free**, 35-member `change_in_header`
collection literally named `Population Attending Educational Institution by Age, Sex and
Type of Educational Institution, 2001` (singular "Institution", one row per state/UT,
e.g. nid 113188 India, nid 1213861 Delhi) that was missing exactly: NCT Delhi (=G254),
Uttaranchal (1213841), Orissa (1213881), Pondicherry (1213901), and Andaman & Nicobar
(1213921, plus a probable duplicate 113225 with no header/file - marked `to be removed`
in favor of 1213921). I pulled all of these into that existing collection name rather than
leaving G254 orphaned as `non-mergeable`. Confidence `medium` - title match is exact and
systematic, but several of the pulled-in rows (G254 itself, plus most of the outside ones)
have no extracted header to confirm columns.

## Things I deliberately did NOT touch

- Many `to be removed, free` duplicate-titled rows appear in nearly every collection's
  "similar rows outside" list (e.g. dozens of `Disabled Population by Type Of Disability,
  Age and Sex, 2001 -<state>` rows in C1's list). These are already correctly disposed of
  outside our collections, so I left them alone rather than re-deciding them.
- `Population In Five Year Age-group by Residence and Sex` (and its SC/ST variants) is a
  **different table** from `Population in single year age by Residence and Sex` despite
  very similar titles and appearing in the same "similar rows outside" sections (e.g. nid
  856621/857221 for Dadra & Nagar Haveli). Not pulled in.
- `Village/Town-wise Primary Census Abstract, 2011` and `Primary Census Abstract for
  Scheduled Castes`/`for Scheduled Tribes` are different products (finer admin level;
  different subject respectively) from our Primary Census Abstract collection - not
  pulled in, per Rule 5.
- `City-wise Population Attending Educational Institution by Age, Sex and Type of
  Educational Institution` and `District-wise Population Attending Educational
  Institution by Completed Education Level...` (curate collections referenced from C7/C8)
  are different admin-level products - left alone.
- nid 90320 (`Primary Census Abstract 2011 - Dadar and Nagar Haveli`) has a garbled,
  duplicated-looking header (`State Code,District Code,...,State Code.1,District
  Code.1,...`) and is already `non-mergeable`. I left it as-is rather than guessing.
- Several collections' outside sections end with "... N more loose rows (grep
  table_index.tsv)" - I did not exhaustively chase every one of these; I pulled in the
  ones explicitly listed in the pack text with a clear single-state/UT gap and a title
  that matches one of this batch's collections. There may be a few more genuine gaps to
  claim by grepping table_index.tsv further, especially for the largest collections (C1,
  C4, C15).

## mac tokens

No new tokens were coined. `year` and `social_group` (both already in the approved
vocabulary) cover everything needed.

## Confidence summary

- `high`: Disability round-split (general), C7/C12/C15-state (min_header_match 1.0 or
  ~0.97-0.98), C8 SC/ST split, C9 district/state split, C15 district/state split.
- `medium`: all the SC+ST merges, C4/C5+C6 (0.96 match), C10/C11 (0.93 match), C9/C15
  state-round merges (no direct score shown), the G254 education-institution pull-in
  cluster, C16.
- `low`: every `<outside>` pull-in without an extracted header (most of them), since the
  file wasn't downloaded and the match rests on title text alone.
