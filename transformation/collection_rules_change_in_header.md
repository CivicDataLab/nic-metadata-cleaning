# Brief: deciding `change_in_header` collections

You are deciding how a batch of dataset **collections** should be fixed. The user is the
authority. The rules below were derived from the collections they fixed by hand and then
confirmed with them. Worked examples of their own decisions come in a separate file. Read
it: when a case looks like one of theirs, decide the way they did.

## Background

The table `dublin_core_remaining` has one row per published dataset (`nid`). Rows that
should be stacked vertically into one published dataset share a **Collection** name.

- `merge_method` says how the stacking works. For this work only three values matter:
  - `change_in_header`: members are stacked after small header edits.
  - `non-mergeable`: the row stays a standalone dataset, and its Collection is blank.
  - `to be removed`: the row is dropped because a newer dataset supersedes it. Its
    Collection is blank.
- `merge_add_columns` (mac) lists the columns to ADD while stacking, so that every stacked
  row stays identifiable (which airline, which year, …).
- Every collection in your pack currently has mac = `review`, a placeholder meaning
  "not decided". Many carry a meaningless `(schema N)` suffix, and many names pin one
  member's value (one airline, one state). All of that is what you are fixing.

## Rules (confirmed by the user)

**Grouping**

1. **Reconcilable headers belong together.** Varying headers are normal in
   change_in_header: spelling or case, an extra S.No. column, a fiscal-year vs normal-year
   header name, unit labels, column order. Members whose columns match after such minor
   edits stay in one collection. Never split on header count alone. The pack's "Header
   variants" section shows them after this reconciling, with what each variant has that
   the main one lacks.
2. **Nested editions → `to be removed`.** Same series, same entity (airline, state, …),
   and one window contains the other, e.g. "…2007-08 to 2014-15" and "…2007-08 to
   2015-16". Keep the latest (widest) edition; the older one becomes `to be removed`
   with Collection blank. The pack lists NESTED pairs it parsed from titles. Check they
   really are the same series and entity. Two rows with an identical window are
   duplicates: keep the one with better headers or the newer nid, and remove the other.
   This is how the user treated the aviation series, where each airline's newest edition
   supersedes its older ones. It does not apply inside a series merged under rule 3's
   exception (see there).
3. **Overlapping sliding windows**, i.e. different starts such as 1965-75 and 1966-76:
   open at least two overlapping files and decide from the data.
   - **Merge** when each file is a continuous one-row-per-year series (every year of its
     window present) and the shared years carry the same figures. That is what the user
     did with the NCRB Suicides and Accidental Deaths series ("Since all the figures are
     repeating … these can be merged"). A trailing summary row such as "Percentage change
     in 1988 over 1987" does NOT block this: it is dropped at merge time, so put
     `Drop the percentage-change summary rows` in Remark. A small revision in one shared
     year does not block it either; name the year in Remark. Merge with the full span in
     the name, at confidence `medium`, and state what you checked in the rationale.
   - **Non-mergeable** when files skip years inside their own window (selected-year
     comparison tables), when shared years disagree in more than one place, or when the
     columns are regrouped between editions. That is what the user did with the NCRB
     Juveniles by Age Group windows: years missing inside each window, a shared year
     differing, and age bands regrouped.
   - **Count the rows.** A "1965 to 1975" file must have 11 year rows, 1965 through
     1975. If any year inside a file's window is missing, the series is NOT continuous,
     so it is non-mergeable, even when every year that is present repeats exactly. Write
     the row count you found in the rationale.
   - If you can't open the files, the answer is `non-mergeable` at confidence `low`.
   - **When a series IS merged under this rule, every edition goes into the collection,
     including nested ones** (1964-68 inside 1964-71, and so on). The user kept all of
     them, and the duplicate years are dropped at merge time. Rule 2's `to be removed`
     applies only to series that are not merged this way.
4. **Years in every column → `non-mergeable`.** A wide table such as "Incidence 1960,
   Volume 1960, Incidence 1964, …", or "Upto 1986-87, During 1987-88, …", whose year
   columns differ between members. The pack shows each variant's share of year-labelled
   columns. One or two year-labelled columns (current vs previous year) do NOT count:
   merge, and put in Remark: `Year in the header can be changed to previous year or last year`.
5. **Different subject or measure → different collections**, even when the columns look
   alike. Passenger vs cargo traffic, female inmates vs all inmates, CPI base 2010 vs
   base 2012, SC vs ST, 2001 vs 2011 census where the classification changed, state
   tables vs district tables when the admin level changes the key columns. A category
   named **only in the title** (airline, domestic/international service, well type,
   jail type) is not a different subject. It stays in the collection and becomes a mac
   token.
6. **Pull in the same series from outside.** The pack lists similar rows outside the
   collection, whatever their merge_method (`direct`, `non-mergeable`, `curate`, no
   collection). If a row is the same series and fits, claim it (see Output) and give it
   the same decision. Only claim rows whose status is `free`, or that belong to a
   collection in YOUR batch. Never claim rows marked LOCKED, `decided in batch …`, or
   `in scope, batch X - do not claim`. If one of those belongs with your decision, say so
   in your notes file instead.
7. **The user's unexplained non-mergeable calls.** The user set some sets non-mergeable
   without a stated reason: Disposal of Crime under L&SL 1972-77, Juvenile by Age Group
   and Sex 1978-83, Inmates and Percentage Share 1998-2000, the 5th MI Census village
   tables split by in use / temporary / permanent / all, and the 2nd/3rd MI Census CCA
   tables. Those exact rows are already decided and locked. **Do not copy these calls onto
   other sets.** The user merged the very similar Disposal of Crime under Local & Special
   Laws 1978-82 set, so the calls are not a pattern. Decide a look-alike purely by rules
   1-6, which usually means merging. Then set confidence `low` and write "look-alike of
   user non-mergeable <which>" in the rationale, so the user sees it.

**Naming** (for change_in_header collections)

- The name must be true of **every** member. Replace a pinned value with a generic one
  ("Various Airlines", "States/UTs") or drop it. Drop edition tails such as "at the end
  of 2014", "during 1978" or "up to May", and never keep `(schema N)`.
- When members cover more than one year or edition, end the name with
  **"from <first> to <last>"**, in fiscal form ("2007-08") for fiscal series. Get the span
  right: first and last across ALL members.
- Keep the publisher's wording and casing style (e.g. "All India Level …"). A name must not
  equal an existing collection name unless you are deliberately merging into it (say so).
- Two different collections in your batch must have different names.

**merge_add_columns** (only for change_in_header rows; blank for the other two)

- Tokens only: snake_case, comma-separated, no spaces, e.g. `airline,service_scope,year`.
- A token belongs in mac only if the dimension **varies across members** AND is **not
  already a header column**. Example: Year is a header column → no `year`.
- Vocabulary in use: year, state, district, month, quarter, airline, service_scope
  (domestic/international/combined), carrier_class, jail_type, inmate_group, victim_group,
  offence, property_type, registration_type, price_basis, product_measure, school_level,
  area, scheme_type, storage_type, use_status, well_type, temperature_measure,
  social_group, sex, mi_census, law, casualty_type, base_year, region, urban_rural.
  A fiscal year is `year`. Coin a new token only if none fits, and mention it in your notes.
- Never `review`.

**Remark** is a free-text instruction for whoever merges, about header edits needed. Use it
when a member's header needs a specific fix, e.g. "Year in the header can be changed to
previous year or last year", or "The dataset has 10,000 instead of 100,000. The header can
be changed". Leave it blank otherwise.

## Your inputs

- `packs/<B>.md` is your evidence pack. It has one section per collection:
  - detector flags;
  - my earlier proposal, marked *NOT approved*. It predates the user's rules, so use it
    as research, not as an answer. In particular it never used `to be removed` or the
    overlap rule;
  - header variants (H1, H2 …) with year-column share;
  - members, listed individually or as groups G<n>;
  - parsed NESTED and OVERLAP windows;
  - similar rows outside the collection, with their status.
- `packs/<B>.json` holds the member nids per collection and per group. You don't need to
  read it; the loader uses it.
- `packs/table_index.tsv` has columns nid, ministry, merge_method, Collection, status and
  Title for the whole table. Grep it to find more of a series, e.g.
  `grep -i "annual traffic" packs/table_index.tsv`.
- Source files are at
  `/media/aak/246AF1266AF0F580/nic-metadata-cleaning/data/final_batch_downloads/<file>`,
  using the file name shown in the pack. Read them with the Read tool (use `limit`; the
  first ~30 lines are enough). The disk is slow, so open at most ~30 files in total, and
  only where rules 3/4 or a doubtful grouping need it.
- Do not open the database and do not write anywhere except your two output files.

## Output

1. `out/<B>.csv` (UTF-8, header row, quote fields containing commas). One row per
   **decision group**:

   | column | meaning |
   |---|---|
   | source_collection | the pack collection: its full name exactly as in the `## C<n> · <name>` heading, or just its id `C<n>`; `<outside>` for pulled-in rows |
   | members | `all` = every member · `rest` = members not covered by the other rows of this source_collection · `G3` or `G3,G7` = pack groups · `nid:123;456` = explicit nids (required for `<outside>`) |
   | merge_method | `change_in_header` \| `non-mergeable` \| `to be removed` |
   | Collection | the new name (change_in_header only; blank otherwise) |
   | merge_add_columns | tokens, blank if none |
   | Remark | blank unless needed |
   | confidence | `high` \| `medium` \| `low` |
   | rationale | one or two sentences: which rule and the evidence |

   Every member of every collection in the pack must be covered **exactly once**. Several
   rows can share a Collection name, e.g. members from two source collections plus
   pulled-in rows.

   Example:
   ```
   source_collection,members,merge_method,Collection,merge_add_columns,Remark,confidence,rationale
   Fleet Strength and Utilisation of Aircraft by Air Asia,nid:2934761;2934801,to be removed,,,,high,"Rule 2: contained in the 2007-08 to 2016-17 editions of the same airlines"
   Fleet Strength and Utilisation of Aircraft by Air Asia,rest,change_in_header,Fleet Strength and Utilisation of Aircraft by Various Airlines from 2007-08 to 2016-17,airline,,high,"Latest edition per airline; airline only in titles, YEAR is a column"
   <outside>,nid:4466741,change_in_header,Fleet Strength and Utilisation of Aircraft by Various Airlines from 2007-08 to 2016-17,airline,,medium,"Rule 6: Zoom Air edition of the same series, was non-mergeable"
   ```

2. `out/<B>_notes.md` holds short notes:
   - cross-batch or LOCKED rows that belong with one of your collections;
   - new mac tokens you coined;
   - anything the user should look at.

**Confidence**
- `high`: a rule applies clearly and the evidence is unambiguous.
- `medium`: needed judgment, or a file check (rule 3 always).
- `low`: a look-alike of an unexplained user call, genuinely unsure, or the evidence is
  missing (no headers, not downloaded).

Low and medium decisions are all reviewed by hand. Being honest about confidence matters
more than looking certain.
