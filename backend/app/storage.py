"""Durable session ownership and replayable task events for a single API worker."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from app.config import SQLITE_CHECKPOINT_PATH

path = Path(SQLITE_CHECKPOINT_PATH).with_name("sessions.sqlite3")
path.parent.mkdir(parents=True, exist_ok=True)
_connection = sqlite3.connect(path, check_same_thread=False)
_connection.execute("PRAGMA journal_mode=WAL")
_connection.executescript("""
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS session_events ON analysis_events(session_id, sequence);
""")
_connection.commit()
_lock = threading.Lock()


def save_session(session_id: str, metadata: dict) -> None:
    with _lock, _connection:
        _connection.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (session_id, json.dumps(metadata)))


def get_session(session_id: str) -> dict | None:
    with _lock:
        row = _connection.execute("SELECT metadata FROM sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(row[0]) if row else None


def delete_session(session_id: str) -> None:
    with _lock, _connection:
        _connection.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        _connection.execute("DELETE FROM analysis_events WHERE session_id=?", (session_id,))


def save_event(session_id: str, payload: dict) -> dict:
    with _lock, _connection:
        cursor = _connection.execute("INSERT INTO analysis_events(session_id,payload) VALUES (?,?)", (session_id, json.dumps(payload)))
        payload = {**payload, "id": str(cursor.lastrowid)}
        _connection.execute("UPDATE analysis_events SET payload=? WHERE sequence=?", (json.dumps(payload), cursor.lastrowid))
    return payload


def get_events(session_id: str, after: int = 0) -> list[dict]:
    with _lock:
        rows = _connection.execute("SELECT payload FROM analysis_events WHERE session_id=? AND sequence>? ORDER BY sequence DESC LIMIT 500", (session_id, after)).fetchall()
    return [json.loads(row[0]) for row in reversed(rows)]
