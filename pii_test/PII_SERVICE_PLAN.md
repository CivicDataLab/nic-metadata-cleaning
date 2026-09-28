# PII Scan Service — Plan

A small FastAPI app + one static webpage: user uploads a CSV, the existing
LOT-2 scan pipeline runs over it, and the detections/summary come back as
downloads. No S3, no DuckDB — this is `run_pii_s3.py --path` with a browser
in front of it.

> **Superseded in part by Phase 5 (2026-09-26, below).** The service now runs
> the full pipeline -- scan, Tier 1, Tier 3 -- as its own API pipeline,
> separate from the script run, and stores every run in S3. The sections up
> to "Out of scope" describe the scan-only first version and are kept for
> the reasoning behind the queue, worker and deployment choices, which
> still hold.

## Difficulty

Low. The hard part (the pipeline) already exists as a callable:
`run_pii_s3.scan_local_file(path)` takes a local CSV and returns
`{detections, pii_found, pii_flag_reason, pii_types, entity_count,
rows_scanned, columns_scanned, columns_skipped, error}` — exactly what the
service needs to serve. `rescan_sample.py` already proved the embedding
pattern: set the module globals (`_analyzer`, `_gpu_ner`, `_max_rows`,
`_ner_batch_size`) once, then call the scan function repeatedly.

Estimated new code: ~300 lines Python + ~120 lines HTML/JS. One day
including testing. `fastapi`, `uvicorn`, `python-multipart` need installing
(none are in the venv yet).

## Architecture

```
browser ── POST /scan (multipart CSV) ──> FastAPI (uvicorn, 1 worker)
   │                                          │  save to jobs/<id>/input.csv
   │<── {job_id} ─────────────────────────────┤  enqueue
   │                                          ▼
   │── GET /jobs/<id> (poll ~1s) ──>   single scan worker thread
   │<── queued(pos)/running/done ───   (owns the GPU; runs scan_local_file)
   │                                          │  write detections.csv, summary.json
   │── GET /jobs/<id>/detections.csv ──> FileResponse
```

Decisions, and why:

1. **Job queue, not a synchronous request.** A 250-row free-text file takes
   ~9 s on the T4; a 50k-row one takes minutes. Holding an HTTP request open
   that long fights every timeout in the chain (uvicorn, nginx later,
   browser). A job ID + 1-second polling is ~30 lines extra and removes the
   whole class of problem. No websockets — polling is fine at this scale.

2. **One uvicorn worker, one scan thread.** The models live on one GPU and
   load once (~1 min, ~2–3 GB VRAM). Multiple uvicorn workers would each
   load their own copy; concurrent scans would interleave on the GPU for no
   throughput gain. So: `uvicorn app:app --workers 1`, an
   `asyncio.Queue`, and a single consumer running the scan via
   `asyncio.to_thread`. Uploads and polls stay responsive because the event
   loop never runs the scan itself. Queue position is reported to the page.

3. **In-memory job store, files on disk.** `jobs: dict[id, Job]` plus
   `jobs/<id>/` (input.csv, detections.csv, summary.json). A restart loses
   the queue — acceptable for an internal tool; the completed files survive
   and a TTL sweep deletes each job dir after N hours (uploads contain PII
   by definition; keeping them forever is the real risk, not losing them).

4. **Plain static HTML, no build step.** One page served by FastAPI's
   `StaticFiles` now; nginx can take over `/static` later without changes.
   `fetch` upload, poll loop, then two download links + a small summary
   table (flag, reason, types, columns scanned/skipped).

## API

| Route | Method | Body / Returns |
|---|---|---|
| `/` | GET | the upload page |
| `/scan` | POST | multipart `file`; optional `max_rows` form field → `{job_id}` (400 on non-CSV/oversize) |
| `/jobs/{id}` | GET | `{status: queued|running|done|error, queue_position?, summary?, error?}` |
| `/jobs/{id}/detections.csv` | GET | per-detection CSV (same columns as `--path` output) |
| `/jobs/{id}/summary.json` | GET | flag, reason, types, counts, columns scanned/skipped, rows_scanned |
| `/healthz` | GET | `{model_loaded: bool, queue_depth: int}` — for nginx/monitoring |

## Integration details (the actual gotchas)

- **Logging hijack.** `run_pii_s3.py` calls `configure_logging(LOT1_LOG_PATH)`
  at import with `force=True`, pointing the *root* logger at
  `pii_test/pii_s3.log` with a file-only handler. The service must
  re-configure logging *after* importing it (own log file + stderr), or
  every uvicorn access log vanishes into pii_s3.log.
- **Import convention.** Same as the other scripts:
  `sys.path.insert(0, "pii_test")`, run from the repo root. Gazetteers and
  the frequency blocklist load relative to `pii_test/` and just work.
- **Row cap.** Default `max_rows` = 50,000 (bounded worst case ≈ a few
  minutes), overridable per upload down to e.g. 250 for a quick look.
  `summary.json` always reports `rows_scanned` vs file rows so truncation
  is visible.
- **Upload cap.** Reject > 100 MB at the route (and mirror with
  `client_max_body_size` when nginx arrives). Reject non-`.csv` names;
  parse failures from `read_csv_robust` come back as job `error`, not 500.
- **GPU contention.** A corpus run (`--lot2`) and the service share one T4.
  Fine occasionally, slow together. The service should not be up during a
  full LOT re-run, or should be started `--no-gpu` (CPU scan works, ~10×
  slower).
- **No auth yet = anyone who reaches the port can upload PII and download
  anyone's results by job ID.** Job IDs as UUID4 makes results
  unguessable, which is enough while the port is firewalled to the team.
  Before it's opened wider: a shared bearer token checked in one
  dependency, TLS at nginx.
- **What is stored, and for how long.** Uploads are user PII: keep job dirs
  under `pii_test/pii_service/jobs/` (gitignored), sweep on a
  background task every 15 min, delete dirs older than 6 h. Never log cell
  contents — the pipeline already only logs column names.

## Code layout

```
pii_test/pii_service/
  app.py          FastAPI app: routes, job store, queue, TTL sweep  (~200 lines)
  scanner.py      startup: import run_pii_s3, build_analyzer once,
                  set module globals; scan_one(path, max_rows) wrapper (~60 lines)
  static/index.html   upload form, poll loop, results table          (~120 lines)
pii_test/pii_service/jobs/  runtime job dirs (gitignored, TTL-swept)
```

`scanner.py` deliberately reuses `scan_local_file` unchanged — the service
must give the same answer as the CLI on the same file, and the harness/
fixtures keep guarding one code path, not two.

## Phases

1. **Serve it** — deps in venv, `scanner.py` + `app.py` + page, manual test
   with the aadhaar fixture and 2023_Q4.csv; confirm identical output to
   `run_pii_s3.py --path`. *(most of the day)*
2. **Harden** — size/row caps, TTL sweep, `/healthz`, error surfaces on the
   page, systemd unit so it restarts and survives logout. *(1–2 h)*
3. **Expose** — *done 2026-08-20*: nginx installed, `pii-scan` site enabled
   against the unix socket, systemd unit enabled at boot, 100 MB cap
   matched on both sides. Remaining: TLS and an auth gate before the port
   is opened beyond the team.
4. **Optional later** — a "download redacted CSV" button reusing
   `generate_redacted.py` logic; batch upload of several files into one job.

## Out of scope

DuckDB writes, LOT bookkeeping, multi-GPU, accounts/user management,
scan history UI. (S3 moved into scope with Phase 5: one folder per run.)

## Phase 5 — full pipeline API, results in S3 (2026-09-26)

The service became a platform feature: anyone uploads a CSV and gets back
whether it holds personal data, decided by detection, **Tier 1** rules and
the **Tier 3** LLM judge. Usage and routes: `pii_service/README.md`.

**Separate from the script run.** `pii_classify_pipeline.py` classifies
*our* corpus with metadata from `metadata.db`; an upload is an unrelated
dataset. So the API has its own orchestration, `pii_service/api_pipeline.py`,
and none of `pii_classify_pipeline.py`, `pii_classify.py`, `pii_tier3.py`,
`run_pii_s3.py`, `pii_filters.py` was edited for it. It imports only the
building blocks and feeds them its own inputs:

| Step | Building block (unchanged) | API-specific input |
|---|---|---|
| scan | `run_pii_s3.scan_local_file` via `scanner.scan_one` | corpus name blocklist (`CROSS_DATASET_COUNTS`) cleared for this process |
| Tier 1 | `pii_classify.classify_detections` | title / catalog title / description **from the POST request**; header row read from the upload |
| Tier 3 | `pii_tier3.build_prompt`, `judge`, `to_rows`, `apply_verdicts` | `build_pairs` passes the request's catalog title + description into the prompt (the script's version has none to pass) |
| decide | — (the API's own order) | present > undecided > permissible > false_positive: unlike the corpus roll-up, an unreviewed column outranks `permissible` |

What deliberately differs from the script run: the cross-dataset blocklist
is off (it would drop a private person who shares a name with someone
frequent in *our* data); metadata comes from the request; Tier 1's
corpus-frequency test sees one dataset and never fires. Tier 1's
vocabularies and the hand-curated gazetteers are kept -- they are general
knowledge, not corpus statistics.

**Output kept simple.** One `final_class` per file (present / undecided /
permissible / false_positive / no_pii_found; the most serious column decides, in
that order), a fixed
one-line `message`, a table of flagged columns (column, class, types,
decided_by, reason) and plain-language `warnings` (judge did not run, no
metadata sent, nothing scanned, NER degraded). Full evidence goes to
`detail/` for audit, not to the page.

**Judge down is not a failure.** Runs finish on Tier 1; the columns the judge
would have decided stay `undecided` and `tier3` says `unavailable` (or
`skipped` / `aborted`). At most 40 columns per run go to the judge, bounding
how long one wide file can hold the single worker.

**S3, one folder per run:**
`s3://nic-ogdp-datasets/pii-service-runs/<YYYY-MM-DD>/<run_id>/` holding
the input, `request.json`, `result.json`, `columns.csv`, `detail/` and the
run's own `run.log` (a handler filtered to the worker thread; never cell
values). `run_id = <UTC time>_<uuid4 hex>` -- sortable and unguessable, and
the job id in the API. Kept forever (no lifecycle rule, by decision); failed
runs are stored too; an upload failure is retried once, then reported in
`s3_error` without failing the run. The local copy keeps its 6 h sweep.

**GPU.** The judge moves to a systemd unit (`tier3-judge.service`) at
`--gpu-memory-utilization 0.65` (~10 GB) so the scan models (~2–3 GB peak)
fit beside it on the T4 -- a CUDA OOM inside vLLM's engine loop kills the
whole server. The dev port moved from 8000 (the judge's) to 8080.

**Verified 2026-09-26** (dev server on :8080, synthetic data only, judge
down): request title reached Tier 1 (`individual_records`, R10); no-metadata
upload came back `undecided` with both warnings; S3 folders complete and
SSE-encrypted; run logs held none of the 872 input values; unreachable
bucket -> run `done` with `s3_error`; garbage file -> `no_pii_found` plus a
"nothing was scanned" warning. 12 unit tests (`pii_service/tests/`) stub
the scan and judge.

**Deployed 2026-09-26 14:24 UTC** (the units were installed with sudo:
`tier3-judge` at 0.65, `pii-scan` restarted). A live run through nginx
judged one column in ~20 s (GPU 11.3 of 15.4 GB with both loaded), and
`/healthz` reported the judge and S3 as ok. The run also exposed three fixes,
which take effect at the next `pii-scan` restart:
- the `tier3` stage is now reported before the first verdict, not after it;
- the file-name title reads `_` as spaces, since the upload sanitizer turns
  spaces into `_` and that defeated Tier 1's word-boundary patterns;
- the file class ranks `undecided` above `permissible`.

The judge was right on that run, given what it saw: with no title sent, the
file name `synthetic_people` became the title, and it answered
`false_positive` ("given the title, it's more likely synthetic"). File names
steer it, so API.md tells callers to send a real title. Still unmeasured: GPU
headroom under a 50k-row scan while the judge is loaded.

**Access (checked 2026-09-26).**
- nginx listens on `0.0.0.0:80`, and a request to the instance's public IP
  from the box itself succeeded. That request goes out through the internet
  gateway, where the security group applies, so port 80 is open beyond this
  host.
- The instance role cannot read the security group rules, so whether the
  whole internet is allowed has to be checked in the console.
- There is no HTTPS on 443 and no authentication.
- `ngrok-pii.service` adds an HTTPS URL through an outbound tunnel.

**Public HTTP closed (2026-09-26).** Once ngrok was up (a static
`*.ngrok-free.dev` domain forwarding to `localhost:80`), nginx was bound to
`127.0.0.1:80`, which needed a restart, not a reload.
- The public IP now refuses port 80.
- The tunnel and `localhost` still answer.
- Public exposure is SSH plus the tunnel. The judge's internal engine port
  36697 listens on all interfaces but is blocked by the security group.
