"""
Gunicorn config for the PII scan service.

    .venv/bin/gunicorn -c pii_test/pii_service/gunicorn.conf.py app:app

Gunicorn is the supervisor here (restart-on-crash, pidfile, graceful
shutdown); the app itself still runs on uvicorn via the worker class.
"""

import os

SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))

# So "app:app" resolves; scanner re-pins the process cwd to the repo root
# at import, exactly as in a dev run.
chdir = SERVICE_DIR

# A unix socket by default: nginx and gunicorn sit on the same host, so a
# TCP port only adds a way to reach the service without going through nginx.
# Set PII_SERVICE_BIND=127.0.0.1:8000 to go back to a port (handy for curl
# during development).
#
# Under systemd the unit points this at /run/pii-scan/gunicorn.sock, which
# lives on tmpfs and is recreated per boot; the default here keeps a manual
# run self-contained in the service directory.
bind = os.environ.get("PII_SERVICE_BIND", f"unix:{SERVICE_DIR}/gunicorn.sock")

# 0o007 -> socket mode 0770 (AF_UNIX sockets are created 0777; the umask
# only clears the "other" bits). Gunicorn chowns it to this process uid:gid at
# bind time, so with "Group=www-data" in the unit the socket comes out
# ubuntu:www-data and nginx can connect while nothing else on the box can.
# A stale socket file from a SIGKILLed master is removed automatically.
umask = 0o007

# NEVER raise workers. One GPU, one ~2.5 GB model copy per process, and the
# job store/queue live in process memory -- a second worker would answer
# polls for jobs it has never heard of.
workers = 1
worker_class = "uvicorn_worker.UvicornWorker"

# The async worker heartbeats from the event loop, which stays responsive
# during scans (they run in a thread), so this is only a hang backstop.
timeout = 120
# On restart/reload, give an in-flight scan time to finish.
graceful_timeout = 300
keepalive = 5

# No max_requests recycling: a worker restart reloads the models (~1 min of
# 503s), so recycle only deliberately (systemctl restart / kill -HUP).

# Gunicorn's own lifecycle + access lines. The app's log (scans, jobs,
# sweeps) stays in pii_service.log via scanner.configure_logging().
errorlog = os.path.join(SERVICE_DIR, "gunicorn.log")
accesslog = os.path.join(SERVICE_DIR, "gunicorn.log")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'
pidfile = os.path.join(SERVICE_DIR, "gunicorn.pid")
