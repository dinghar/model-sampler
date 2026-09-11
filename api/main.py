from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.db import get_session, init_db
from common.models import CallSiteConfig, ConfigAuditLog, BucketAssignment, CallEvent, OutcomeEvent, AnalysisResult
from sdk.hashing import assign_tier as compute_tier
from analysis_engine.run import run_once as run_analysis_once
from api.schemas import (
    CallSiteConfigIn, CallSiteConfigPatch, CallSiteConfigOut,
    AssignRequest, AssignResponse,
    CallEventIn, OutcomeEventIn,
    AnalysisResultOut,
)

app = FastAPI(title="Model-Tier Evaluation API")

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------------------------------------------------------
# Call site config
# ---------------------------------------------------------------------------

@app.post("/api/call-sites", response_model=CallSiteConfigOut, status_code=201)
def create_call_site(payload: CallSiteConfigIn, db: Session = Depends(get_session)):
    if db.get(CallSiteConfig, payload.call_site_id) is not None:
        raise HTTPException(status_code=409, detail="call_site_id already exists")
    config = CallSiteConfig(**payload.model_dump())
    db.add(config)
    db.add(ConfigAuditLog(call_site_id=payload.call_site_id, changed_by=None, change=payload.model_dump(mode="json")))
    db.commit()
    db.refresh(config)
    return config


@app.get("/api/call-sites", response_model=List[CallSiteConfigOut])
def list_call_sites(db: Session = Depends(get_session)):
    return db.scalars(select(CallSiteConfig).order_by(CallSiteConfig.call_site_id)).all()


@app.get("/api/call-sites/{call_site_id}", response_model=CallSiteConfigOut)
def get_call_site(call_site_id: str, db: Session = Depends(get_session)):
    config = db.get(CallSiteConfig, call_site_id)
    if config is None:
        raise HTTPException(status_code=404, detail="unknown call_site_id")
    return config


@app.patch("/api/call-sites/{call_site_id}", response_model=CallSiteConfigOut)
def update_call_site(call_site_id: str, payload: CallSiteConfigPatch, db: Session = Depends(get_session)):
    config = db.get(CallSiteConfig, call_site_id)
    if config is None:
        raise HTTPException(status_code=404, detail="unknown call_site_id")

    changes = payload.model_dump(exclude_unset=True, exclude={"changed_by"})
    if not changes:
        return config

    diff = {}
    for field, new_value in changes.items():
        old_value = getattr(config, field)
        if old_value != new_value:
            diff[field] = {"old": old_value, "new": new_value}
        setattr(config, field, new_value)
    config.updated_at = datetime.now(timezone.utc)

    if diff:
        db.add(ConfigAuditLog(call_site_id=call_site_id, changed_by=payload.changed_by, change=diff))

    db.commit()
    db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------

@app.post("/api/call-sites/{call_site_id}/assign", response_model=AssignResponse)
def assign_bucket(call_site_id: str, payload: AssignRequest, db: Session = Depends(get_session)):
    config = db.get(CallSiteConfig, call_site_id)
    if config is None:
        raise HTTPException(status_code=404, detail="unknown call_site_id")

    # Kill switch: a disabled call site always routes to control, and does not
    # create a new bucket assignment for scopes it hasn't already seen.
    if not config.enabled:
        return AssignResponse(
            call_site_id=call_site_id, scope_id=payload.scope_id, tier="control", model=config.control_model
        )

    existing = db.get(BucketAssignment, (call_site_id, payload.scope_id))
    if existing is not None:
        tier = existing.tier
    else:
        tier = compute_tier(call_site_id, payload.scope_id, config.salt, config.sample_rate)
        db.add(BucketAssignment(
            call_site_id=call_site_id, scope_id=payload.scope_id, tier=tier, salt_used=config.salt
        ))
        try:
            db.commit()
        except IntegrityError:
            # concurrent first-assignment race: the other writer's row wins
            db.rollback()
            existing = db.get(BucketAssignment, (call_site_id, payload.scope_id))
            tier = existing.tier

    model = config.weak_model if tier == "weak" else config.control_model
    return AssignResponse(call_site_id=call_site_id, scope_id=payload.scope_id, tier=tier, model=model)


# ---------------------------------------------------------------------------
# Telemetry ingestion
# ---------------------------------------------------------------------------

@app.post("/api/telemetry/call-events", status_code=201)
def ingest_call_event(payload: CallEventIn, db: Session = Depends(get_session)):
    event = CallEvent(
        call_site_id=payload.call_site_id,
        scope_id=payload.scope_id,
        model_used=payload.model_used,
        tier=payload.tier,
        request_id=payload.request_id,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    return {"status": "ok"}


@app.post("/api/telemetry/outcome-events", status_code=201)
def ingest_outcome_event(payload: OutcomeEventIn, db: Session = Depends(get_session)):
    event = OutcomeEvent(
        call_site_id=payload.call_site_id,
        scope_id=payload.scope_id,
        score=payload.score,
        score_type=payload.score_type,
        source=payload.source,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Analysis job trigger (on-demand, in addition to any scheduled run)
# ---------------------------------------------------------------------------

@app.post("/api/analysis/run")
def trigger_analysis_run(window_days: int = Query(default=30, le=365)):
    analyzed = run_analysis_once(window_days=window_days)
    return {"analyzed_call_sites": analyzed}


# ---------------------------------------------------------------------------
# Analysis results (read side, for the dashboard)
# ---------------------------------------------------------------------------

@app.get("/api/call-sites/{call_site_id}/results", response_model=List[AnalysisResultOut])
def get_results(call_site_id: str, limit: int = Query(default=50, le=500), db: Session = Depends(get_session)):
    rows = db.scalars(
        select(AnalysisResult)
        .where(AnalysisResult.call_site_id == call_site_id)
        .order_by(AnalysisResult.computed_at.desc())
        .limit(limit)
    ).all()
    return rows


@app.get("/api/call-sites/{call_site_id}/results/latest", response_model=AnalysisResultOut)
def get_latest_result(call_site_id: str, db: Session = Depends(get_session)):
    row = db.scalars(
        select(AnalysisResult)
        .where(AnalysisResult.call_site_id == call_site_id)
        .order_by(AnalysisResult.computed_at.desc())
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no analysis results yet for this call site")
    return row


# Dashboard static UI, served from the same app to avoid CORS in local/dev use.
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")
