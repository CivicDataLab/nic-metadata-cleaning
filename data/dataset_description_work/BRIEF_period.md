# Brief: turn a collection description into a one-file description template

## Background

India's health ministry publishes HMIS "item-wise" reports: one file per district per month.
Many monthly files of one district were grouped into a **collection**, and one description was
written for the whole collection. We now need a description for **each single file**.

You get the collection's description. You return the same description, edited so that it
describes ONE file of that collection. The file's own period is not known to you: put the token
`{period}` where the period belongs, and a program will fill it in for every file.

What `{period}` will be replaced with:

- `"mode": "monthly"` — one month, e.g. `January 2019 (FY 2018-19)`
- `"mode": "cumulative"` — from the start of the financial year up to one month, e.g.
  `April 2018 to February 2019 (FY 2018-19)`, or just `April 2018 (FY 2018-19)`

Your sentence must read correctly with either form. `for {period}` and `covering {period}` always work.

## Rules

1. **Edit, do not rewrite.** Keep the original sentences, their order, the place names, the
   facility wording and the ministry name. Change only what rules 2 to 5 require.
2. **Use `{period}` exactly once**, where the description states its time coverage. Delete the
   collection's own span ("FY 2011-12 to 2016-17", "across financial years 2013-14 to 2016-17",
   "for FY 2014-15") and put `{period}` there. If the description states no time coverage, add
   `for {period}` to the first sentence, normally right after the place name.
3. **Delete every other year, month name, date and clock time.** Phrases such as "provisional
   figures for 2017-2018", "up to April", "status as on 15 Mar 2019, 12:38 PM", "with a noted
   status timestamp" were copied from one file's note and are wrong for the other files. Keep
   the plain fact without the date: "with provisional figures", "figures are provisional".
4. **One file is not merged.** Remove "merged", "consolidates", "brings together", "combined
   files". "The merged dataset provides" becomes "The dataset provides".
5. **Fix wording that only fits a many-month series**: "month-wise", "across months", "across
   financial years", "over the specified financial years", "longitudinal", "year-wise",
   "for early months", "for the latest period". Drop the phrase or reword it in the smallest
   way. These may stay: "monthly", "cumulative", "trends", "over time", "updated monthly",
   "for the specified period".
6. **No new facts.** Do not add indicators, places, numbers or purposes that are not in the original.
7. The result is one line of plain text, 35 to 65 words, with no four-digit year and no month
   name anywhere, and with no quotation marks around it.

## Examples

OLD (monthly): HMIS Item-wise Monthly Report provides month-wise health management information system outputs for sub-districts in Udham Singh Nagar, Uttarakhand. It supports program monitoring, performance tracking, and evidence-based planning of family welfare and health services. Data are reported under the Ministry of Health and Family Welfare and are provided as provisional figures for the latest period, updated monthly.

NEW: HMIS Item-wise Monthly Report provides health management information system outputs for sub-districts in Udham Singh Nagar, Uttarakhand, for {period}. It supports program monitoring, performance tracking, and evidence-based planning of family welfare and health services. Data are reported under the Ministry of Health and Family Welfare and are provided as provisional figures, updated monthly.

OLD (cumulative): A monthly HMIS item-wise cumulative reporting dataset covering sub-districts of Rewari, Haryana. It compiles health-management information to support planning, monitoring, and review of service delivery. Provided by the Ministry of Health and Family Welfare, the files cover FY 2012-13 to 2016-17 with provisional figures for 2015-2016 up to April.

NEW: A monthly HMIS item-wise cumulative reporting dataset covering sub-districts of Rewari, Haryana. It compiles health-management information to support planning, monitoring, and review of service delivery. Provided by the Ministry of Health and Family Welfare, the file covers {period}, with provisional figures.

OLD (monthly): The merged dataset provides HMIS item-wise monthly reporting for sub-districts in Bulandshahar, Uttar Pradesh under the Health Management Information System. It supports monitoring service delivery across public and private facilities and rural/urban setups. The source is the Ministry of Health and Family Welfare (Department of Health and Family Welfare). Updates are monthly, with a noted status timestamp and provisional figures for 2017–2018.

NEW: The dataset provides HMIS item-wise monthly reporting for sub-districts in Bulandshahar, Uttar Pradesh, for {period}, under the Health Management Information System. It supports monitoring service delivery across public and private facilities and rural/urban setups. The source is the Ministry of Health and Family Welfare (Department of Health and Family Welfare). Updates are monthly, with provisional figures.

OLD (cumulative): This merged dataset brings together HMIS item-wise cumulative reports for sub-districts in Bilaspur, Chhattisgarh. It supports monitoring of health service delivery using provisional monthly cumulative figures across financial years 2013-14 to 2016-17. Data is published by the Ministry of Health and Family Welfare under Family Welfare reporting.

NEW: This dataset provides the HMIS item-wise cumulative report for sub-districts in Bilaspur, Chhattisgarh, for {period}. It supports monitoring of health service delivery using provisional monthly cumulative figures. Data is published by the Ministry of Health and Family Welfare under Family Welfare reporting.

## How to work

- This is a reading and editing job. Do NOT write a script, regex or shell command to produce
  the templates. Read each description and edit it yourself.
- Your pack is a JSONL file: one item per line with `id`, `mode`, `description`.
- Read it 60 lines at a time (Read tool with `offset` and `limit`). After each 60 lines, write
  the results for those lines to a new file `out/<pack name>_part<K>.tsv` (K = 1, 2, 3 ...),
  one line per item: the id, a TAB character, the template. No header line.
- Every id in the pack must appear exactly once across your part files. Do not skip items.
- When finished, reply with only: the number of items written, and the ids (at most 10) you
  were least sure about, each with a few words on why.
