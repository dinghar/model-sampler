"""SQLite-backed persistence for demo chat sessions.

Conversation content previously lived only in an in-memory dict in
demo_chat_app/main.py, which meant any process restart -- including one
needed just to deploy a code fix -- silently destroyed the whole demo
dataset. This module makes that data outlive the process: it's an
application concern of the demo app, not part of the eval system's own
telemetry schema (call_events/outcome_events/bucket_assignments), which is
why it's a separate SQLite file here rather than a new table in the eval
Postgres schema.
"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "sessions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                vote TEXT,
                tier TEXT,
                model TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                ordinal INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL
            )
        """)


def create_session(session_id: str, created_at: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (session_id, created_at))


def add_message(session_id: str, role: str, text: str) -> None:
    with _connect() as conn:
        ordinal = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO messages (session_id, ordinal, role, text) VALUES (?, ?, ?, ?)",
            (session_id, ordinal, role, text),
        )


def set_tier_model(session_id: str, tier: str, model: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE sessions SET tier = ?, model = ? WHERE id = ?", (tier, model, session_id))


def set_vote(session_id: str, vote: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE sessions SET vote = ? WHERE id = ?", (vote, session_id))


def get_session(session_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        messages = conn.execute(
            "SELECT role, text FROM messages WHERE session_id = ? ORDER BY ordinal", (session_id,)
        ).fetchall()
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "vote": row["vote"],
            "tier": row["tier"],
            "model": row["model"],
            "messages": [{"role": m["role"], "text": m["text"]} for m in messages],
        }


def list_sessions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM sessions ORDER BY created_at DESC").fetchall()
    return [get_session(r["id"]) for r in rows]
