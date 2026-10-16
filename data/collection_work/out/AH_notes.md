# Notes on batch AH (Department of Animal Husbandry and Dairying)

## Headline finding: C13 and C14 are the same series, not two collections

The pack lists C13 "Share of milk production by cows, buffaloes and goats" (2008-09 to
2012-13, 5 members) and C14 "State & UT-wise Milk Production by Cows, Buffaloes & Goats"
(2009-10 to 2013-14, 5 members) as separate collections. I opened the 2009-10 files from
both (nid 305481 vs nid 836941) and the 2012-13 files from both (nid 305541 vs nid 837001):
in both cases the state-by-state figures are identical (e.g. Andhra Pradesh Cow Milk Total
2828.02 / 3698.93 matches exactly across the pair), just under slightly different column
labels (Cow Milk - CB/ND vs Cow Milk - Exotic/CB/IND-ND) and a renamed title. C13's title
says "Share of milk production" but the values are absolute production quantities (e.g.
9569.58), not percentages, so the two are the same measure, not different ones by rule 5.

I treated this as a sliding-window duplicate under rule 2/3: the four years C13 and C14
both cover (2009-10 through 2012-13) are duplicates - I dropped the C13 copies
(305481, 305501, 305521, 305541) as `to be removed` and kept the C14 editions, plus C13's
unique 2008-09 (305461) and C14's unique 2013-14 (837021), all stacked into one
`change_in_header` collection "State & UT-wise Milk Production by Cows, Buffaloes & Goats
from 2008-09 to 2013-14" (mac=year). I only verified 2 of the 4 overlap years byte-for-byte
(2009-10 and 2012-13); I did not open 2010-11/2011-12, so please spot-check those two if you
want full certainty. Confidence: medium, since this required judgment beyond the documented
patterns (not a pure rule-3 continuous-table overlap, and not a pure rule-2 identical-window
duplicate either - it's a hybrid I inferred from the file contents).

## Header typos found by opening files (C12 outside pull)

- nid 300181 (Meghalaya, "Number of stray cattle and dogs" - 2012): 3rd column header
  reads "Stray Rural" but the values are sensible cattle counts and the file otherwise
  matches the Stray Cattle/Stray Dogs template - the header should read "Stray Cattle".
- nid 303381 (Sikkim, same series): 4th column header reads "Strat Dogs", a typo for
  "Stray Dogs".
  Both are flagged in the Remark for that row in AH.csv; I still pulled them in (rule 6)
  since the data content is unambiguous.

## Pattern across C1-C10 and C12 (not independently file-checked)

All of these collections are the same shape: one file per state/UT for a single year, with
District as the only geo column in the header and the state name only in the title. I
treated every "H2/H3 adds columns beyond H1" case as rule-1 reconcilable (extra rural/urban
or age-band breakdown, or an added S.No. column) rather than opening files to confirm,
because the pack's own "Header variants (after reconciling...)" section already frames them
that way, and the (not-approved) prior proposal explicitly notes for each of these
collections that "column-prefix and rural/urban-breakdown differences are reconcilable."
I only opened files where a further check seemed warranted (C12's odd headers, and the
C13/C14 duplicate check). If you want independent verification of the reconciliation itself
for C1/C2/C4/C5/C6/C7/C9/C10/C12, that assumption is inherited from the pack rather than
re-derived by me.

All A&N Islands / Puducherry / Lakshadweep / Meghalaya / Sikkim outside pulls (rule 6) were
confirmed "free" in the pack text before claiming.

## Not claimed - different subject (rule 5), flagged in case it matters to another batch

"Details of cattle by age, sex and use in rural and urban combined" (merge_method=curate,
free, ~32-34 members, e.g. nid 291461, 304661, 305061) is the same state-file/2012 shape as
C2/C4/C5/C10 but for cattle specifically - a different animal, so I left it alone per rule 5.
It looked like a strong candidate for the same mac=state treatment if/when it's someone's
batch to decide.

Similarly, "District wise Number of Cattle by breed" (curate, free), "District wise Number
of Indigenous Sheep by Breed" (curate, free) and "District wise Number of Indigenous pig by
breed" (curate, free) are the same 2007 district-breed-count shape as C11 but for a
different animal/classification - not claimed, rule 5.

## mac tokens

No new tokens were coined. Every collection in this batch only needed `state` or `year`,
both already in the vocabulary list.

## LOCKED / cross-batch

I did not encounter any rows marked LOCKED or "decided in batch X" while working this pack;
all outside rows referenced above are explicitly "free" in the pack text.
