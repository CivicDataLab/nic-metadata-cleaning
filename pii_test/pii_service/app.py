"""
FastAPI front end for the PII API: upload a CSV (plus, optionally, what the
dataset is), get back whether it holds personal data -- detection, Tier 1
rules and the Tier 3 LLM judge, via api_pipeline. See
pii_test/PII_SERVICE_PLAN.md.

Writes nothing to DuckDB. Each run lives in jobs/<run_id>/ next to this file
until the TTL sweep, and is uploaded to its own S3 folder (storage.py) as
the permanent record.

Run from anywhere (scanner pins the cwd to the repo root):

    .venv/bin/python pii_test/pii_service/app.py --port 8080

(8000 is the Tier 3 judge.)
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import threading
import time
import uuid as uuidlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import scanner  # noqa: E402  -- must come before anything that logs

scanner.configure_logging()

import api_pipeline  # noqa: E402
import storage  # noqa: E402

SERVICE_DIR = scanner.SERVICE_DIR
JOBS_DIR = os.path.join(SERVICE_DIR, "jobs")
STATIC_DIR = os.path.join(SERVICE_DIR, "static")

MAX_UPLOAD_BYTES = 100 * 2**20
DEFAULT_MAX_ROWS = 50_000          # bounded worst case on the T4: a few minutes
JOB_TTL_SECONDS = 6 * 3600
SWEEP_INTERVAL_SECONDS = 900
MAX_TITLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 5_000
HEALTH_CACHE_SECONDS = 30

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc)


@dataclass
class Job:
    id: str                        # the run id: <UTC time>_<uuid4 hex>
    filename: str                  # sanitized upload name, also the file on disk
    max_rows: int
    meta: dict                     # title / catalog_title / description from the request
    llm: bool
    size: int
    created: float
    status: str = "queued"         # queued | running | done | error
    stage: str | None = None       # scanning | tier1 | tier3 while running
    progress: dict | None = None   # {"done", "total"} during tier3
    error: str | None = None
    result: dict | None = None

    @property
    def dir(self):
        return os.path.join(JOBS_DIR, self.id)

    @property
    def input_path(self):
        return os.path.join(self.dir, "input", self.filename)

    @property
    def s3_prefix(self):
        return storage.run_prefix(self.id, self.created)


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
HEALTH = {"checked": 0.0, "judge": None, "s3": None}

# Every run executes on this one thread: the models are loaded here, runs are
# serialized by it, and the per-run log handler filters on its ident.
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pii-run")


def _queue_position(job):
    """1-based place in line among queued jobs; None once running/finished."""
    if job.status != "queued":
        return None
    return 1 + sum(1 for j in JOBS.values()
                   if j.status == "queued" and j.created < job.created)


class _ThisThread(logging.Filter):
    """Pass only records logged from one thread -- the run's own lines."""

    def __init__(self):
        super().__init__()
        self.ident = threading.get_ident()

    def filter(self, record):
        return record.thread == self.ident


def _write_request(job, **extra):
    request = {
        "run_id": job.id,
        "file": job.filename,
        "size_bytes": job.size,
        "submitted_at": _utc(job.created).isoformat(),
        "metadata": job.meta,
        "options": {"llm": job.llm, "max_rows": job.max_rows},
        **extra,
    }
    with open(os.path.join(job.dir, "request.json"), "w", encoding="utf-8") as fh:
        json.dump(request, fh, indent=2, ensure_ascii=False)


def _process_job(job):
    """Runs on the worker thread: the pipeline, then the upload to S3."""
    root = logging.getLogger()
    handler = logging.FileHandler(os.path.join(job.dir, "run.log"), encoding="utf-8")
    handler.setFormatter(root.handlers[0].formatter if root.handlers else None)
    handler.addFilter(_ThisThread())
    root.addHandler(handler)

    def progress(stage, done, total):
        job.stage = stage
        job.progress = {"done": done, "total": total} if total else None

    s3_folder = storage.uri(job.s3_prefix)
    started, timings = time.time(), {}
    try:
        logging.info(f"run {job.id}: {job.filename!r}, {job.size:,} bytes, "
                     f"llm={job.llm}, max_rows={job.max_rows}")
        try:
            result = api_pipeline.run(
                job.input_path, job.dir, job.meta, run_id=job.id,
                scan=scanner.scan_one, max_rows=job.max_rows, llm=job.llm,
                progress=progress, timings=timings, s3_folder=s3_folder)
        except Exception as exc:                        # noqa: BLE001
            logging.exception(f"run {job.id}: failed")
            result = api_pipeline.error_result(
                job.id, job.filename, f"{type(exc).__name__}: {exc}", s3_folder)
            api_pipeline.write_result(job.dir, result)
        _write_request(job, status=result["status"],
                       started_at=_utc(started).isoformat(),
                       finished_at=_utc(time.time()).isoformat(),
                       seconds=timings)
        logging.info(f"run {job.id}: {result['status']}, uploading to {s3_folder}")
    finally:
        root.removeHandler(handler)
        handler.close()

    try:
        storage.upload_run(job.dir, job.s3_prefix)
        logging.info(f"run {job.id}: stored at {s3_folder}")
    except Exception as exc:                            # noqa: BLE001
        # The full error (it names local paths) stays in the service log;
        # the client gets the gist.
        logging.error(f"run {job.id}: S3 upload failed: {exc}")
        result["s3_folder"] = None
        result["s3_error"] = (f"upload to s3://{storage.BUCKET} failed "
                              f"({type(exc).__name__}); results are kept locally "
                              f"for {JOB_TTL_SECONDS // 3600} hours")
        api_pipeline.write_result(job.dir, result)
    return result


async def _consume():
    """The single run worker: loads the models, then drains the queue."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(EXECUTOR, scanner.load_models, STATE["device"])
    STATE["model_loaded"] = True
    while True:
        job = JOBS.get(await QUEUE.get())
        if job is None:            # swept while queued
            continue
        job.status = "running"
        try:
            job.result = await loop.run_in_executor(EXECUTOR, _process_job, job)
            job.status = job.result["status"]
            job.error = job.result.get("error")
        except Exception as exc:                        # noqa: BLE001
            job.status, job.error = "error", str(exc)
            logging.exception(f"run {job.id}: failed outside the pipeline")
        finally:
            job.stage, job.progress = None, None


async def _sweep():
    """Delete local run dirs older than the TTL. S3 keeps the permanent copy."""
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


async def _ensure_s3_readme():
    try:
        await asyncio.to_thread(storage.ensure_readme)
    except Exception as exc:                            # noqa: BLE001
        logging.warning(f"could not write {storage.uri(storage.README_KEY)}: {exc}")


@contextlib.asynccontextmanager
async def lifespan(app):
    os.makedirs(JOBS_DIR, exist_ok=True)
    tasks = [asyncio.create_task(_consume()), asyncio.create_task(_sweep()),
             asyncio.create_task(_ensure_s3_readme())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="PII scan service", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


async def _dependencies():
    """Judge and S3 reachability, rechecked at most every HEALTH_CACHE_SECONDS."""
    if time.time() - HEALTH["checked"] > HEALTH_CACHE_SECONDS:
        HEALTH["judge"], HEALTH["s3"] = await asyncio.gather(
            asyncio.to_thread(api_pipeline.judge_problem),
            asyncio.to_thread(storage.problem))
        HEALTH["checked"] = time.time()
    return HEALTH["judge"], HEALTH["s3"]


@app.get("/healthz")
async def healthz():
    judge, s3 = await _dependencies()
    return {"model_loaded": STATE["model_loaded"],
            "device": STATE["device"],
            "queue_depth": sum(1 for j in JOBS.values()
                               if j.status in ("queued", "running")),
            "judge": {"ok": judge is None, "detail": judge},
            "s3": {"ok": s3 is None, "detail": s3}}


def _field(value, name, limit):
    value = " ".join((value or "").split()) if name != "description" else (value or "").strip()
    if len(value) > limit:
        raise HTTPException(400, f"{name} is longer than {limit:,} characters")
    return value or None


@app.post("/scan", status_code=202)
async def scan(file: UploadFile,
               max_rows: int = Form(DEFAULT_MAX_ROWS),
               title: str = Form(""),
               catalog_title: str = Form(""),
               description: str = Form(""),
               llm: bool = Form(True)):
    name = _SAFE_NAME_RE.sub("_", os.path.basename(file.filename or ""))
    if not name.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    meta = {"title": _field(title, "title", MAX_TITLE_CHARS),
            "catalog_title": _field(catalog_title, "catalog_title", MAX_TITLE_CHARS),
            "description": _field(description, "description", MAX_DESCRIPTION_CHARS)}
    max_rows = max(1, min(max_rows, DEFAULT_MAX_ROWS))

    created = time.time()
    run_id = f"{_utc(created):%Y%m%dT%H%M%SZ}_{uuidlib.uuid4().hex}"
    job = Job(id=run_id, filename=name, max_rows=max_rows, meta=meta, llm=llm,
              size=0, created=created)
    os.makedirs(os.path.dirname(job.input_path), exist_ok=True)
    try:
        with open(job.input_path, "wb") as out:
            while chunk := await file.read(1 << 20):
                job.size += len(chunk)
                if job.size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"File exceeds {MAX_UPLOAD_BYTES >> 20} MB")
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(job.dir, ignore_errors=True)
        raise
    _write_request(job, status="queued")

    JOBS[job.id] = job
    await QUEUE.put(job.id)
    logging.info(f"run {job.id}: queued {name!r} ({job.size:,} bytes)")
    return {"run_id": job.id, "job_id": job.id, "status_url": f"/jobs/{job.id}"}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "No such run (local results are deleted after "
                                 "6 hours; the S3 copy is kept)")
    return {"run_id": job.id, "job_id": job.id, "status": job.status,
            "stage": job.stage, "progress": job.progress,
            "filename": job.filename,
            "queue_position": _queue_position(job),
            "model_loaded": STATE["model_loaded"],
            "error": job.error, "result": job.result}


@app.get("/jobs/{job_id}/files/{name}")
async def job_file(job_id: str, name: str):
    job = JOBS.get(job_id)
    rel = api_pipeline.DOWNLOADS.get(name)
    path = job and rel and os.path.join(job.dir, rel)
    if not (path and job.status in ("done", "error") and os.path.exists(path)):
        raise HTTPException(404, "No such file for this run")
    media = "application/json" if name.endswith(".json") else "text/csv"
    stem = os.path.splitext(job.filename)[0]
    return FileResponse(path, media_type=media, filename=f"{stem}_{name}")


# Pre-pipeline routes, kept so existing links and scripts still resolve.
@app.get("/jobs/{job_id}/detections.csv")
async def job_detections(job_id: str):
    return await job_file(job_id, "detections.csv")


@app.get("/jobs/{job_id}/summary.json")
async def job_summary(job_id: str):
    return await job_file(job_id, "result.json")


def main():
    """Dev entry point. Production runs under gunicorn -- see README."""
    parser = argparse.ArgumentParser(description="PII scan web service.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (0.0.0.0 once nginx fronts it)")
    # Not 8000: that is the Tier 3 judge's port.
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-gpu", action="store_true")
    args = parser.parse_args()

    if args.no_gpu:
        STATE["device"] = "cpu"
    # log_config=None: uvicorn's loggers propagate to the root logger, so its
    # access log lands in pii_service.log + stderr with everything else.
    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
