# PII Check: User Guide

This guide is for anyone who wants to check a dataset for personal data before publishing it. You don't need to know how the service works inside. It covers:

- the two ways to use it: a web page, or an API for scripts and other systems
- what to send so the check works well
- how to read the answer

For the full technical reference (every field, every error code), see **[API.md](API.md)**.

---

## 1. What the service does

You give it a **CSV file**. It tells you whether the file contains **personal data about individuals**, such as names, mobile numbers, email addresses, Aadhaar or PAN numbers, or farmer IDs, and whether that data **may be published**.

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
  - a `.csv` file, at most **100 MB**
  - with a **header row** (column names) as its first line.

  Excel files are not accepted; save the file as CSV first.

> **First visit from a browser:** you may see an ngrok page saying you are about to visit a site. Click **Visit Site**. It appears once and does not affect scripts.

---

## 3. Option A: the web page (no code)

1. Open `<BASE>/` in your browser.
2. **CSV file:** choose your file.
3. **Dataset title**, **Catalog title** and **Description:** fill in as much as you can. These fields are optional, but they make a real difference; see [section 5](#5-describing-your-dataset-this-matters).
4. Leave **Rows to scan** at 50,000 and **Use the LLM judge** ticked unless you have a reason to change them:
   - Lower the row count for a quick first look at a very large file.
   - Untick the judge if you only want the fast rule-based answer.
5. Click **Check**. The status line shows progress:
   - *Queued — position N*: someone else's file is being checked first.
   - *Queued — models are still loading*: the service restarted recently; wait about a minute.
   - *Scanning…* → *Applying rules…* → *LLM judge… 2/5 columns*
6. When it says **Done**, you'll see the answer badge, a one-line message, any warnings and the column table. Three downloads are offered:
   - `columns.csv`: the column table.
   - `result.json`: the full answer.
   - `detections.csv`: every individual value that was flagged. **This file contains the personal data itself; handle it accordingly.**

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
| `file` | yes | The `.csv` file, at most 100 MB. |
| `title` | no, but recommended | The dataset's name. At most 500 characters. |
| `catalog_title` | no | The collection or catalog it belongs to. At most 500 characters. |
| `description` | no, but recommended | What one row of the data is. At most 5,000 characters. |
| `llm` | no | `true` (default) or `false`. `false` skips the LLM judge, so it's faster, but columns the rules can't decide stay `undecided`. |
| `max_rows` | no | Rows to check from the top of the file. Default and maximum: 50,000. |

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
- `columns.csv`
- `result.json`
- `detections.csv`
- `tier1_column_class.csv`
- `tier3_verdicts.csv` (the judge's reasoning)
- `column_class.csv`

Interactive API docs, where you can try requests in the browser, are at `<BASE>/docs`.

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

---

## 7. Timing and limits

| | |
|---|---|
| Small file (a few hundred rows) | a few seconds, plus about 20 seconds for each column sent to the LLM judge |
| Large file (50,000 rows of long text) | a few minutes |
| File size | 100 MB maximum |
| Rows checked | the first 50,000; personal data that only appears further down is not seen |
| Columns judged by the LLM per check | 40 |
| Checks at once | one; others wait in a queue (you'll see your position) |
| How long a result can be fetched | about 6 hours after you submit it, then the link returns "No such run" |

If the service restarts, checks that were still queued or running are lost. The status link will return "No such run"; just submit the file again.

---

## 8. Common problems

| You see | Why | Fix |
|---|---|---|
| `Only .csv files are accepted` | The file name doesn't end in `.csv`. | Save or rename the file as CSV. |
| `File exceeds 100 MB` (or an HTML "413" page) | The file is too big. | Split it, or check a sample of its rows. |
| `title is longer than 500 characters` | Title or catalog title too long (description allows 5,000). | Shorten it; put the detail in the description. |
| `No such run` | The result is older than about 6 hours, the service restarted, or the run ID is mistyped. | Submit the file again. |
| "502 Bad Gateway" | The service is restarting (about 10–15 seconds). | Wait and retry. |
| Status stuck at *models are still loading* | The service just restarted. | Wait about a minute. |
| A small file with an obvious list of names comes back `no_pii_found` | A column that repeats the same few names many times is treated as a category, like a list of scheme names, not as people. | Check with more rows, or have a person review. |
| Any network error from a script, or an ngrok "endpoint is offline" page | The service or its tunnel is down. | Check the address is exactly `https://skilled-machine-juror.ngrok-free.dev`; if it is, contact the service owner. |

---

## 9. What happens to your data

- **Everything you upload is kept permanently** in the platform's storage: the file, the title and description you sent, and the results. Each check gets its own folder, shown as `s3_folder` in the result. **Only upload data that is allowed to be stored there.**
- The copy on the service machine itself is deleted after about 6 hours.
- The LLM judge runs **on the service's own server**. Your data is not sent to any outside AI service.
- **Anyone who has a run ID can read that run's results**, including `detections.csv`, which contains the flagged personal data. Run IDs are long and random, so they can't be guessed, but share them only with people who should see the results.

---

## 10. Quick checklist

- [ ] File is `.csv`, under 100 MB, with a header row
- [ ] Title and description sent, saying what one row is
- [ ] Waited for `done`, not just for the upload to succeed
- [ ] Read the `warnings`
- [ ] `present` → redact the listed columns; `undecided` → a person reviews them
- [ ] `detections.csv` handled as personal data

Questions, wrong answers or a service that seems down: contact the service owner and include the **run ID**.
