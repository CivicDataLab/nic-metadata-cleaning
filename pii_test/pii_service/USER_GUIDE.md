# PII Check: User Guide

This guide is for anyone who wants to check a dataset for personal data before publishing it. You don't need to know how the service works inside. It covers:

- the two ways to use it: a web page, or an API for scripts and other systems
- what to send so the check works well
- how to read the answer

For the full technical reference (every field, every error code), see **[API.md](API.md)**.

---

## 1. What the service does

You give it a **CSV, JSON, Excel or PDF file**. It tells you whether the file contains **personal data about individuals**, such as names, mobile numbers, email addresses, Aadhaar or PAN numbers, or farmer IDs, and whether that data **may be published**.

It doesn't just search for names and numbers. It also decides what they are. A list of *District Collectors with their office phone numbers* is public information and can be published. A list of *pension beneficiaries with their fathers' names and mobile numbers* cannot.

You get one of five answers for the whole file:

| Answer | Label on the page | What it means | What you should do |
|---|---|---|---|
| `present` | **PII present** | Personal data about private individuals. | **Redact the listed columns** before publishing. |
| `undecided` | **Needs review** | Some columns could not be decided automatically. | **Have a person look at the listed columns.** Do not treat this as "probably fine". |
| `permissible` | **Permissible** | Personal data, but official or public-role information (officers' names, office phone numbers, helplines). | Can be published. |
| `false_positive` | **No PII** | Something looked like personal data but isn't, e.g. village names mistaken for people's names. | Nothing to do. |
| `no_pii_found` | **No PII** | Nothing was detected. | Check the warnings first; see [section 6](#6-warnings-you-may-see). |

With the answer, you also get a **table of the flagged columns**. Each row shows the column's own verdict, the kind of data found and a one-line reason.

---

## 2. Before you start

- **The address** is **`https://skilled-machine-juror.ngrok-free.dev`**. In this guide it is written as `<BASE>`.
- **A password, if the owner has set one.** On the page, your browser will ask for it. From a script, send it as HTTP basic auth.
- **Your file must be:**
  - a `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` file, at most **100 MB**
  - a CSV or Excel sheet needs a **header row** (column names) as its first line; for JSON, see [section 8](#8-file-formats-and-layouts)
  - for an Excel workbook, only the first sheet is checked. To check another sheet, save it as its own file.

> **First visit from a browser:** you may see an ngrok page saying you are about to visit a site. Click **Visit Site**. It appears once and does not affect scripts.

---

## 3. Option A: the web page (no code)

1. Open `<BASE>/` in your browser.
2. **File:** choose your CSV, JSON, Excel or PDF file.
3. **Dataset title**, **Catalog title** and **Description:** fill in as much as you can. These fields are optional, but they make a real difference; see [section 5](#5-describing-your-dataset-this-matters).
4. Leave **Rows to scan** at 50,000 and **Use the LLM judge** ticked unless you have a reason to change them:
   - Lower the row count for a quick first look at a very large file.
   - Untick the judge if you only want the fast rule-based answer.
   - Tick **Make a redacted copy** if you also want the file back with its personal data replaced; see [section 7](#7-getting-a-redacted-copy).
5. Click **Check**. The status line shows progress:
   - *Queued — position N*: someone else's file is being checked first.
   - *Queued — models are still loading*: the service restarted recently; wait about a minute.
   - *Reading the file…* → *Scanning…* → *Applying rules…* → *LLM judge… 2/5 columns* → *Redacting…* (only if you asked for a redacted copy)
6. When it says **Done**, you'll see the answer badge, a one-line message, any warnings and the column table. These downloads are offered:
   - `results.csv`: the complete result; see [below](#the-complete-result-resultscsv). **This file contains the personal data itself; handle it accordingly.**
   - `columns.csv`: the column table.
   - `result.json`: the full answer.
   - `detections.csv`: every individual value that was flagged, without the verdicts. It also contains the personal data itself.
   - `redacted.csv`: the redacted copy. The link appears only if you asked for one and it could be made; a line above the links says what was redacted.

Keep the **Run ID** shown at the bottom of the result if you may need to refer to this check later.

---

## 4. Option B: the API (for scripts and systems)

A check takes three steps. The service works **asynchronously**, so you do not wait on one long request.

```
1. POST <BASE>/scan              send the file + description  →  you get a run_id
2. GET  <BASE>/jobs/<run_id>     ask every 2 seconds           →  until status is "done" or "error"
3. read "result" from that same response
```

### With curl

```bash
BASE=https://skilled-machine-juror.ngrok-free.dev

# 1. Submit
curl -s "$BASE/scan" \
  -F file=@hospitals.csv \
  -F title="Directory of District Hospitals, Assam" \
  -F catalog_title="Health Facilities of Assam" \
  -F description="One row per district hospital: hospital name, address, superintendent's name and office phone number."
# -> {"run_id": "20260926T135716Z_a7ac…", "status_url": "/jobs/20260926T135716Z_a7ac…", …}

# 2 + 3. Check the status (repeat until "status" is "done" or "error")
curl -s "$BASE/jobs/20260926T135716Z_a7ac…"
```

If a password is set, add `-u user:password` to each command.

### With Python

```python
import time
import requests

BASE = "https://skilled-machine-juror.ngrok-free.dev"
AUTH = None                      # or ("user", "password") if the owner set one


def check_pii(path, title=None, catalog_title=None, description=None, use_llm=True):
    """Upload one CSV and return the service's answer (a dict)."""
    with open(path, "rb") as fh:
        response = requests.post(
            f"{BASE}/scan",
            files={"file": (path.split("/")[-1], fh, "text/csv")},
            data={
                "title": title or "",
                "catalog_title": catalog_title or "",
                "description": description or "",
                "llm": "true" if use_llm else "false",
            },
            auth=AUTH,
            timeout=300,          # the upload itself; large files take a while
        )
    response.raise_for_status()
    run_id = response.json()["run_id"]

    while True:
        job = requests.get(f"{BASE}/jobs/{run_id}", auth=AUTH, timeout=30).json()
        if job["status"] == "done":
            return job["result"]
        if job["status"] == "error":
            raise RuntimeError(f"run {run_id} failed: {job['error']}")
        time.sleep(2)


result = check_pii(
    "hospitals.csv",
    title="Directory of District Hospitals, Assam",
    description="One row per district hospital: name, address, superintendent and office phone.",
)
print(result["final_class"], "-", result["message"])
for col in result["columns"]:
    print(f"  {col['column']:<25} {col['class']:<15} {col['pii_types']:<20} {col['reason']}")
for warning in result["warnings"]:
    print("  WARNING:", warning)
```

### What you can send to `POST /scan`

| Field | Required | Notes |
|---|---|---|
| `file` | yes | The `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` file, at most 100 MB. |
| `title` | no, but recommended | The dataset's name. At most 500 characters. |
| `catalog_title` | no | The collection or catalog it belongs to. At most 500 characters. |
| `description` | no, but recommended | What one row of the data is. At most 5,000 characters. |
| `llm` | no | `true` (default) or `false`. `false` skips the LLM judge, so it's faster, but columns the rules can't decide stay `undecided`. |
| `max_rows` | no | Rows to check from the top of the file. Default and maximum: 50,000. |
| `redact` | no | `true` or `false` (default). `true` requests a redacted copy of the file. |

### What you get back

When `status` is `"done"`, the `result` looks like this:

```json
{
  "final_class": "present",
  "message": "Personal data found in 3 column(s): Beneficiary Name, Father Name, Mobile No. Redact before publishing.",
  "columns": [
    {"column": "Beneficiary Name", "class": "present", "pii_types": "PERSON",
     "decided_by": "tier1", "reason": "header token 'beneficiary' names a private individual regardless of dataset context"},
    {"column": "Father Name", "class": "present", "pii_types": "PERSON",
     "decided_by": "tier1", "reason": "header token 'father' names a private individual, and the dataset is not a directory"},
    {"column": "Mobile No", "class": "present", "pii_types": "PHONE_NUMBER",
     "decided_by": "tier1", "reason": "dataset holds individual records (title matches 'beneficiar')"}
  ],
  "rows_scanned": 200,
  "tier3": "not_needed",
  "metadata_source": "request",
  "warnings": [],
  "run_id": "20260926T135716Z_a7ac…"
}
```

The fields most integrations need:
- `final_class`: the answer; see the table in [section 1](#1-what-the-service-does).
- `message`: a sentence you can show a person as-is.
- `columns`: the flagged columns, most serious first. `decided_by` is `tier1` (a rule decided) or `tier3` (the LLM judge decided).
- `warnings`: an empty list means no caveats. **Always show these to the user if there are any.**

Once the check is finished, you can also download files from `<BASE>/jobs/<run_id>/files/<name>`. The name is one of:
- `results.csv` (the complete result; see below)
- `columns.csv`
- `result.json`
- `detections.csv`
- `tier1_column_class.csv`
- `tier3_verdicts.csv` (the judge's reasoning)
- `column_class.csv`
- `redacted.csv` (only when `redact=true` was sent and it succeeded)

Interactive API docs, where you can try requests in the browser, are at `<BASE>/docs`.

### The complete result: `results.csv`

`results.csv` has **one row for every value that was flagged**, with what each step of the check said about it:

| Column | What it tells you |
|---|---|
| `column`, `row_index` | Where the value is in your file (rows are counted from 0, not including the header). |
| `entity_type`, `entity_text` | What kind of data it looks like (`PERSON`, `PHONE_NUMBER`, …) and the value itself. |
| `score`, `source` | How confident the detector was, and which detector found it. |
| `tier1_class`, `tier1_reason` | What the rules decided for this column, and why. `undecided` means the rules couldn't decide. |
| `llm_verdict` | What the judge decided for the column. Empty if the column never went to the judge; only columns the rules left `undecided` go to it. |
| `llm_reasoning` | The judge's explanation. It appears only on the rows whose value the judge was shown as an example; it sees up to 15 different values per column. |
| `final_class`, `decided_by` | The final verdict for the column, and whether the rules (`tier1`) or the judge (`tier3`) made it. |

Two things to know when reading it:
- **Verdicts are made per column, not per value.** Every row of a column carries the same verdict.
- **An empty `llm_verdict` means the rules decided that column** and the judge was not needed.

---

## 5. Describing your dataset (this matters)

The same column can be fine in one dataset and personal data in another. "Name + mobile number" is:
- publishable in a *directory of Block Development Officers*
- private in a *list of scholarship recipients*

The service can only tell these apart if it knows what the dataset is. It learns that from:

1. the **title**, **catalog title** and **description** you send
2. the file's **column names**.

If you send nothing, it falls back to the **file name**. That can go badly wrong: a file called `synthetic_people.csv` was once judged "not real people" because of the word *synthetic*.

**Good descriptions say what one row is and who the people in it are:**

| Instead of… | Send… |
|---|---|
| title: `data` | title: `List of beneficiaries under PM-KISAN, Bihar, 2024` |
| title: `Assam hospitals` | title: `Directory of District Hospitals, Assam`; description: `One row per hospital: name, address, medical superintendent and office phone` |
| no description | description: `Each row is one farmer's call to the Kisan Call Centre: the question asked and the advice given` |

Also:
- **Keep the real column names.** Names like *Father Name*, *Mobile No*, *Office Phone* or *Designation* carry a lot of the signal.
- **Keep sensible file names**, and avoid `test.csv` or `dummy.csv` if you don't send a title.

---

## 6. Warnings you may see

| Warning starts with… | What it means | What to do |
|---|---|---|
| *No title or description was sent…* | The check only had the file name and column names to go on. | Resend with a title and description for a more reliable answer. |
| *Nothing was scanned: none of the file's N column(s) holds free text…* | Every column was numbers, codes, dates or empty, so nothing was examined. | Usually fine for purely statistical data, but `no_pii_found` here means "not examined", not "checked and clean". |
| *Nothing was scanned: the file has no data rows.* | The file only has a header. | Check that you uploaded the right file. |
| *The LLM judge did not run…* | The judge was unavailable, so columns it would have decided are `undecided`. | Try again later, or have a person review those columns. |
| *N column(s) over the per-run judge limit of 40 left undecided.* | A very wide file had more doubtful columns than one check will judge. | Review those columns by hand, or split the file by columns. |
| *NER failed on this file; only the regex detectors ran.* | Names may have been missed. Phone, email, Aadhaar, PAN and farmer-ID detection still ran. | Try again; if it repeats, tell the service owner. |
| *Only the first sheet (…) was checked…* | The Excel workbook has other sheets that were not looked at. | Save each other sheet as its own file and check it too. |
| *The file is named as an Excel workbook but holds plain text…* | The file was read as CSV. | Nothing, if the result looks right. |
| *In N free-text column(s) only the values the detectors flagged were replaced…* | Redacted copy: a name the detectors missed may still be in those columns. | Read those columns before publishing the copy. |
| *N free-text column(s) could not be redacted value by value…* | Redacted copy: every filled cell of those columns was replaced instead. | Nothing; the text of those columns is gone from the copy. |
| *N free-text column(s) were too long to search…* | Redacted copy: the file has more than 200,000 cells of sentences, so every filled cell of those columns was replaced instead. | Split the file into smaller parts if you need the text kept. |
| *The redacted copy still holds N undecided column(s)…* | Redacted copy: those columns were left as they were. | Have a person review them before publishing. |
| *The redacted copy holds the first sheet only.* | Redacted copy of a workbook with several sheets. | Check and redact the other sheets separately. |
| *Only the first N of M pages were checked.* | The PDF has more than 200 pages. | Split it and check the rest. |
| *No text could be read from N page(s)…* | Those PDF pages are blank or unreadable, so they were not checked. | Look at those pages yourself. |
| *Nothing was checked: no text could be read from this PDF.* | `no_pii_found` here means "not examined". | Upload a better scan, or review the document by hand. |
| *N page(s) were read by OCR…* | Scanned pages; a misread letter or digit can hide a name or a number. | Glance through those pages before relying on a clean result. |
| *The OCR was unsure of what it read…* | A poor scan. | Treat a clean result with caution. |

---

## 7. Getting a redacted copy

Ask for one with the upload: tick **Make a redacted copy** on the page, or send `-F redact=true` from a script. If the check finds columns classified `present`, you get the file back as `redacted.csv` with the personal data in those columns replaced by placeholders such as `<PERSON>` and `<PHONE_NUMBER>`.

```
curl -s -F file=@beneficiaries.csv -F title="List of beneficiaries" -F redact=true <BASE>/scan
# … wait for "done" as in section 4, then:
curl -s -o beneficiaries_redacted.csv <BASE>/jobs/<run_id>/files/redacted.csv
```

### What is replaced

| Kind of column | What happens | Example |
|---|---|---|
| **Short values**: names, phone numbers, IDs (a typical cell is 40 characters or fewer) | **Every filled cell** is replaced. | `Ramesh Kumar` → `<PERSON>` |
| **Free text**: sentences (a typical cell is longer than 40 characters) | The flagged values are replaced inside the cell; the rest of the sentence stays. | `Called on behalf of <PERSON> about the delayed installment` |

- **Why every cell in a short-value column?** The check does not catch every name in a column of names. Replacing only the ones it caught would leave the others in the file.
- **Free text is searched again for the redaction,** more thoroughly than for the check itself, so more may be replaced than `results.csv` lists. Even so, **a name the detectors miss stays in the text.** A warning names these columns: have a person read them before publishing.
- **Every row is covered,** not only the 50,000 rows the check looks at.
- Empty cells stay empty.

### What is not touched

- Columns classified `permissible` or `false_positive` are left exactly as they were.
- **Columns classified `undecided` are also left as they were.** A warning names them. The copy is not ready to publish until a person has reviewed those columns.
- **Columns the check did not flag at all are left as they were.** The copy is only as good as the check: look at the column table, and if a column you know holds personal data is not listed as `present`, it has not been redacted.
- For an Excel workbook, the copy holds the **first sheet only**, and cells come out as plain text: a date cell reads `2024-01-05 00:00:00`.
- **A PDF cannot be redacted yet.** Asking for a copy of one answers "not supported"; the check still gives its answer.

### What you get

- The copy is **always a CSV**, also when you uploaded JSON or Excel.
- The result gains a `redaction` part: `status` is `done` (the copy is ready), `not_needed` (nothing was classified `present`, so there is no copy) or `failed` (no copy; `message` says why). When it is `done`, `columns` lists each redacted column, how it was redacted (`whole_column` or `found_values`) and how many cells changed.
- If the redaction cannot be completed safely, the check still finishes with its answer; only the copy is missing.

**Before you publish a redacted copy:** read the warnings, review any `undecided` and free-text columns yourself, and open the file to see that it looks right.

---

## 8. File formats and layouts

The service decides the type from the ending of the file name: `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`.

### JSON

Any of these layouts works:

1. **A list of records:** `[{"Name": "Asha Rao", "Village": "Rampur"}, {"Name": "Vikram Nair", "Village": "Sonpur"}]`
2. **An object holding one list of records:** `{"data": [{"Name": "Asha Rao", …}, …]}`
3. **An object holding several lists of records:** the one named `rows`, `records` or `data` is used, looked for in that order.

- A nested object becomes dotted column names: `{"address": {"city": "Pune"}}` becomes a column `address.city`.
- A list inside a record is kept as text in one cell, so it is still checked.
- In the results, `column` is the JSON key and `row_index` is the record's position in the list, counted from 0.

### Excel

- `.xlsx` and `.xls` workbooks are read directly.
- **Only the first sheet is checked.** If the workbook has more sheets, a warning names the ones that were not checked. Save another sheet as its own file to check it.
- A workbook that unpacks to more than 500 MB is refused; save the sheet as CSV instead.
- A file named `.xls` or `.xlsx` that is really a text file, which is common in government downloads, is read as CSV. A warning tells you.

### PDF

- A PDF is checked as text, page by page. If a page already holds text, that text is used. If it is a scan, the service reads it with OCR, in English and Hindi.
- **The answer names pages, not columns:** "Personal data found on 3 page(s): 1, 4, 7." In `results.csv`, the `page` and `line` columns say where each value was read.
- **Only the first 200 pages are read.** A warning tells you when the file has more; split a longer file.
- **OCR makes mistakes.** A blurred digit can hide a phone number. Warnings tell you how many pages were read by OCR and whether the scan was hard to read. Treat a clean result on a poor scan with caution.
- **Names written in Hindi are only partly found.** On a test page of 12 Hindi names the check reported 3 in full, 5 in part and missed 4. Phone numbers, Aadhaar, PAN and email are still found in Hindi text. Review a Hindi document yourself rather than relying on a clean result.
- **Describe the document.** The whole PDF gets one answer, and one mobile number is enough to make it "PII present". An office order that names officers was judged publishable only when its title and description said what it was; see [section 5](#5-describing-your-dataset-this-matters).
- A password-protected PDF cannot be read; remove the password first.
- A redacted copy cannot be made of a PDF yet.

---

## 9. Timing and limits

| | |
|---|---|
| Small file (a few hundred rows) | a few seconds, plus about 20 seconds for each column sent to the LLM judge |
| Large file (50,000 rows of long text) | several minutes (7 minutes in one test) |
| Redacted copy | no extra time for name, phone and ID columns; for a column of sentences, about as long again as the check took |
| JSON file | converting it takes about a second for 10 MB |
| PDF | the first 200 pages; a page with its own text is instant, a scanned page takes 2 to 3 seconds |
| File size | 100 MB maximum |
| Rows checked | the first 50,000; personal data that only appears further down is not seen |
| Columns judged by the LLM per check | 40 |
| Checks at once | one; others wait in a queue (you'll see your position) |
| How long a result can be fetched | about 6 hours after you submit it, then the link returns "No such run" |

If the service restarts, checks that were still queued or running are lost. The status link will return "No such run"; just submit the file again.

---

## 10. Common problems

| You see | Why | Fix |
|---|---|---|
| `Only .csv, .json, .xlsx, .xls and .pdf files are accepted` | The file name doesn't end in one of those. | Save or rename the file. |
| `Not a valid PDF file` | The file is named `.pdf` but is damaged or is something else. | Export or download it again. |
| `The PDF is password-protected…` | The service cannot open it. | Remove the password and upload it again. |
| `The PDF took too long to read…` | A very long or very heavy scan. | Split it into smaller files. |
| `Not valid JSON…` | The JSON file is cut off or malformed. | Export or download the file again. |
| `No table found in the JSON…` or `The JSON holds no records` | The file is not a list of records, for example a failed download. | Check the layout; see [section 8](#8-file-formats-and-layouts). |
| `The workbook unpacks to N MB, over the 500 MB limit` | An Excel file is too large when unpacked. | Save the sheet as a CSV instead. |
| `The file is named .xls but holds HTML or XML` | An Excel file is really a web page. | Save it as CSV. |
| `File exceeds 100 MB` (or an HTML "413" page) | The file is too big. | Split it, or check a sample of its rows. |
| `title is longer than 500 characters` | Title or catalog title too long (description allows 5,000). | Shorten it; put the detail in the description. |
| `No such run` | The result is older than about 6 hours, the service restarted, or the run ID is mistyped. | Submit the file again. |
| "502 Bad Gateway" | The service is restarting (about 10–15 seconds). | Wait and retry. |
| Status stuck at *models are still loading* | The service just restarted. | Wait about a minute. |
| A small file with an obvious list of names comes back `no_pii_found` | A column that repeats the same few names many times is treated as a category, like a list of scheme names, not as people. | Check with more rows, or have a person review. |
| Any network error from a script, or an ngrok "endpoint is offline" page | The service or its tunnel is down. | Check the address is exactly `https://skilled-machine-juror.ngrok-free.dev`; if it is, contact the service owner. |

---

## 11. What happens to your data

- **Everything you upload is kept permanently** in the platform's storage: the file, the title and description you sent, and the results. Each check gets its own folder, shown as `s3_folder` in the result. **Only upload data that is allowed to be stored there.**
- The copy on the service machine itself is deleted after about 6 hours.
- The LLM judge runs **on the service's own server**. Your data is not sent to any outside AI service.
- **Anyone who has a run ID can read that run's results**, including `results.csv` and `detections.csv`, which contain the flagged personal data. Run IDs are long and random, so they can't be guessed, but share them only with people who should see the results.

---

## 12. Quick checklist

- [ ] File is `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`, under 100 MB; tables have a header row; a PDF has no password
- [ ] Title and description sent, saying what one row is
- [ ] Waited for `done`, not just for the upload to succeed
- [ ] Read the `warnings`
- [ ] `present` → redact the listed columns; `undecided` → a person reviews them
- [ ] `results.csv` and `detections.csv` handled as personal data
- [ ] If you requested redaction: read the redaction warnings before publishing the redacted copy

Questions, wrong answers or a service that seems down: contact the service owner and include the **run ID**.
