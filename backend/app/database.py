"""SQLite connection, schema initialization, and audit persistence."""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from contextvars import ContextVar
from functools import wraps
import inspect
import hashlib

current_user = ContextVar("guardian_user", default="demo-user")


def tool_token():
    user = current_user.get()
    if user == "demo-user":
        return os.environ.get("GUARDIAN_AGENT_TOOL_TOKEN", "")
    token = current_user.set("demo-user")
    try:
        with db() as conn:
            return conn.execute("SELECT tool_token FROM users WHERE id=?", (user,)).fetchone()[0]
    finally:
        current_user.reset(token)


def user_scoped(function):
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        user = signature.bind(*args, **kwargs).arguments.get("user", "demo-user")
        token = current_user.set(user)
        try:
            if user != "demo-user":
                init_db()
            return function(*args, **kwargs)
        finally:
            current_user.reset(token)
    return wrapped

DB_PATH = Path(
    os.getenv("GUARDIAN_DB_PATH")
    or str(Path(__file__).resolve().parents[1] / "guardian.db")
)


@contextmanager
def db():
    user = current_user.get()
    path = DB_PATH if user == "demo-user" else DB_PATH.with_name(DB_PATH.stem + "-" + hashlib.sha256(user.encode()).hexdigest() + ".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, tool_token TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS registration_profiles (user_id TEXT PRIMARY KEY REFERENCES users(id), encrypted_profile TEXT NOT NULL, consent_version TEXT NOT NULL, consent_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operator (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires_at REAL NOT NULL, last_seen REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS google_oauth (id INTEGER PRIMARY KEY CHECK (id=1), state_hash TEXT, state_expires_at REAL, refresh_token TEXT, scopes TEXT, connected_at TEXT);
            CREATE TABLE IF NOT EXISTS integration_settings (id INTEGER PRIMARY KEY CHECK (id=1), trusted_contact_email TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS followup_events (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE, details TEXT NOT NULL, status TEXT NOT NULL, result TEXT);
            CREATE TABLE IF NOT EXISTS followup_facts (incident_id TEXT PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE, facts TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts (address TEXT NOT NULL, attempted_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, merchant TEXT NOT NULL, amount INTEGER NOT NULL, occurred_at TEXT NOT NULL, status TEXT NOT NULL, suspicious INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, summary TEXT NOT NULL, incident_type TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS demo_account (id INTEGER PRIMARY KEY CHECK (id=1), card_frozen INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id), kind TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, result TEXT, approved_at TEXT, created_at TEXT NOT NULL, UNIQUE(incident_id, kind));
            CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, incident_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS voice_sessions (id TEXT PRIMARY KEY, agora_session_id TEXT, channel TEXT NOT NULL, user_uid INTEGER NOT NULL, agent_uid INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incident_requests (request_key TEXT PRIMARY KEY, summary TEXT NOT NULL, incident_type TEXT NOT NULL, incident_id TEXT NOT NULL REFERENCES incidents(id));
            CREATE TABLE IF NOT EXISTS voice_events (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES voice_sessions(id), event TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(auth_sessions)")}
        if "user_id" not in columns:
            conn.execute("ALTER TABLE auth_sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'demo-user'")
        voice_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(voice_sessions)")
        }
        if "profile_id" not in voice_columns:
            conn.execute(
                "ALTER TABLE voice_sessions ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'default'"
            )
        if conn.execute("SELECT 1 FROM transactions LIMIT 1").fetchone() is None:
            now = datetime.now(timezone.utc)
            conn.executemany(
                "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "txn-1001",
                        "Metro Grocery",
                        2840,
                        (now - timedelta(days=1)).isoformat(),
                        "completed",
                        0,
                    ),
                    (
                        "txn-1002",
                        "UPI Transfer · New Payee",
                        35000,
                        (now - timedelta(hours=2)).isoformat(),
                        "completed",
                        1,
                    ),
                    (
                        "txn-1003",
                        "Fuel Station",
                        1800,
                        (now - timedelta(hours=5)).isoformat(),
                        "completed",
                        0,
                    ),
                ],
            )
        conn.execute(
            "INSERT OR IGNORE INTO demo_account(id, card_frozen) VALUES (1, 0)"
        )
        conn.execute(
            "DELETE FROM voice_events WHERE created_at < ?",
            ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM audit WHERE incident_id IN (SELECT id FROM incidents WHERE created_at < ? AND status != 'in_progress')", (cutoff,))
        conn.execute("DELETE FROM incident_requests WHERE incident_id IN (SELECT id FROM incidents WHERE created_at < ? AND status != 'in_progress')", (cutoff,))
        conn.execute("DELETE FROM actions WHERE incident_id IN (SELECT id FROM incidents WHERE created_at < ? AND status != 'in_progress')", (cutoff,))
        conn.execute("DELETE FROM incidents WHERE created_at < ? AND status != 'in_progress'", (cutoff,))


def as_dicts(rows):
    return [dict(row) for row in rows]


def audit(conn, incident_id, action, detail):
    conn.execute(
        "INSERT INTO audit VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid4()),
            incident_id,
            action,
            detail,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
