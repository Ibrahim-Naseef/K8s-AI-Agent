import hmac
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db
from .agent import investigate

@asynccontextmanager
async def lifespan(_):
    db.init()
    yield


app = FastAPI(title="AI Kubernetes Troubleshooter", lifespan=lifespan)
JOBS: dict = {}
LOCK = threading.Lock()


def auth(authorization: str = Header(default="")):
    # Fail closed: refuse everything if no token is configured.
    if not config.APP_TOKEN:
        raise HTTPException(503, "Server has no APP_TOKEN configured")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {config.APP_TOKEN}".encode()):
        raise HTTPException(401, "Invalid token")


class Req(BaseModel):
    namespace: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")
    question: str = Field(default="", max_length=500)


def _run(job_id: str, ns: str, question: str):
    job = JOBS[job_id]

    def emit(kind, message, data=None):
        job["events"].append({"t": time.time(), "kind": kind, "message": message, "data": data})

    try:
        job["result"] = investigate(ns, question, emit)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"] = "error", f"{type(e).__name__}: {str(e)[:300]}"
    db.upsert(job_id, ns, question, job["status"], job.get("result"), job.get("error"), job["events"])


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/namespaces", dependencies=[Depends(auth)])
def namespaces():
    return config.ALLOWED_NAMESPACES


@app.post("/api/investigations", dependencies=[Depends(auth)])
def start(req: Req):
    if req.namespace not in config.ALLOWED_NAMESPACES:
        raise HTTPException(403, f"Namespace not allowed. Allowed: {config.ALLOWED_NAMESPACES}")
    with LOCK:
        if sum(1 for j in JOBS.values() if j["status"] == "running") >= 3:
            raise HTTPException(429, "Too many investigations running; try again shortly")
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "namespace": req.namespace, "question": req.question,
                        "status": "running", "events": [], "result": None, "error": None,
                        "created_at": time.time()}
    db.upsert(job_id, req.namespace, req.question, "running")
    threading.Thread(target=_run, args=(job_id, req.namespace, req.question), daemon=True).start()
    return {"id": job_id}


@app.get("/api/investigations", dependencies=[Depends(auth)])
def history():
    return db.list_recent()


@app.get("/api/investigations/{job_id}", dependencies=[Depends(auth)])
def get_one(job_id: str):
    job = JOBS.get(job_id)
    if job:
        return job
    row = db.get(job_id)
    if not row:
        raise HTTPException(404, "Not found")
    return row


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
