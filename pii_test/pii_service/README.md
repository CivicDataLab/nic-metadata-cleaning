# PII Check

This folder is the PII Check service: a web page and an API that tell you whether a CSV, JSON, Excel or PDF file contains personal data, and whether that data may be published. This README has two parts:

- **[Part 1: User guide](#part-1-user-guide)**, for anyone checking a dataset before publishing it. No code needed.
- **[Part 2: API reference](#part-2-api-reference)**: every endpoint, field, error code and limit, for developers.

How the service is built, deployed and run on this server (the systemd units, gunicorn, nginx, ngrok, the tests and logs) is in [../README.md, section 13](../README.md#13-the-pii-api).

---

## Part 1: User guide

This guide is for anyone who wants to check a dataset for personal data before publishing it. You don't need to know how the service works inside. It covers:

- the two ways to use it: a web page, or an API for scripts and other systems
- what to send so the check works well
- how to read the answer

For the full technical reference (every field, every error code), see **[Part 2: API reference](#part-2-api-reference)**.

---

### 1. What the service does

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

### 2. Before you start

- **The address** is **`https://skilled-machine-juror.ngrok-free.dev`**. In this guide it is written as `<BASE>`.
- **A password, if the owner has set one.** On the page, your browser will ask for it. From a script, send it as HTTP basic auth.
- **Your file must be:**
  - a `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` file, at most **100 MB**
  - a CSV or Excel sheet needs a **header row** (column names) as its first line; for JSON, see [section 8](#8-file-formats-and-layouts)
  - for an Excel workbook, only the first sheet is checked. To check another sheet, save it as its own file.

> **First visit from a browser:** you may see an ngrok page saying you are about to visit a site. Click **Visit Site**. It appears once and does not affect scripts.

---

### 3. Option A: the web page (no code)

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

### 4. Option B: the API (for scripts and systems)

A check takes three steps. The service works **asynchronously**, so you do not wait on one long request.

```
1. POST <BASE>/scan              send the file + description  →  you get a run_id
2. GET  <BASE>/jobs/<run_id>     ask every 2 seconds           →  until status is "done" or "error"
3. read "result" from that same response
```

#### With curl

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

#### With Python

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

#### What you can send to `POST /scan`

| Field | Required | Notes |
|---|---|---|
| `file` | yes | The `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` file, at most 100 MB. |
| `title` | no, but recommended | The dataset's name. At most 500 characters. |
| `catalog_title` | no | The collection or catalog it belongs to. At most 500 characters. |
| `description` | no, but recommended | What one row of the data is. At most 5,000 characters. |
| `llm` | no | `true` (default) or `false`. `false` skips the LLM judge, so it's faster, but columns the rules can't decide stay `undecided`. |
| `max_rows` | no | Rows to check from the top of the file. Default and maximum: 50,000. |
| `redact` | no | `true` or `false` (default). `true` requests a redacted copy of the file. |

#### What you get back

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

#### The complete result: `results.csv`

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

### 5. Describing your dataset (this matters)

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

### 6. Warnings you may see

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

### 7. Getting a redacted copy

Ask for one with the upload: tick **Make a redacted copy** on the page, or send `-F redact=true` from a script. If the check finds columns classified `present`, you get the file back as `redacted.csv` with the personal data in those columns replaced by placeholders such as `<PERSON>` and `<PHONE_NUMBER>`.

```
curl -s -F file=@beneficiaries.csv -F title="List of beneficiaries" -F redact=true <BASE>/scan
# … wait for "done" as in section 4, then:
curl -s -o beneficiaries_redacted.csv <BASE>/jobs/<run_id>/files/redacted.csv
```

#### What is replaced

| Kind of column | What happens | Example |
|---|---|---|
| **Short values**: names, phone numbers, IDs (a typical cell is 40 characters or fewer) | **Every filled cell** is replaced. | `Ramesh Kumar` → `<PERSON>` |
| **Free text**: sentences (a typical cell is longer than 40 characters) | The flagged values are replaced inside the cell; the rest of the sentence stays. | `Called on behalf of <PERSON> about the delayed installment` |

- **Why every cell in a short-value column?** The check does not catch every name in a column of names. Replacing only the ones it caught would leave the others in the file.
- **Free text is searched again for the redaction,** more thoroughly than for the check itself, so more may be replaced than `results.csv` lists. Even so, **a name the detectors miss stays in the text.** A warning names these columns: have a person read them before publishing.
- **Every row is covered,** not only the 50,000 rows the check looks at.
- Empty cells stay empty.

#### What is not touched

- Columns classified `permissible` or `false_positive` are left exactly as they were.
- **Columns classified `undecided` are also left as they were.** A warning names them. The copy is not ready to publish until a person has reviewed those columns.
- **Columns the check did not flag at all are left as they were.** The copy is only as good as the check: look at the column table, and if a column you know holds personal data is not listed as `present`, it has not been redacted.
- For an Excel workbook, the copy holds the **first sheet only**, and cells come out as plain text: a date cell reads `2024-01-05 00:00:00`.
- **A PDF cannot be redacted yet.** Asking for a copy of one answers "not supported"; the check still gives its answer.

#### What you get

- The copy is **always a CSV**, also when you uploaded JSON or Excel.
- The result gains a `redaction` part: `status` is `done` (the copy is ready), `not_needed` (nothing was classified `present`, so there is no copy) or `failed` (no copy; `message` says why). When it is `done`, `columns` lists each redacted column, how it was redacted (`whole_column` or `found_values`) and how many cells changed.
- If the redaction cannot be completed safely, the check still finishes with its answer; only the copy is missing.

**Before you publish a redacted copy:** read the warnings, review any `undecided` and free-text columns yourself, and open the file to see that it looks right.

---

### 8. File formats and layouts

The service decides the type from the ending of the file name: `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`.

#### JSON

Any of these layouts works:

1. **A list of records:** `[{"Name": "Asha Rao", "Village": "Rampur"}, {"Name": "Vikram Nair", "Village": "Sonpur"}]`
2. **An object holding one list of records:** `{"data": [{"Name": "Asha Rao", …}, …]}`
3. **An object holding several lists of records:** the one named `rows`, `records` or `data` is used, looked for in that order.

- A nested object becomes dotted column names: `{"address": {"city": "Pune"}}` becomes a column `address.city`.
- A list inside a record is kept as text in one cell, so it is still checked.
- In the results, `column` is the JSON key and `row_index` is the record's position in the list, counted from 0.

#### Excel

- `.xlsx` and `.xls` workbooks are read directly.
- **Only the first sheet is checked.** If the workbook has more sheets, a warning names the ones that were not checked. Save another sheet as its own file to check it.
- A workbook that unpacks to more than 500 MB is refused; save the sheet as CSV instead.
- A file named `.xls` or `.xlsx` that is really a text file, which is common in government downloads, is read as CSV. A warning tells you.

#### PDF

- A PDF is checked as text, page by page. If a page already holds text, that text is used. If it is a scan, the service reads it with OCR, in English and Hindi.
- **The answer names pages, not columns:** "Personal data found on 3 page(s): 1, 4, 7." In `results.csv`, the `page` and `line` columns say where each value was read.
- **Only the first 200 pages are read.** A warning tells you when the file has more; split a longer file.
- **OCR makes mistakes.** A blurred digit can hide a phone number. Warnings tell you how many pages were read by OCR and whether the scan was hard to read. Treat a clean result on a poor scan with caution.
- **Names written in Hindi are only partly found.** On a test page of 12 Hindi names the check reported 3 in full, 5 in part and missed 4. Phone numbers, Aadhaar, PAN and email are still found in Hindi text. Review a Hindi document yourself rather than relying on a clean result.
- **Describe the document.** The whole PDF gets one answer, and one mobile number is enough to make it "PII present". An office order that names officers was judged publishable only when its title and description said what it was; see [section 5](#5-describing-your-dataset-this-matters).
- A password-protected PDF cannot be read; remove the password first.
- A redacted copy cannot be made of a PDF yet.

---

### 9. Timing and limits

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

### 10. Common problems

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

### 11. What happens to your data

- **Everything you upload is kept permanently** in the platform's storage: the file, the title and description you sent, and the results. Each check gets its own folder, shown as `s3_folder` in the result. **Only upload data that is allowed to be stored there.**
- The copy on the service machine itself is deleted after about 6 hours.
- The LLM judge runs **on the service's own server**. Your data is not sent to any outside AI service.
- **Anyone who has a run ID can read that run's results**, including `results.csv` and `detections.csv`, which contain the flagged personal data. Run IDs are long and random, so they can't be guessed, but share them only with people who should see the results.

---

### 12. Quick checklist

- [ ] File is `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`, under 100 MB; tables have a header row; a PDF has no password
- [ ] Title and description sent, saying what one row is
- [ ] Waited for `done`, not just for the upload to succeed
- [ ] Read the `warnings`
- [ ] `present` → redact the listed columns; `undecided` → a person reviews them
- [ ] `results.csv` and `detections.csv` handled as personal data
- [ ] If you requested redaction: read the redaction warnings before publishing the redacted copy

Questions, wrong answers or a service that seems down: contact the service owner and include the **run ID**.

---

## Part 2: API reference

Upload a CSV, JSON, Excel or PDF file and find out whether it contains personal data, such as names, phone numbers, emails or Aadhaar/PAN numbers, and whether that data may be published.

The check has three steps:
1. A scan finds candidate values.
2. Rules (Tier 1) decide what they can.
3. A local LLM judge (Tier 3) decides the rest.

The answer is one class per file plus a short table of the flagged columns.

Runs are **asynchronous**: submit the file, poll its status, then read the result.

```
POST /scan  ──>  202 {run_id}  ──>  GET /jobs/{run_id} every 1–2 s  ──>  status "done"  ──>  result
```

Contents:
- [Base URL and access](#base-url-and-access)
- [Quick start](#quick-start)
- [How a file is checked](#how-a-file-is-checked)
- [Endpoints](#endpoints)
- [The result object](#the-result-object)
- [Errors](#errors)
- [Limits and timing](#limits-and-timing)
- [Getting good results](#getting-good-results)
- [File formats](#file-formats)
- [Redaction](#redaction)
- [Data handling](#data-handling)

---

### Base URL and access

| Route in | Base URL | Notes |
|---|---|---|
| ngrok tunnel (for outside users) | `https://skilled-machine-juror.ngrok-free.dev` | HTTPS, on a static domain, so the address stays the same. |
| On the server itself | `http://localhost` | nginx on port 80. |

- **No API key.** If the owner has put a password on the tunnel, send it as HTTP basic auth: `curl -u user:password …`, or `auth=("user", "password")` in Python.
- **ngrok's browser warning.** On a free ngrok account, the first visit from a *browser* shows an ngrok warning page. Click **Visit Site** once. Scripts using curl or Python are not affected. To skip the page anyway, send the header `ngrok-skip-browser-warning: 1`.
- **Try it from a browser:** `<base>/` is an upload page. `<base>/docs` is interactive API documentation, where **Try it out** on `POST /scan` lets you pick a file.

---

### Quick start

**curl** (with [`jq`](https://jqlang.github.io/jq/)):

CSV upload:
```bash
BASE=https://skilled-machine-juror.ngrok-free.dev

RUN=$(curl -s "$BASE/scan" \
  -F file=@hospitals.csv \
  -F title="Directory of District Hospitals, Assam" \
  -F description="Name, address and phone number of each district hospital" \
  | jq -r .run_id)

# poll until the run finishes
until curl -s "$BASE/jobs/$RUN" | jq -e '.status == "done" or .status == "error"' >/dev/null; do
  sleep 2
done

curl -s "$BASE/jobs/$RUN" | jq .result
```

JSON upload with redaction:
```bash
RUN=$(curl -s "$BASE/scan" \
  -F file=@data.json \
  -F title="List of beneficiaries" \
  -F redact=true \
  | jq -r .run_id)

# poll until done, then download the redacted copy
until curl -s "$BASE/jobs/$RUN" | jq -e '.status == "done" or .status == "error"' >/dev/null; do
  sleep 2
done

curl -s "$BASE/jobs/$RUN/files/redacted.csv" > redacted.csv
```

**Python** (`requests`):

```python
import time
import requests

BASE = "https://skilled-machine-juror.ngrok-free.dev"

with open("hospitals.csv", "rb") as fh:
    response = requests.post(
        f"{BASE}/scan",
        files={"file": ("hospitals.csv", fh, "text/csv")},
        data={
            "title": "Directory of District Hospitals, Assam",
            "description": "Name, address and phone number of each district hospital",
        },
    )
response.raise_for_status()
run_id = response.json()["run_id"]

# Note: the content type in the file tuple is ignored; only the file name's ending is checked.

while True:
    job = requests.get(f"{BASE}/jobs/{run_id}").json()
    if job["status"] in ("done", "error"):
        break
    time.sleep(2)

if job["status"] == "error":
    raise SystemExit(f"run failed: {job['error']}")

result = job["result"]
print(result["final_class"], "-", result["message"])
for column in result["columns"]:
    print(f"  {column['column']}: {column['class']} ({column['pii_types']}) - {column['reason']}")
for warning in result["warnings"]:
    print("  warning:", warning)
```

---

### How a file is checked

1. **Scan.**
   - Reads up to `max_rows` rows from the top of the file.
   - Skips columns that hold only numbers, codes, dates or nothing.
   - In the remaining text columns, it looks for personal data with a named-entity model and pattern detectors. Typical types: `PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `AADHAAR_NUMBER` (checksum-validated), `PAN_NUMBER`, `FARMER_REGISTRATION_ID`.
   - Filters then drop common false alarms, such as place names read as people or a column that repeats the same few "names" like a category.
2. **Tier 1: rules.** Each flagged column is classified from:
   - Its **header**, e.g. *Beneficiary*, *Father*, *Patient* versus *District Collector*, *Nodal Officer*.
   - The **values**, e.g. mobile numbers versus office landlines and toll-free numbers, or personal versus government email domains.
   - The **dataset context**, read from the title, catalog title and description you send, and from the file's header row. For example, "directory of officers" reads as official, while "beneficiaries" or "patients" reads as individual records.
3. **Tier 3: LLM judge.** Columns the rules cannot decide go to an LLM running **on the same server**; no data goes to an outside AI service. The judge sees the title, catalog title, description, header row and up to 15 flagged values.
4. **Answer.** The file takes the class of its most serious column, in the order **present > undecided > permissible > false_positive**.

---

### Endpoints

#### `POST /scan`: submit a file

`multipart/form-data`:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `file` | file | **yes** | – | Name must end in `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` (case insensitive); at most 100 MB. |
| `redact` | boolean | no | `false` | `true` requests a redacted copy of the file; see [Redaction](#redaction). |
| `title` | string | no | – | At most 500 characters. **Strongly recommended**; see [Getting good results](#getting-good-results). |
| `catalog_title` | string | no | – | At most 500 characters. The catalog or collection the dataset belongs to. |
| `description` | string | no | – | At most 5,000 characters. What the rows are: people, offices, aggregates… |
| `llm` | boolean | no | `true` | `false` skips the LLM judge. Columns the rules can't decide then stay `undecided`. |
| `max_rows` | integer | no | `50000` | Rows scanned from the top. Values outside 1–50,000 are clamped. Does not apply to a PDF, whose limit is its first 200 pages. |

- Characters in the file name other than letters, digits, `.`, `_` and `-` are replaced with `_`. The result's `file` shows the cleaned name.
- Runs execute one at a time. Other runs wait in a queue.

**202 Accepted**

```json
{
  "run_id": "20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5",
  "job_id": "20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5",
  "status_url": "/jobs/20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5"
}
```

`job_id` is the same value as `run_id`, kept for older clients. Keep the `run_id`: it is the only way to read the result.

#### `GET /jobs/{run_id}`: status and result

```json
{
  "run_id": "20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5",
  "job_id": "20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5",
  "status": "running",
  "stage": "tier3",
  "progress": {"done": 1, "total": 3},
  "filename": "hospitals.csv",
  "queue_position": null,
  "model_loaded": true,
  "error": null,
  "result": null
}
```

| Field | Meaning |
|---|---|
| `status` | `queued`, `running`, `done` or `error`. Poll until it is `done` or `error`. |
| `stage` | While running: `converting` (reading the file; JSON is turned into a table here, and a PDF's pages are read, with `progress` counting pages), `scanning`, `tier1` (rules), `tier3` (LLM judge) or `redacting`. Otherwise `null`. |
| `progress` | During `tier3`: `{"done", "total"}` columns judged so far. Otherwise `null`. |
| `queue_position` | While queued: the run's place in line (1 = next). |
| `model_loaded` | `false` for about a minute after the service restarts. Queued runs wait for it. |
| `error` | Why the run failed, when `status` is `error`. |
| `result` | The [result object](#the-result-object) once `status` is `done`. For a failed run it holds the same `error`. |

Polling every 1–2 seconds is fine. This returns 404 once the run is removed from the server: after about 6 hours, or straight away if the service has restarted since. The permanent copy is unaffected; see [Data handling](#data-handling).

#### `GET /jobs/{run_id}/files/{name}`: download a file

Available once the run has finished. Files are saved as `<file name>_<name>`.

| `name` | Contents |
|---|---|
| `result.json` | The result object. |
| `columns.csv` | The flagged columns: `column, class, pii_types, decided_by, reason`. |
| `results.csv` | **The complete result:** every detection, with what the rules and the LLM judge said about its column. See [results.csv](#resultscsv). **Contains the flagged values themselves.** |
| `detections.csv` | Every detection: `uuid` (file name without extension), `column`, `row_index`, `entity_type`, `entity_text`, `score`, `source`. **Contains the flagged values themselves.** |
| `tier1_column_class.csv` | The rules' verdict per column, with their evidence (including sample values). |
| `tier3_verdicts.csv` | The judge's verdict and reasoning per judged column. Only present when the judge ran. |
| `column_class.csv` | The final verdict per column after both tiers. |
| `redacted.csv` | A redacted copy of the input file. Only present when `redact=true` was sent and redaction succeeded. See [Redaction](#redaction). |

Returns 404 if the name is not in this list, the file was not produced for this run, or the run has been removed.

##### `results.csv`

One row per detection, grouped by column (most serious column first), then in row order. A file with no detections gets a header-only `results.csv`.

| Column | Meaning |
|---|---|
| `column`, `row_index` | Where the value was found. `row_index` counts data rows from 0. |
| `entity_type`, `entity_text` | What was detected, and the value itself. |
| `score`, `source` | Detector confidence, and `presidio` (models) or `regex` (patterns). |
| `tier1_class`, `tier1_reason` | The rules' verdict for the column and why. `undecided` means the rules could not decide. |
| `llm_verdict` | The judge's verdict for the column: `present`, `permissible`, `false_positive`, or `no verdict` if its reply could not be used. Empty when the column was not sent to the judge; only columns the rules left `undecided` are sent. |
| `llm_reasoning` | The end of the judge's reasoning (up to 800 characters). Filled only on the rows whose value was in the judge's prompt (it sees up to 15 distinct values per column), to keep the file small. |
| `final_class`, `decided_by` | The column's final verdict, and whether `tier1` (rules) or `tier3` (LLM judge) decided it. |

The verdicts are per **column**, so they repeat on each of that column's rows.

For a PDF the file starts with two more columns, `page` and `line`: where on the page the value was read. `row_index` then counts the lines of the whole document from 0.

#### `GET /healthz`: service status

```json
{"model_loaded": true, "device": "cuda", "queue_depth": 0,
 "judge": {"ok": true, "detail": null}, "s3": {"ok": true, "detail": null}}
```

- `queue_depth` counts queued plus running runs.
- `judge.ok` is `false` when the LLM judge is down. Runs still work, but columns the rules can't decide stay `undecided`.
- The judge and S3 checks are cached for 30 seconds.

#### Other routes

| Route | |
|---|---|
| `GET /` | The upload page. |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Generated interactive docs and the OpenAPI schema. |
| `GET /jobs/{run_id}/detections.csv`, `GET /jobs/{run_id}/summary.json` | Older aliases for `files/detections.csv` and `files/result.json`. |

---

### The result object

A real run (synthetic data) with a title sent:

```json
{
  "run_id": "20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5",
  "status": "done",
  "file": "synthetic_beneficiaries_v2.csv",
  "final_class": "present",
  "message": "Personal data found in 3 column(s): Beneficiary Name, Father Name, Mobile No. Redact before publishing.",
  "columns": [
    {"column": "Beneficiary Name", "class": "present", "pii_types": "PERSON", "decided_by": "tier1",
     "reason": "header token 'beneficiary' names a private individual regardless of dataset context"},
    {"column": "Father Name", "class": "present", "pii_types": "PERSON", "decided_by": "tier1",
     "reason": "header token 'father' names a private individual, and the dataset is not a directory"},
    {"column": "Mobile No", "class": "present", "pii_types": "PHONE_NUMBER", "decided_by": "tier1",
     "reason": "dataset holds individual records (title matches 'beneficiar')"}
  ],
  "rows_scanned": 200,
  "rows_limit": 50000,
  "tier3": "not_needed",
  "metadata_source": "request",
  "warnings": [],
  "s3_folder": "s3://nic-ogdp-datasets/pii-service-runs/2026-09-26/20260926T135716Z_a7ac1130fcc347ce88dd276d7ac0dff5/"
}
```

| Field | Meaning |
|---|---|
| `final_class` | The answer for the whole file; see the next table. |
| `message` | One line to show a person. |
| `columns` | Only the flagged columns, most serious first. `pii_types` is comma-separated. `decided_by` is `tier1` (rules) or `tier3` (LLM judge). `reason` is the rule's explanation; for a judged column it reads `Tier 3 local LLM judge` (the judge's full reasoning is in `tier3_verdicts.csv`). |
| `rows_scanned`, `rows_limit` | Rows actually read, and the cap that applied. For a PDF, `rows_scanned` counts its lines and `rows_limit` is `null`; see `pdf`. |
| `tier3` | `ran`, `not_needed` (the rules decided everything), `skipped` (`llm=false`), `unavailable` (judge down) or `aborted` (judge failed mid-run). |
| `metadata_source` | `request` if a title, catalog title or description was sent; `filename` if not. |
| `error` | Only when `status` is `error`: why the run failed. The result then carries just `run_id`, `status`, `file`, `error` and `s3_folder`. |
| `warnings` | Plain-language caveats; see below. An empty list means none. |
| `redaction` | Present only when `redact=true` was sent. A summary of the redacted file; see [Redaction](#redaction). |
| `pdf` | Present only for a PDF: `pages` (in the file), `pages_checked`, `pages_ocr` (read by OCR) and `pages_with_findings` (the page numbers the message names). |
| `s3_folder` | Where this run is permanently stored. `null` if storing failed; `s3_error` then says why. |

#### `final_class`

| Value | Meaning | What to do |
|---|---|---|
| `present` | Personal data about private individuals. | Redact the listed columns before publishing. |
| `undecided` | At least one column could not be decided automatically. | Have someone review the listed columns. |
| `permissible` | Personal data, but official or public-role information, such as officers' names or office phone numbers. | May be published. |
| `false_positive` | Something was flagged, but it is not personal data (for example, place names read as names). | Nothing to do. |
| `no_pii_found` | Nothing was detected. | Check `warnings`. "Nothing was scanned" means no column was actually checked. |

#### Warnings

| Warning (start of text) | Cause |
|---|---|
| `No title or description was sent…` | Only the file name and header row were available; see [Getting good results](#getting-good-results). |
| `Nothing was scanned: none of the file's N column(s) holds free text…` | Every column was numbers, codes, dates or empty. |
| `Nothing was scanned: the file has no data rows.` | The file has only a header. |
| `The LLM judge did not run (unavailable \| aborted)…` | The columns it would have decided are left `undecided`. Try again later. |
| `N column(s) over the per-run judge limit of 40 left undecided.` | Very wide file; see [Limits and timing](#limits-and-timing). |
| `NER failed on this file; only the regex detectors ran.` | Names may have been missed; the pattern-based detectors (phone, Aadhaar, PAN, farmer ID) still ran. |
| `Only the first sheet (…) was checked; N other sheet(s) were not…` | An Excel workbook with more than one sheet; see [File formats](#file-formats). |
| `The file is named as an Excel workbook but holds plain text; it was read as CSV.` | See [File formats](#file-formats). |
| `In N free-text column(s) only the values the detectors flagged were replaced…` | Redaction: a name the detectors missed may remain in those columns. |
| `N free-text column(s) could not be redacted value by value…` | Redaction: every filled cell of those columns was replaced instead. |
| `N free-text column(s) were too long to search…` | Redaction: more than 200,000 cells of free text in one run; every filled cell of those columns was replaced instead. |
| `The redacted copy still holds N undecided column(s)…` | Redaction: those columns were not touched and need a person's review. |
| `The redacted copy holds the first sheet only.` | Redaction of a workbook with more than one sheet. |
| `Only the first N of M pages were checked.` | A PDF longer than 200 pages; see [File formats](#file-formats). |
| `No text could be read from N page(s): …` | PDF: those pages are blank, or OCR could not read them. They were not checked. |
| `Nothing was checked: no text could be read from this PDF.` | PDF: `no_pii_found` here means "not examined". |
| `N page(s) were read by OCR…` | PDF: a misread letter or digit can hide a name or a number on those pages. |
| `The OCR was unsure of what it read (average confidence N%)…` | PDF: a poor scan. Treat a clean result with caution. |

---

### Errors

**HTTP errors** mean the request was rejected and no run was created:

| Status | When | Body |
|---|---|---|
| 400 | File name does not end in `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf` | `{"detail": "Only .csv, .json, .xlsx, .xls and .pdf files are accepted"}` |
| 400 | A text field is too long | `{"detail": "title is longer than 500 characters"}` |
| 413 | File over 100 MB | `{"detail": "File exceeds 100 MB"}`. Near the limit, the proxy may answer first with an HTML 413 page. |
| 422 | Missing `file`, or a field of the wrong type | `{"detail": [{"type": "missing", "loc": ["body", "file"], "msg": "Field required", …}]}` |
| 404 | Unknown or removed run, or an unknown download name | `{"detail": "No such run (local results are deleted after 6 hours; the S3 copy is kept)"}` |
| 502 | The service is restarting (about 10 s) | nginx's error page. Retry. |

**Run errors** happen when the request was accepted but the file could not be processed, for example because it is not valid JSON or could not be read as a table; see [Files that cannot be read](#files-that-cannot-be-read). `GET /jobs/{run_id}` then returns `"status": "error"` with the reason in `error`.

A judge that is down is **not** an error: the run finishes with `tier3: "unavailable"`.

---

### Limits and timing

| | |
|---|---|
| File size | 100 MB |
| Rows scanned | 50,000 (first rows of the file). A redacted copy covers every row. |
| Free text searched for a redacted copy | 200,000 cells per run; a column past that is replaced whole |
| Excel workbook | First sheet only; at most 500 MB once unpacked |
| PDF | First 200 pages; 30 minutes to read them |
| Columns judged by the LLM per run | 40; the rest stay `undecided` |
| Concurrency | One run at a time; others queue (`queue_position`) |
| Results on the server | About 6 hours after submission, then 404 |
| Service restart | Queued and running runs are lost; submit them again. Earlier runs return 404. |

Measured on this server:
- The scan of a 200-row file takes about 2 s. A 50,000-row file with long free text can take a few minutes.
- Each column sent to the LLM judge takes about 20 s.
- Turning JSON into a table is quick: a 10 MB file with 24,000 records took under a second.
- A PDF page with its own text takes a few hundredths of a second. A scanned page takes about 2 s when clean and about 3 s when skewed or speckled, three pages at a time.
- A redacted copy costs nothing extra for short-value columns. For a free-text column every cell is searched again, which takes about as long as the scan did: 6.5 minutes for 60,000 cells of sentences, after a 7-minute scan of the same file.
- After a service restart, the models take about a minute to load before the first run starts.

---

### Getting good results

- **Send a title, and a description if you can.** Both tiers use them to tell a directory of officials (publishable) from a list of beneficiaries (not publishable).
  - Without them the file name is used as the title.
  - A name like `test.csv`, `dummy.csv` or `synthetic_people.csv` can mislead the judge. In testing, it read "synthetic" in a file name as "these are not real people".
  - Underscores in file names are read as spaces.
- **Upload the real header row.** Column names carry much of the signal, e.g. *Father Name* or *Mobile No* versus *Office Phone*.
- **Repetitive name columns are treated as categories.** If fewer than about half of a column's values are distinct, names in it are dropped as a controlled vocabulary. A small file that lists the same few people many times can come back `no_pii_found`.
- **Only the first `max_rows` rows are scanned.** Personal data that appears only further down is not seen.
- **A redacted copy only covers columns the check classified `present`.** A column the check did not flag, such as the repetitive name column above, is left as it is. Read the column table before relying on the copy.
- **Treat `undecided` as "needs a person",** not as "probably fine".

---

### File formats

The file's type is taken from the ending of its name: `.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`. The first four are tables and are checked column by column. A PDF is checked as text and answered page by page.

#### JSON

The JSON is turned into a table first, then checked like a CSV. Every record is converted. Accepted layouts:

1. **A list of records:** `[{"Name": "Asha Rao", "Village": "Rampur"}, {"Name": "Vikram Nair", "Village": "Sonpur"}]`
2. **An object holding one list of records:** `{"data": [{"Name": "Asha Rao", …}, …]}`
3. **An object holding several lists of records:** the one named `rows`, `records` or `data` is used, looked for in that order.

- A nested object becomes dotted column names: `{"address": {"city": "Pune"}}` gives a column `address.city`.
- A list inside a record is kept as text in one cell, so it is still scanned.
- In `results.csv` and `detections.csv`, `column` is the JSON key (dotted for nested ones) and `row_index` is the record's position in the list, counting from 0.

#### Excel

- `.xlsx` and `.xls` workbooks are read directly. **Only the first sheet is checked.** When the workbook has more sheets, a warning names the ones that were not checked. To check another sheet, save it as its own file.
- An `.xlsx` that unpacks to more than 500 MB is refused; save the sheet as CSV instead.
- A file named `.xls` or `.xlsx` that actually holds plain text, which is common in government downloads, is read as CSV, and a warning says so.

#### PDF

A PDF is checked as text: every line of every page, with the page it is on.

- **A page's own text is used when it has some.** Most PDFs written by a word processor do, and that text is exact.
- **Pages without text are read by OCR** (tesseract, English and Hindi). This covers:
  - scanned pages, including ones fed in sideways or upside down;
  - a scan with a signature line or page number typed over it;
  - Hindi set in an old non-Unicode font such as Kruti Dev, whose stored text is gibberish.
- **At most the first 200 pages are read.** A warning says so when the file has more.
- **Findings are reported by page.** The message names the pages, `results.csv` gains `page` and `line` columns, and the result carries a `pdf` object; see [The result object](#the-result-object). The one entry in `columns` is called `text`.
- **OCR is not exact.** A misread digit hides a phone number and a misread letter hides a name. A warning says how many pages were read this way, and another when tesseract was unsure of what it read.
- **Names written in Hindi are only partly found,** in a PDF as in any other file: on a test page of 12 Hindi names the check reported 3 in full, 5 in part and missed 4. Phone, Aadhaar, PAN and email are found in Hindi text as in English.
- **The whole document gets one verdict, so send a title and description.** A single mobile number is enough to make a PDF `present`. A test office order naming two officers and a nodal officer's mobile came back `present` with no title, and `permissible` when the title and description said it was an order naming the committee and its nodal officer.
- **A redacted copy cannot be made of a PDF yet;** see [Redaction](#redaction).

#### Files that cannot be read

The run ends with `"status": "error"` and one of these in `error`:

| `error` | Cause |
|---|---|
| `Not valid JSON: <reason> (line L, column C)` | The file is cut off or malformed. |
| `No table found in the JSON: expected a list of records, or an object holding one` | For example a failed download such as `{"status": "FAIL"}`. |
| `The JSON holds no records` | An empty list. |
| `The JSON holds more than one list of records (a, b); name the table rows, records or data` | The service cannot tell which list is the table. |
| `The file is not UTF-8 text` | A JSON file in another encoding. |
| `The workbook unpacks to N MB, over the 500 MB limit; save the sheet as CSV` | |
| `The file is named .xls but holds HTML or XML, not a workbook; save it as CSV` | A web page saved under an Excel name. |
| `Not a valid Excel workbook` | The file is neither a workbook nor text. |
| `The workbook could not be opened (…)` | A damaged or password-protected workbook. |
| `Not a valid PDF file` | The file is named `.pdf` but is not one, or is damaged. |
| `The PDF is password-protected; remove the password and upload it again` | |
| `The PDF has no pages` | |
| `The PDF took too long to read (over 30 minutes); split it into smaller files` | |
| `The PDF could not be read` | Reading it failed part-way. Only that run is affected. |

---

### Redaction

Send `redact=true` with the upload to also get a redacted copy of the file. It is made when at least one column is classified `present`.

```bash
curl -s "$BASE/scan" -F file=@beneficiaries.csv -F title="List of beneficiaries" -F redact=true
# … poll as usual, then:
curl -s -o beneficiaries_redacted.csv "$BASE/jobs/$RUN/files/redacted.csv"
```

#### What is replaced

- **Not for PDFs yet.** `redact=true` on a PDF gives `redaction.status: "not_supported"` and no file; the check itself is unaffected.
- **Only columns classified `present`.** `permissible` and `false_positive` columns are left exactly as they were.
- **`undecided` columns are also left as they were.** A warning names them: the copy is not ready to publish until a person has reviewed them.
- **A short-value column has every filled cell replaced** with a placeholder such as `<PERSON>` or `<PHONE_NUMBER>`.
  - This is a column of names, phone numbers or IDs: its typical filled cell is 40 characters or fewer.
  - Replacing only the detected values is not enough here. The detectors do not catch every name in a column, so the rest would be left behind.
- **A free-text column has the flagged values replaced** inside each cell, and the sentence around them stays: `Called on behalf of <PERSON> about the delayed installment`.
  - This is a column of sentences: its typical filled cell is longer than 40 characters.
  - Every cell is searched again for the redaction, more thoroughly than for the check. So more values can be replaced than `results.csv` lists for that column.
  - A name the detectors miss stays in the text. A warning names the columns this applies to; have a person read them before publishing.
  - If the text cannot be searched, every filled cell of the column is replaced instead, and a warning says so. The same happens past 200,000 cells of free text in one run, to keep the run's time bounded.
- **Every row is covered,** not only the rows that were scanned (up to 50,000).
- Empty cells stay empty.
- **The copy is always a CSV,** also for JSON and Excel uploads. For a workbook it holds the first sheet only, and every cell comes out as its text value: a date cell reads `2024-01-05 00:00:00`.

#### The `redaction` object

The result object carries a `redaction` object only when `redact=true` was sent:

```json
"redaction": {
  "status": "done",
  "message": "2 column(s) redacted in 25 row(s).",
  "rows": 25,
  "columns": [
    {"column": "Name", "method": "whole_column", "cells_redacted": 25},
    {"column": "Remarks", "method": "found_values", "cells_redacted": 7}
  ]
}
```

| Field | Meaning |
|---|---|
| `status` | `done`: a redacted copy is ready. `not_needed`: no column was classified `present`, so there is nothing to redact and no file. `not_supported`: the upload is a PDF; no file. `failed`: no file; see `message`. |
| `message` | One line for people. |
| `rows` | Data rows in the redacted copy. Only when `done`. |
| `columns` | One entry per redacted column. Only when `done`. `method` is `whole_column` (every filled cell replaced) or `found_values` (flagged values replaced inside the cells). `cells_redacted` is how many cells were changed. |

- A redaction that cannot be completed safely never fails the run. The check still finishes with its answer, `redaction.status` is `failed` and no file is offered.
- Before the copy is offered, the service reads it back and checks that it has every row and that no flagged value is left in a redacted column.

#### Download

`GET /jobs/{run_id}/files/redacted.csv`. It exists only when `redaction.status` is `done`; otherwise that address answers 404.

---

### Data handling

- **Everything you upload is stored permanently:** the file, the metadata you sent, the results and the run's log. Each run gets its own folder, `s3://nic-ogdp-datasets/pii-service-runs/<YYYY-MM-DD>/<run_id>/` (encrypted at rest). Only upload data that may be stored there.
- The S3 folder contains:
  - `input/<file>` — the upload as received (`.csv`, `.json`, `.xlsx`, `.xls` or `.pdf`)
  - `converted/<name>.csv` — only for JSON and PDF uploads and for text files named as Excel: the table that was actually scanned. For a PDF it is the text that was read, one row per line
  - `result.json`, `columns.csv`, `results.csv` and the `detail/` files — the results
  - `redacted.csv` — only when a redacted copy was asked for and produced
  - `request.json` and `run.log` — what was sent, and the run's log (no cell values)
- The copy on the server is deleted after about 6 hours.
- The LLM judge runs on the service's own server. No data is sent to external AI services.
- Service logs record column names, counts and verdicts, never cell values. The downloadable result files do contain flagged values: `results.csv`, `detections.csv`, the sample values in the tier files, and the judge's reasoning.
- Anyone who can reach the service and knows a `run_id` can read that run's results. Run IDs are random and can't be guessed, so share them only with people who should see the results.
