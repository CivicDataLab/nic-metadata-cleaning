# PII scan service

Web front end for the LOT 2 scan pipeline: upload a CSV, download the
detections and a summary. Design and rationale: `../PII_SERVICE_PLAN.md`.

## Run (production: gunicorn)

    .venv/bin/gunicorn -c pii_test/pii_service/gunicorn.conf.py app:app

Gunicorn supervises (respawns a crashed worker, pidfile, graceful stop);
the app runs on uvicorn inside it via `uvicorn_worker.UvicornWorker`.
A worker respawn reloads the models. Measured on this host, a
`systemctl restart pii-scan` costs ~15 s end to end: ~10 s where the socket
is absent and nginx answers 502, then a few seconds of
`{"model_loaded": false}` before it is ready.

It binds a **unix socket**, not a TCP port: `gunicorn.sock` in this
directory for a manual run, `/run/pii-scan/gunicorn.sock` under systemd.
nginx connects to that; nothing reaches the app any other way.

    curl --unix-socket pii_test/pii_service/gunicorn.sock http://localhost/healthz

Environment knobs:

    PII_SERVICE_BIND=127.0.0.1:8000   # go back to a TCP port (dev/curl convenience)
    PII_SERVICE_BIND=unix:/run/pii-scan/gunicorn.sock   # what the unit sets
    PII_SERVICE_DEVICE=cpu            # leave the GPU to a corpus run (~10x slower)

To survive reboots, install the shipped unit (needs sudo):

    sudo cp pii_test/pii_service/pii-scan.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now pii-scan

The unit runs as `ubuntu` with `Group=www-data`, so the socket comes out
`ubuntu:www-data` mode 0770 -- nginx can connect, other users cannot. It also
takes `RuntimeDirectory=pii-scan`, so `/run/pii-scan` is created at start and
removed at stop and no socket can outlive the process. If nginx runs as some
other user on your box (`ps -o user= -C nginx`), change `Group=`.

## Installed on this host (2026-08-20)

nginx 1.18.0 and the systemd unit are installed and enabled at boot:

| | |
|---|---|
| service | `pii-scan.service` -> `/etc/systemd/system/` (enabled) |
| socket | `/run/pii-scan/gunicorn.sock`, `ubuntu:www-data` 0770 |
| nginx site | `/etc/nginx/sites-available/pii-scan`, symlinked into `sites-enabled` |
| default site | **removed** from `sites-enabled` -- `server_name _` would clash |
| nginx logs | `/var/log/nginx/pii-scan.{access,error}.log` |
| listening | `0.0.0.0:80`; ufw inactive, so exposure is whatever the cloud security group allows |

    sudo systemctl status pii-scan       # service state
    sudo systemctl restart pii-scan      # ~15 s, see above
    curl localhost/healthz               # through nginx

> **No authentication.** Anyone who can reach port 80 can upload a CSV and
> download any result whose job ID they hold. Job IDs are UUID4 so they are
> not guessable, but that is not access control. Before the port is opened
> beyond the team, add TLS (certbot) and a gate -- `allow`/`deny` by IP, or
> uncomment the `auth_basic` lines in `nginx-pii-scan.conf` and create
> `/etc/nginx/.htpasswd` with `sudo htpasswd -c /etc/nginx/.htpasswd <user>`.

## nginx

`nginx-pii-scan.conf` is a ready site config pointing at that socket, with
`client_max_body_size 100m` to match the app's upload cap. Install steps are
in its header. It is deliberately left open (no TLS, no auth) since the port
is not exposed yet -- both are flagged inline for when it is.

## Run (dev)

    .venv/bin/python pii_test/pii_service/app.py --port 8000   # --no-gpu, --host

## Logs

- `pii_service.log` -- the app: jobs, scans, sweeps (plus stderr in dev runs)
- `gunicorn.log` -- gunicorn lifecycle + HTTP access lines

A stale `gunicorn.sock` left by a SIGKILLed master needs no cleanup:
gunicorn removes a leftover socket file before binding.

## Notes

- **workers = 1 is load-bearing**: one GPU, one ~2.5 GB model copy per
  process, and the job store/queue live in process memory. A second worker
  would answer polls for jobs it has never heard of.
- Job dirs live in `jobs/` next to this file and are deleted after 6 h
  (uploads are PII). `jobs/`, logs, pid and socket files are gitignored.
- A worker crash loses queued/running jobs from memory (result files on
  disk survive until the sweep); the uploader just resubmits.
- No DuckDB, no S3. Same code path as `run_pii_s3.py --path`, so the CLI
  and the service always agree.
