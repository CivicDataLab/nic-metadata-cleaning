# PII API

Upload a CSV -- optionally with what the dataset is -- and get back whether
it holds personal data: detection, Tier 1 rules, then the Tier 3 LLM judge.
Every run is stored in its own S3 folder. Design and rationale:
`../PII_SERVICE_PLAN.md`.

**Separate from the script pipeline.** `pii_classify_pipeline.py` classifies
*our* corpus, with metadata from `metadata.db`. Uploads are unrelated
datasets, so the API has its own orchestration (`api_pipeline.py`). It
imports the scan, Tier 1's rules and Tier 3's judge unchanged, feeds them
the metadata sent with the request, and switches off corpus statistics (the
cross-dataset name blocklist). None of the script-side files is edited to
serve the API.

## Using the API

For people outside the team, start with the walkthrough in **[USER_GUIDE.md](USER_GUIDE.md)**: the web page, a minimal API client, how to describe a dataset, and how to read the answer. Full reference for API users: **[API.md](API.md)**, covering endpoints, fields, the result object, errors, limits and data handling. In short:

    curl -F file=@hospitals.csv -F title="Directory of District Hospitals" http://localhost/scan
    # -> 202 {"run_id": "..."}; then poll GET /jobs/<run_id> until status is done/error

`GET /docs` serves FastAPI's interactive docs, generated from the code.

## S3: one folder per run

    s3://nic-ogdp-datasets/pii-service-runs/
      README.txt
      <YYYY-MM-DD>/<run_id>/            run_id = <UTC time>_<uuid4 hex>
        input/<file>.csv                the upload as received (contains PII)
        request.json                    metadata, options, timings
        result.json                     the answer above
        columns.csv                     the flagged columns as a table
        detail/detections.csv           per detection
        detail/tier1_column_class.csv   Tier 1 rows with their evidence
        detail/tier3_verdicts.csv       judge verdict + reasoning (when it ran)
        detail/column_class.csv         final rows after both tiers
        run.log                         that run's log lines (no cell values)

- Folders are kept forever; there is no lifecycle rule on the prefix.
- Failed runs are uploaded too, with `status: "error"` in `result.json`.
- If the upload fails, the service retries once. After that the run still finishes, with `s3_folder: null` and `s3_error` set, and the full error goes to `pii_service.log`.
- Credentials come from the instance role, and the bucket encrypts at rest (SSE-S3).
- Override the destination with `PII_RUNS_BUCKET` / `PII_RUNS_PREFIX`.

## Tier 3 judge

The judge is vLLM serving Qwen3-8B-AWQ on `127.0.0.1:8000`, installed as its own unit:

    sudo cp pii_test/pii_service/tier3-judge.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now tier3-judge
    curl -s 127.0.0.1:8000/v1/models        # lists tier3-judge once warm (~1 min)

- It runs at `--gpu-memory-utilization 0.65` (~10 GB), not the 0.80 used by hand, so the service's scan models fit beside it on the T4.
- `pii-scan.service` `Wants=` it. If the judge is down, runs still finish on Tier 1 alone.
- Point the API at another judge with `PII_JUDGE_ENDPOINT` / `PII_JUDGE_MODEL`.

## Sharing it outside this server: ngrok

`ngrok-pii.service` runs `ngrok http 80 --inspect=false`, a tunnel to nginx that gives an `https://…ngrok-free.dev` URL. ngrok connects out from this server, so it needs no open inbound port. The binary is at `~/.local/bin/ngrok` (v3, installed 2026-09-26).

    ngrok config add-authtoken <token>      # once, in a terminal here (dashboard.ngrok.com)
    sudo cp pii_test/pii_service/ngrok-pii.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now ngrok-pii
    curl -s 127.0.0.1:4040/api/tunnels | grep -o 'https://[^"]*'     # the public URL

- **Stable URL:** the unit uses the account's static domain, `--url https://skilled-machine-juror.ngrok-free.dev`, so the address survives restarts.
- **Password:** the unit header shows a traffic policy that adds basic auth. Keep that file outside the repo, because it holds the credentials.
- **Inspector off:** `--inspect=false` stops the agent's local inspector from keeping uploaded CSVs in memory.
- **Browser warning:** on a free account, browsers get ngrok's warning page once. API clients are not affected; see API.md.

## Run (production: gunicorn)

    .venv/bin/gunicorn -c pii_test/pii_service/gunicorn.conf.py app:app

Gunicorn supervises the process: it respawns a crashed worker, writes a pidfile and stops gracefully. The app runs on uvicorn inside it via `uvicorn_worker.UvicornWorker`. A worker respawn reloads the models. Measured on this host, `systemctl restart pii-scan` costs ~15 s end to end: ~10 s while the socket is absent and nginx answers 502, then a few seconds of `{"model_loaded": false}` before it is ready.

It binds a **unix socket**, not a TCP port: `gunicorn.sock` in this directory for a manual run, `/run/pii-scan/gunicorn.sock` under systemd. nginx connects to that; nothing reaches the app any other way.

    curl --unix-socket pii_test/pii_service/gunicorn.sock http://localhost/healthz

Environment knobs:

    PII_SERVICE_BIND=127.0.0.1:8080   # go back to a TCP port (not 8000: that's the judge)
    PII_SERVICE_BIND=unix:/run/pii-scan/gunicorn.sock   # what the unit sets
    PII_SERVICE_DEVICE=cpu            # leave the GPU to a corpus run (~10x slower)
    PII_JUDGE_ENDPOINT, PII_JUDGE_MODEL   # Tier 3 judge (default 127.0.0.1:8000, tier3-judge)
    PII_RUNS_BUCKET, PII_RUNS_PREFIX      # S3 run folders (default nic-ogdp-datasets, pii-service-runs)

To survive reboots, install the shipped unit (needs sudo):

    sudo cp pii_test/pii_service/pii-scan.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now pii-scan

The unit runs as `ubuntu` with `Group=www-data`, so the socket comes out `ubuntu:www-data` mode 0770: nginx can connect, other users cannot. It also uses `RuntimeDirectory=pii-scan`, so `/run/pii-scan` is created at start and removed at stop, and no socket can outlive the process. If nginx runs as some other user on your box (`ps -o user= -C nginx`), change `Group=`.

## Installed on this host (2026-08-20)

nginx 1.18.0 and the systemd unit are installed and enabled at boot:

| | |
|---|---|
| service | `pii-scan.service` -> `/etc/systemd/system/` (enabled) |
| socket | `/run/pii-scan/gunicorn.sock`, `ubuntu:www-data` 0770 |
| nginx site | `/etc/nginx/sites-available/pii-scan`, symlinked into `sites-enabled` |
| default site | **removed** from `sites-enabled` (`server_name _` would clash) |
| nginx logs | `/var/log/nginx/pii-scan.{access,error}.log` |
| listening | `127.0.0.1:80` only (since 2026-09-26). The public IP no longer answers HTTP; outside users come in through the ngrok tunnel. ufw is inactive, and the security group still allows port 80, but nothing listens on it publicly. |

    sudo systemctl status pii-scan       # service state
    sudo systemctl restart pii-scan      # ~15 s, see above
    curl localhost/healthz               # through nginx

> **No authentication.** Anyone with the ngrok URL can upload a CSV, and can download any result whose run ID they hold. Run IDs end in a UUID4 and cannot be guessed, but that is not access control. To gate it, add the basic-auth traffic policy described in `ngrok-pii.service`. Then the only public way in carries a password, and ngrok already provides the TLS.

## nginx

`nginx-pii-scan.conf` is a ready site config pointing at that socket, with `client_max_body_size 100m` to match the app's upload cap. Install steps are in its header. It listens on loopback only: ngrok provides the public HTTPS endpoint, so nginx needs neither TLS nor its own auth.

## Run (dev) and tests

    .venv/bin/python pii_test/pii_service/app.py --port 8080   # --no-gpu, --host
    .venv/bin/python -m unittest discover -s pii_test/pii_service/tests -v

The tests stub the scan and the judge (no GPU, server or S3 needed). Tier 1 and the Tier 3 plumbing are the real modules.

## Logs

- `pii_service.log`: the app (runs, sweeps, S3 uploads), plus stderr in dev runs.
- `gunicorn.log`: gunicorn lifecycle + HTTP access lines.
- `jobs/<run_id>/run.log`: one run's own lines, also uploaded to its S3 folder.

A stale `gunicorn.sock` left by a SIGKILLed master needs no cleanup: gunicorn removes a leftover socket file before binding.

## Notes

- **workers = 1 is load-bearing**: one GPU, one ~2.5 GB model copy per process, and the job store/queue live in process memory. A second worker would answer polls for jobs it has never heard of. Runs execute one at a time on a single `pii-run` thread.
- Local run dirs live in `jobs/` next to this file and are deleted after 6 h (uploads are PII). `jobs/`, logs, pid and socket files are gitignored.
- A worker crash loses queued and running jobs from memory. Finished runs are already in S3; the uploader resubmits the rest.
- **Differences from the script run**, all deliberate:
  - The cross-dataset name blocklist is off.
  - Metadata comes from the request, not `metadata.db`.
  - Tier 1's corpus-frequency test sees a single dataset, so it never fires.
  - The scan code itself is the same `run_pii_s3.scan_local_file`.
