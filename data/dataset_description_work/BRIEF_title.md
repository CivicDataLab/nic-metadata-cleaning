# Brief: turn a shared description into a one-file description template

## Background

India's health ministry publishes HMIS and health survey reports as many separate files: one per
state or district, per indicator, per period. Groups of such files share ONE description, written
for the whole group. We now need a description for **each single file**.

Each item gives you the shared `description`, the `collection` name (may be empty), the number
of `members`, and up to four `example_titles` taken from across the group. The example titles
show how the member files differ from each other: by state, district, indicator, period, or
frequency.

You return a template for ONE member file. Write the token `{title}` where the file's own title
goes; a program fills it in for every file, e.g.
`Range-wise Performance of Public Facilities for IPD Attendance of Lakshadweep for July-2019`.

## Rules

1. **Start with `{title}`** as the subject of the first sentence: "{title} provides ...",
   "{title} presents ...", "{title} compiles ...". Use `{title}` exactly once.
2. **Everything after `{title}` must be true for every member.** Compare the description with
   the example titles. Remove or generalise any state, district, indicator name, year, month or
   frequency word (monthly / quarterly / annual) that is not shared by all the example titles.
   If the description says "IPD attendance" and an example title says "OPD attendance (All)",
   write "attendance" or drop the indicator. If it says "Monthly" and the titles say
   "Quarterly" or "Annual", drop the frequency word.
3. **Do not repeat what the title already says** (place, period, indicator). The rest should
   say what kind of data this is, what it is used for, how it is scoped, and its source.
4. **Edit, do not rewrite.** Keep the original wording and sentence order wherever it is still
   true for every member.
5. **Delete years, month names, dates and clock times** ("provisional figures for 2010–2011",
   "updated as on 25 Dec 2015, 2:19 PM", "covers FY 2016-17"). Keep the plain fact without the
   date: "figures are provisional".
6. **One file is not merged.** Remove "merged", "consolidates", "brings together".
7. **No new facts.** Do not add indicators, places, numbers or purposes that are not in the original.
8. The result is one line of plain text, 30 to 60 words not counting `{title}`, with no
   four-digit year and no month name, and with no quotation marks around it.

## Example

Example titles: "Range-wise Performance of Public Facilities for IPD Attendance of Andaman and Nicobar Islands for April-2018"; "Range-wise Performance of Public Facilities for OPD attendance (All) of Haryana for January-2014"

OLD: Monthly performance indicators for public facilities reporting IPD attendance on the HMIS portal. The scope covers only districts that had shifted to facility-wise data uploading, excluding medical colleges. Data are presented at facility level rollups within ranges, capturing active facilities and their reporting and performance status.

NEW: {title} presents performance indicators for public facilities reporting attendance on the HMIS portal. The scope covers only districts that had shifted to facility-wise data uploading, excluding medical colleges. Data are presented at facility level rollups within ranges, capturing active facilities and their reporting and performance status.

Example titles: "Data Item Comparison Report of Khammam (Andhra Pradesh Old) for 2008-2009 & 2007-2008"; "Amreli District Data Item Comparison Report for 2013-2014 and 2012-2013"

OLD: The merged dataset provides district-level, month-wise comparisons of HMIS indicators using item-wise records. It supports monitoring and performance analysis of facility reporting through the financial year. Source is the Ministry of Health and Family Welfare (Department of Health and Family Welfare). Coverage includes provisional figures for 2010–2011 and 2011–2012.

NEW: {title} provides district-level, month-wise comparisons of HMIS indicators using item-wise records. It supports monitoring and performance analysis of facility reporting through the financial year. Source is the Ministry of Health and Family Welfare (Department of Health and Family Welfare). Figures may be provisional.

## How to work

- This is a reading and editing job. Do NOT write a script, regex or shell command to produce
  the templates. Read each item and edit it yourself.
- Your pack is a JSONL file, one item per line.
- Read it 45 lines at a time (Read tool with `offset` and `limit`). After each 45 lines, write
  the results for those lines to a new file `out/<pack name>_part<K>.tsv` (K = 1, 2, 3 ...),
  one line per item: the id, a TAB character, the template. No header line.
- Every id in the pack must appear exactly once across your part files. Do not skip items.
- When finished, reply with only: the number of items written, and the ids (at most 10) you
  were least sure about, each with a few words on why.
