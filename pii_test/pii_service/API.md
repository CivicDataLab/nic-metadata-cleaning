# PII Check API

Upload a CSV and find out whether it contains personal data, such as names, phone numbers, emails or Aadhaar/PAN numbers, and whether that data may be published.

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
- [Data handling](#data-handling)

---

## Base URL and access

| Route in | Base URL | Notes |
|---|---|---|
| ngrok tunnel (for outside users) | `https://skilled-machine-juror.ngrok-free.dev` | HTTPS, on a static domain, so the address stays the same. |
| On the server itself | `http://localhost` | nginx on port 80. |

- **No API key.** If the owner has put a password on the tunnel, send it as HTTP basic auth: `curl -u user:password …`, or `auth=("user", "password")` in Python.
- **ngrok's browser warning.** On a free ngrok account, the first visit from a *browser* shows an ngrok warning page. Click **Visit Site** once. Scripts using curl or Python are not affected. To skip the page anyway, send the header `ngrok-skip-browser-warning: 1`.
- **Try it from a browser:** `<base>/` is an upload page. `<base>/docs` is interactive API documentation, where **Try it out** on `POST /scan` lets you pick a file.

---

## Quick start

**curl** (with [`jq`](https://jqlang.github.io/jq/)):

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

## How a file is checked

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

## Endpoints

### `POST /scan`: submit a file

`multipart/form-data`:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `file` | file | **yes** | – | Name must end in `.csv`; at most 100 MB. |
| `title` | string | no | – | At most 500 characters. **Strongly recommended**; see [Getting good results](#getting-good-results). |
| `catalog_title` | string | no | – | At most 500 characters. The catalog or collection the dataset belongs to. |
| `description` | string | no | – | At most 5,000 characters. What the rows are: people, offices, aggregates… |
| `llm` | boolean | no | `true` | `false` skips the LLM judge. Columns the rules can't decide then stay `undecided`. |
| `max_rows` | integer | no | `50000` | Rows scanned from the top. Values outside 1–50,000 are clamped. |

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

### `GET /jobs/{run_id}`: status and result

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
| `stage` | While running: `scanning`, `tier1` (rules) or `tier3` (LLM judge). Otherwise `null`. |
| `progress` | During `tier3`: `{"done", "total"}` columns judged so far. Otherwise `null`. |
| `queue_position` | While queued: the run's place in line (1 = next). |
| `model_loaded` | `false` for about a minute after the service restarts. Queued runs wait for it. |
| `error` | Why the run failed, when `status` is `error`. |
| `result` | The [result object](#the-result-object) once `status` is `done`. For a failed run it holds the same `error`. |

Polling every 1–2 seconds is fine. This returns 404 once the run is removed from the server: after about 6 hours, or straight away if the service has restarted since. The permanent copy is unaffected; see [Data handling](#data-handling).

### `GET /jobs/{run_id}/files/{name}`: download a file

Available once the run has finished. Files are saved as `<file name>_<name>`.

| `name` | Contents |
|---|---|
| `result.json` | The result object. |
| `columns.csv` | The flagged columns: `column, class, pii_types, decided_by, reason`. |
| `detections.csv` | Every detection: `uuid` (file name without extension), `column`, `row_index`, `entity_type`, `entity_text`, `score`, `source`. **Contains the flagged values themselves.** |
| `tier1_column_class.csv` | The rules' verdict per column, with their evidence (including sample values). |
| `tier3_verdicts.csv` | The judge's verdict and reasoning per judged column. Only present when the judge ran. |
| `column_class.csv` | The final verdict per column after both tiers. |

Returns 404 if the name is not in this list, the file was not produced for this run, or the run has been removed.

### `GET /healthz`: service status

```json
{"model_loaded": true, "device": "cuda", "queue_depth": 0,
 "judge": {"ok": true, "detail": null}, "s3": {"ok": true, "detail": null}}
```

- `queue_depth` counts queued plus running runs.
- `judge.ok` is `false` when the LLM judge is down. Runs still work, but columns the rules can't decide stay `undecided`.
- The judge and S3 checks are cached for 30 seconds.

### Other routes

| Route | |
|---|---|
| `GET /` | The upload page. |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Generated interactive docs and the OpenAPI schema. |
| `GET /jobs/{run_id}/detections.csv`, `GET /jobs/{run_id}/summary.json` | Older aliases for `files/detections.csv` and `files/result.json`. |

---

## The result object

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
| `rows_scanned`, `rows_limit` | Rows actually read, and the cap that applied. |
| `tier3` | `ran`, `not_needed` (the rules decided everything), `skipped` (`llm=false`), `unavailable` (judge down) or `aborted` (judge failed mid-run). |
| `metadata_source` | `request` if a title, catalog title or description was sent; `filename` if not. |
| `error` | Only when `status` is `error`: why the run failed. The result then carries just `run_id`, `status`, `file`, `error` and `s3_folder`. |
| `warnings` | Plain-language caveats; see below. An empty list means none. |
| `s3_folder` | Where this run is permanently stored. `null` if storing failed; `s3_error` then says why. |

### `final_class`

| Value | Meaning | What to do |
|---|---|---|
| `present` | Personal data about private individuals. | Redact the listed columns before publishing. |
| `undecided` | At least one column could not be decided automatically. | Have someone review the listed columns. |
| `permissible` | Personal data, but official or public-role information, such as officers' names or office phone numbers. | May be published. |
| `false_positive` | Something was flagged, but it is not personal data (for example, place names read as names). | Nothing to do. |
| `no_pii_found` | Nothing was detected. | Check `warnings`. "Nothing was scanned" means no column was actually checked. |

### Warnings

| Warning (start of text) | Cause |
|---|---|
| `No title or description was sent…` | Only the file name and header row were available; see [Getting good results](#getting-good-results). |
| `Nothing was scanned: none of the file's N column(s) holds free text…` | Every column was numbers, codes, dates or empty. |
| `Nothing was scanned: the file has no data rows.` | The file has only a header. |
| `The LLM judge did not run (unavailable \| aborted)…` | The columns it would have decided are left `undecided`. Try again later. |
| `N column(s) over the per-run judge limit of 40 left undecided.` | Very wide file; see [Limits and timing](#limits-and-timing). |
| `NER failed on this file; only the regex detectors ran.` | Names may have been missed; the pattern-based detectors (phone, Aadhaar, PAN, farmer ID) still ran. |

---

## Errors

**HTTP errors** mean the request was rejected and no run was created:

| Status | When | Body |
|---|---|---|
| 400 | File name does not end in `.csv` | `{"detail": "Only .csv files are accepted"}` |
| 400 | A text field is too long | `{"detail": "title is longer than 500 characters"}` |
| 413 | File over 100 MB | `{"detail": "File exceeds 100 MB"}`. Near the limit, the proxy may answer first with an HTML 413 page. |
| 422 | Missing `file`, or a field of the wrong type | `{"detail": [{"type": "missing", "loc": ["body", "file"], "msg": "Field required", …}]}` |
| 404 | Unknown or removed run, or an unknown download name | `{"detail": "No such run (local results are deleted after 6 hours; the S3 copy is kept)"}` |
| 502 | The service is restarting (about 10 s) | nginx's error page. Retry. |

**Run errors** happen when the request was accepted but the file could not be processed, for example because it could not be read as CSV. `GET /jobs/{run_id}` then returns `"status": "error"` with the reason in `error`.

A judge that is down is **not** an error: the run finishes with `tier3: "unavailable"`.

---

## Limits and timing

| | |
|---|---|
| File size | 100 MB |
| Rows scanned | 50,000 (first rows of the file) |
| Columns judged by the LLM per run | 40; the rest stay `undecided` |
| Concurrency | One run at a time; others queue (`queue_position`) |
| Results on the server | About 6 hours after submission, then 404 |
| Service restart | Queued and running runs are lost; submit them again. Earlier runs return 404. |

Measured on this server:
- The scan of a 200-row file takes about 2 s. A 50,000-row file with long free text can take a few minutes.
- Each column sent to the LLM judge takes about 20 s.
- After a service restart, the models take about a minute to load before the first run starts.

---

## Getting good results

- **Send a title, and a description if you can.** Both tiers use them to tell a directory of officials (publishable) from a list of beneficiaries (not publishable).
  - Without them the file name is used as the title.
  - A name like `test.csv`, `dummy.csv` or `synthetic_people.csv` can mislead the judge. In testing, it read "synthetic" in a file name as "these are not real people".
  - Underscores in file names are read as spaces.
- **Upload the real header row.** Column names carry much of the signal, e.g. *Father Name* or *Mobile No* versus *Office Phone*.
- **Repetitive name columns are treated as categories.** If fewer than about half of a column's values are distinct, names in it are dropped as a controlled vocabulary. A small file that lists the same few people many times can come back `no_pii_found`.
- **Only the first `max_rows` rows are scanned.** Personal data that appears only further down is not seen.
- **Treat `undecided` as "needs a person",** not as "probably fine".

---

## Data handling

- **Everything you upload is stored permanently:** the file, the metadata you sent, the results and the run's log. Each run gets its own folder, `s3://nic-ogdp-datasets/pii-service-runs/<date>/<run_id>/` (encrypted at rest). Only upload data that may be stored there.
- The copy on the server is deleted after about 6 hours.
- The LLM judge runs on the service's own server. No data is sent to external AI services.
- Service logs record column names, counts and verdicts, never cell values. The downloadable result files do contain flagged values: `detections.csv`, the sample values in the tier files, and the judge's reasoning.
- Anyone who can reach the service and knows a `run_id` can read that run's results. Run IDs are random and can't be guessed, so share them only with people who should see the results.
