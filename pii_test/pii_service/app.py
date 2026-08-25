"""
FastAPI front end for the LOT 2 PII scan: upload a CSV, get the detections
and a summary back as downloads. See pii_test/PII_SERVICE_PLAN.md.

Writes nothing to DuckDB or S3. Each upload lives in jobs/<id>/ next to this
file and is deleted by the TTL sweep -- uploads contain PII by definition,
so retention is short by design.

Run from anywhere (scanner pins the cwd to the repo root):

    .venv/bin/python pii_test/pii_service/app.py --port 8000
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import time
import uuid as uuidlib
from dataclasses import dataclass, field

import pandas as pd
import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import scanner  # noqa: E402  -- must come before anything that logs

scanner.configure_logging()

SERVICE_DIR = scanner.SERVICE_DIR
JOBS_DIR = os.path.join(SERVICE_DIR, "jobs")
STATIC_DIR = os.path.join(SERVICE_DIR, "static")

MAX_UPLOAD_BYTES = 100 * 2**20
DEFAULT_MAX_ROWS = 50_000          # bounded worst case on the T4: a few minutes
JOB_TTL_SECONDS = 6 * 3600
SWEEP_INTERVAL_SECONDS = 900

DETECTION_FIELDS = ("uuid", "column", "row_index", "entity_type",
                    "entity_text", "score", "source")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class Job:
    id: str
    filename: str                  # sanitized upload name, also the file on disk
    max_rows: int
    created: float = field(default_factory=time.time)
    status: str = "queued"         # queued | running | done | error
    error: str | None = None
    summary: dict | None = None

    @property
    def dir(self):
        return os.path.join(JOBS_DIR, self.id)


def _pick_device():
    """Decided at import time so gunicorn (which never calls main()) gets it
    too. PII_SERVICE_DEVICE=cpu leaves the GPU to a corpus run."""
    if os.environ.get("PII_SERVICE_DEVICE", "").lower() == "cpu":
        return "cpu"
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


JOBS: dict[str, Job] = {}
QUEUE: asyncio.Queue[str] = asyncio.Queue()
STATE = {"model_loaded": False, "device": _pick_device()}


def _queue_position(job):
    """1-based place in line among queued jobs; None once running/finished."""
    if job.status != "queued":
        return None
    return 1 + sum(1 for j in JOBS.values()
                   if j.status == "queued" and j.created < job.created)


def _process_job(job):
    """Runs in the worker thread: scan, then write the two result files."""
    started = time.time()
    input_path = os.path.join(job.dir, job.filename)
    result = scanner.scan_one(input_path, job.max_rows)
    if result["error"]:
        raise RuntimeError(result["error"])

    # Same writer as run_pii_s3 --path, so the CSVs are byte-compatible;
    # written even when empty so the download link always resolves.
    detections = pd.DataFrame(result["detections"], columns=DETECTION_FIELDS)
    detections.to_csv(os.path.join(job.dir, "detections.csv"), index=False)

    summary = {
        "filename": job.filename,
        "pii_found": result["pii_found"],
        "pii_flag_reason": result["pii_flag_reason"],
        "pii_types": result["pii_types"],
        "entity_count": result["entity_count"],
        "rows_scanned": result["rows_scanned"],
        "max_rows": job.max_rows,
        "columns_scanned": result["columns_scanned"],
        "columns_skipped": result["columns_skipped"],
        "degraded": result["degraded"],
        "scan_seconds": round(time.time() - started, 2),
    }
    with open(os.path.join(job.dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return summary


async def _consume():
    """The single scan worker: loads the models, then drains the queue."""
    await asyncio.to_thread(scanner.load_models, STATE["device"])
    STATE["model_loaded"] = True
    while True:
        job = JOBS.get(await QUEUE.get())
        if job is None:            # swept while queued
            continue
        job.status = "running"
        logging.info(f"job {job.id}: scanning {job.filename!r} "
                     f"(max_rows={job.max_rows})")
        try:
            job.summary = await asyncio.to_thread(_process_job, job)
            job.status = "done"
            logging.info(f"job {job.id}: done, {job.summary['entity_count']} "
                         f"detection(s), flagged={job.summary['pii_found']}")
        except Exception as exc:
            job.status, job.error = "error", str(exc)
            logging.exception(f"job {job.id}: failed")


async def _sweep():
    """Delete job dirs older than the TTL. Uploads are PII; keep them short."""
    while True:
        cutoff = time.time() - JOB_TTL_SECONDS
        for job_id in [j for j, job in JOBS.items() if job.created < cutoff]:
            JOBS.pop(job_id)
        if os.path.isdir(JOBS_DIR):
            for entry in os.listdir(JOBS_DIR):
                path = os.path.join(JOBS_DIR, entry)
                # Covers dirs orphaned by a previous run of the server too.
                if entry not in JOBS and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    logging.info(f"swept job dir {entry}")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app):
    os.makedirs(JOBS_DIR, exist_ok=True)
    tasks = [asyncio.create_task(_consume()), asyncio.create_task(_sweep())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="PII scan service", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/healthz")
async def healthz():
    return {"model_loaded": STATE["model_loaded"],
            "device": STATE["device"],
            "queue_depth": sum(1 for j in JOBS.values()
                               if j.status in ("queued", "running"))}


@app.post("/scan")
async def scan(file: UploadFile, max_rows: int = Form(DEFAULT_MAX_ROWS)):
    name = _SAFE_NAME_RE.sub("_", os.path.basename(file.filename or ""))
    if not name.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    max_rows = max(1, min(max_rows, DEFAULT_MAX_ROWS))

    job = Job(id=uuidlib.uuid4().hex, filename=name, max_rows=max_rows)
    os.makedirs(job.dir, exist_ok=True)
    size = 0
    try:
        with open(os.path.join(job.dir, name), "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"File exceeds {MAX_UPLOAD_BYTES >> 20} MB")
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(job.dir, ignore_errors=True)
        raise

    JOBS[job.id] = job
    await QUEUE.put(job.id)
    logging.info(f"job {job.id}: queued {name!r} ({size:,} bytes)")
    return {"job_id": job.id}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job (results are deleted after 6 hours)")
    return {"job_id": job.id, "status": job.status, "filename": job.filename,
            "queue_position": _queue_position(job),
            "model_loaded": STATE["model_loaded"],
            "error": job.error, "summary": job.summary}


def _job_file(job_id, filename):
    job = JOBS.get(job_id)
    path = job and os.path.join(job.dir, filename)
    if not (job and job.status == "done" and os.path.exists(path)):
        raise HTTPException(404, "No result for this job")
    return job, path


@app.get("/jobs/{job_id}/detections.csv")
async def job_detections(job_id: str):
    job, path = _job_file(job_id, "detections.csv")
    stem = os.path.splitext(job.filename)[0]
    return FileResponse(path, media_type="text/csv",
                        filename=f"{stem}_pii_detections.csv")


@app.get("/jobs/{job_id}/summary.json")
async def job_summary(job_id: str):
    _, path = _job_file(job_id, "summary.json")
    return FileResponse(path, media_type="application/json")


def main():
    """Dev entry point. Production runs under gunicorn -- see README."""
    parser = argparse.ArgumentParser(description="PII scan web service.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (0.0.0.0 once nginx fronts it)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-gpu", action="store_true")
    args = parser.parse_args()

    if args.no_gpu:
        STATE["device"] = "cpu"
    # log_config=None: uvicorn's loggers propagate to the root logger, so its
    # access log lands in pii_service.log + stderr with everything else.
    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
