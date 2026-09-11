"""Demo chat app: a minimal multi-session chat UI whose replies are routed
through the model-tier evaluation system (call_site_id="chat-reply",
scope_id=<session id>), and whose thumbs up/down feeds the outcome signal
the analysis engine uses. Talk to it, start new conversations, and rate them
to build a real dataset the eval dashboard (default http://127.0.0.1:8008/)
can analyze.

Run from the repo root so the `sdk` package resolves:
    uvicorn demo_chat_app.main:app --port 8010 --reload
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from sdk.client import SmartSamplerClient
from demo_chat_app import store
from demo_chat_app.llm import generate_reply

CALL_SITE_ID = "chat-reply"
SAMPLER_API_BASE_URL = os.environ.get("SAMPLER_API_BASE_URL", "http://127.0.0.1:8008")

app = FastAPI(title="Demo Chat App")
sampler = SmartSamplerClient(api_base_url=SAMPLER_API_BASE_URL)

STATIC_DIR = Path(__file__).resolve().parent / "static"

store.init_db()


class Message(BaseModel):
    role: str  # "user" | "assistant"
    text: str


class SessionOut(BaseModel):
    id: str
    created_at: datetime
    messages: List[Message] = []
    vote: Optional[str] = None
    tier: Optional[str] = None
    model: Optional[str] = None


class NewMessageIn(BaseModel):
    text: str


class FeedbackIn(BaseModel):
    vote: str  # "up" | "down"


def _row_to_session(row: dict) -> SessionOut:
    return SessionOut(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        messages=[Message(**m) for m in row["messages"]],
        vote=row["vote"],
        tier=row["tier"],
        model=row["model"],
    )


@app.get("/api/meta")
def get_meta():
    return {"call_site_id": CALL_SITE_ID, "sampler_dashboard_url": SAMPLER_API_BASE_URL}


@app.post("/api/sessions", response_model=SessionOut, status_code=201)
def create_session():
    session_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    store.create_session(session_id, created_at.isoformat())
    return SessionOut(id=session_id, created_at=created_at)


@app.get("/api/sessions", response_model=List[SessionOut])
def list_sessions():
    sessions = [_row_to_session(row) for row in store.list_sessions()]
    return sorted(sessions, key=lambda s: s.created_at, reverse=True)


@app.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str):
    row = store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")
    return _row_to_session(row)


@app.post("/api/sessions/{session_id}/messages", response_model=SessionOut)
def send_message(session_id: str, payload: NewMessageIn):
    row = store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="message text cannot be empty")

    store.add_message(session_id, "user", payload.text)

    # Tier/model are resolved once and stick for the life of the session --
    # this *is* the "no mid-scope contamination" principle from the design
    # doc, demonstrated live: every message in this conversation gets routed
    # to the same model tier.
    tier = sampler.get_tier(CALL_SITE_ID, session_id)
    model = sampler.get_model(CALL_SITE_ID, session_id)

    history = store.get_session(session_id)["messages"]
    api_messages = [{"role": m["role"], "content": m["text"]} for m in history]
    try:
        reply_text = generate_reply(model=model, messages=api_messages)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    sampler.record_call(CALL_SITE_ID, session_id, model_used=model, tier=tier)

    store.set_tier_model(session_id, tier, model)
    store.add_message(session_id, "assistant", reply_text)
    return _row_to_session(store.get_session(session_id))


@app.post("/api/sessions/{session_id}/feedback", response_model=SessionOut)
def give_feedback(session_id: str, payload: FeedbackIn):
    row = store.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if payload.vote not in ("up", "down"):
        raise HTTPException(status_code=400, detail="vote must be 'up' or 'down'")
    if not row["messages"]:
        raise HTTPException(status_code=400, detail="cannot rate a conversation with no messages yet")

    store.set_vote(session_id, payload.vote)
    sampler.report_outcome(CALL_SITE_ID, session_id, score=(payload.vote == "up"), source="thumbs_button")
    return _row_to_session(store.get_session(session_id))


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
