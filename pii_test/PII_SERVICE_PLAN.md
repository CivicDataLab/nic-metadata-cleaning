# PII Scan Service — Plan

A small FastAPI app + one static webpage: user uploads a CSV, the existing
LOT-2 scan pipeline runs over it, and the detections/summary come back as
downloads. No S3, no DuckDB — this is `run_pii_s3.py --path` with a browser
in front of it.

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

DuckDB writes, S3, LOT bookkeeping, multi-GPU, accounts/user management,
scan history UI.
