import json
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, text
from .config import ROOT, ARTIFACTS, LOGS
from .db import Session, Patient, Recording, Replay, Alert, AuditEvent, Prediction, ModelVersion, utcnow
from .ml import active_version
from .service import create_replay, advance, snapshot, get_replay, DomainError
from .domain import add_minutes
from .nutrition import latest_catalog

app = FastAPI(title="GlycoAhead API", version="0.1.0", description="Recorded ShanghaiT2DM replay; no live-device integration or clinical use.")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
lock = threading.RLock()
logger = logging.getLogger("glycoahead")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOGS / "app.jsonl", maxBytes=2_000_000, backupCount=3)
logger.addHandler(handler)


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    # Local demo has no authentication. Reject cross-site browser mutations.
    origin = request.headers.get("origin")
    allowed = {"http://localhost:5173", "http://127.0.0.1:5173", str(request.base_url).rstrip("/")}
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in allowed:
        return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation rejected"})
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
    if content_length > 16_384:
        return JSONResponse(status_code=413, content={"detail": "Request exceeds 16 KB limit"})
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(json.dumps({"event": "request_failed", "request_id": request_id}))
        return JSONResponse(status_code=500, content={"detail": "Internal error; consult local logs", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    logger.info(json.dumps({"event": "http", "request_id": request_id, "method": request.method,
                            "route": getattr(request.scope.get("route"), "path", "unmatched"),
                            "status": response.status_code, "duration_ms": round((time.perf_counter()-started)*1000, 1)}))
    return response


@app.exception_handler(DomainError)
async def domain_error(_, exc):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateReplay(StrictBody):
    recording_id: str = Field(min_length=1, max_length=80, pattern=r"^[0-9_]+$")


class Advance(StrictBody):
    steps: int = Field(default=1, ge=1, le=96)
    expected_cursor: int = Field(ge=0)


class ClockJump(StrictBody):
    minutes: int = Field(default=45, ge=15, le=180)


@app.get("/api/health")
def health():
    try:
        with Session() as db:
            db.execute(text("SELECT 1"))
            recordings = db.scalar(select(func.count()).select_from(Recording))
        version = active_version()
        return {"status": "ready", "database": "ok", "recordings": recordings, "model_version": version, "mode": "local_research"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "setup_required", "detail": "Run init, import-shanghai and train."})


@app.get("/api/recordings")
def recordings():
    with Session() as db:
        return [{"id": r.id, "patient_id": r.patient_id, "age": r.profile["age"], "diabetes_years": r.profile["diabetes_years"],
                 "count": r.count, "start_time": r.start_time, "end_time": r.end_time, "gaps": r.audit["gaps"]} for r in db.scalars(select(Recording).order_by(Recording.id))]


@app.get("/api/evaluation")
def evaluation():
    try:
        version = active_version()
        path = ARTIFACTS / version / "evaluation.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, FileNotFoundError):
        raise HTTPException(503, "No evaluation report; train a model first")


@app.get("/api/experiments/latest")
def latest_experiment():
    directory = ARTIFACTS / "experiments"
    try:
        pointer = json.loads((directory / "latest.json").read_text(encoding="utf-8"))
        run_id = pointer["run_id"]
        if not isinstance(run_id, str) or Path(run_id).name != run_id or run_id in (".", ".."):
            raise ValueError("Invalid experiment identifier")
        run = directory / run_id
        status = json.loads((run / "status.json").read_text(encoding="utf-8"))
        if status.get("state") != "completed":
            raise HTTPException(409, "The latest comparison is incomplete")
        return json.loads((run / "report.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "No completed feature comparison is available")
    except (ValueError, KeyError):
        raise HTTPException(503, "The comparison report could not be read")


@app.get("/api/nutrition")
def nutrition_catalog():
    with Session() as db:
        try:
            catalog_id, catalog = latest_catalog(db)
        except ValueError as exc:
            raise HTTPException(503, str(exc))
        return {"catalog_id": catalog_id, "source": catalog["source"], "assumptions": catalog["assumptions"],
            "references": [{"key": key, **ref, "mapped_names": [name for name, mapping in catalog["mappings"].items() if mapping["reference"] == key]}
                for key, ref in catalog["references"].items()]}


@app.get("/api/database")
def database_summary():
    from .db import Base
    from .config import DATA
    with Session() as db:
        return {"engine": "SQLite", "path": str(DATA / "glycoahead.sqlite"),
            "tables": [{"name": table.name, "rows": db.scalar(select(func.count()).select_from(table))}
                for table in Base.metadata.sorted_tables], "notice": "Local research database; read-only summary."}


@app.post("/api/replays", status_code=201)
def new_replay(body: CreateReplay):
    with lock, Session.begin() as db:
        try:
            replay = create_replay(db, body.recording_id)
            return snapshot(db, replay.id)
        except ValueError as exc:
            raise HTTPException(503, str(exc))


@app.get("/api/replays/{replay_id}")
def replay_snapshot(replay_id: str):
    with Session() as db:
        return snapshot(db, replay_id)


@app.post("/api/replays/{replay_id}/advance")
def replay_advance(replay_id: str, body: Advance):
    with lock, Session.begin() as db:
        advance(db, replay_id, body.steps, body.expected_cursor)
        return snapshot(db, replay_id)


@app.post("/api/replays/{replay_id}/simulate-disconnect")
def disconnect(replay_id: str, body: ClockJump):
    with lock, Session.begin() as db:
        replay = get_replay(db, replay_id)
        if replay.virtual_time is None:
            raise HTTPException(409, "Replay at least one reading first")
        replay.virtual_time = add_minutes(replay.virtual_time, body.minutes)
        # Drop archived readings during this simulated outage. No backfill into predictions.
        from .db import SourceReading
        next_row = db.scalar(select(SourceReading).where(SourceReading.recording_id == replay.recording_id, SourceReading.time > replay.virtual_time).order_by(SourceReading.position).limit(1))
        record = db.get(Recording, replay.recording_id)
        replay.cursor = next_row.position if next_row else record.count
        for prediction in db.scalars(select(Prediction).where(Prediction.replay_id == replay_id, Prediction.outcome_status == "pending")):
            prediction.outcome_status = "censored_gap"
        replay.updated_at = utcnow()
        db.add(AuditEvent(kind="simulated_disconnect", entity_id=replay_id, details={"minutes": body.minutes}))
        return snapshot(db, replay_id)


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int):
    with lock, Session.begin() as db:
        alert = db.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")
        if alert.status != "acknowledged":
            alert.status = "acknowledged"
            alert.acknowledged_at = utcnow()
            db.add(AuditEvent(kind="alert_acknowledged", entity_id=str(alert_id), details={"meaning": "Reviewed in research demo; no treatment action implied"}))
        return {"id": alert.id, "status": alert.status, "acknowledged_at": alert.acknowledged_at}


@app.get("/api/predictions/{prediction_id}")
def prediction_provenance(prediction_id: int):
    with Session() as db:
        p = db.get(Prediction, prediction_id)
        if not p:
            raise HTTPException(404, "Prediction not found")
        model = db.get(ModelVersion, p.model_id)
        replay = db.get(Replay, p.replay_id)
        record = db.get(Recording, replay.recording_id)
        return {"id": p.id, "event_time": p.time, "processing_time": p.created_at, "features": p.features,
                "population_probability": p.population_probability, "personal_probability": p.personal_probability,
                "state_before": p.state_before, "state_after": p.state_after, "model_version": p.model_id,
                "model_sha256": model.sha256, "source_sha256": record.source_sha256, "summary_sha256": record.summary_sha256,
                "outcome": p.outcome, "outcome_status": p.outcome_status, "learned_from": bool(p.updated_state)}


@app.get("/api/audit")
def audit():
    with Session() as db:
        return [{"id": a.id, "kind": a.kind, "entity_id": a.entity_id, "details": a.details, "created_at": a.created_at} for a in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(100))]


@app.get("/api/replays/{replay_id}/export")
def export_replay(replay_id: str):
    with Session() as db:
        return JSONResponse(snapshot(db, replay_id), headers={"Content-Disposition": f'attachment; filename="glycoahead-replay-{replay_id[:32]}.json"'})


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
