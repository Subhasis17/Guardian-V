"""User-authorized third-party integrations."""

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.database import db, user_scoped
from app.security import require_demo_auth

router = APIRouter(prefix="/api/integrations/google")
SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)


class ContactInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        return value


def _config():
    values = {name: os.getenv(name, "").strip() for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")}
    if not all(values.values()):
        raise HTTPException(503, "Google OAuth is not configured on the backend.")
    if not values["GOOGLE_REDIRECT_URI"].startswith(("http://", "https://")):
        raise HTTPException(503, "GOOGLE_REDIRECT_URI must be an HTTP(S) URL.")
    return values


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _cipher():
    key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise HTTPException(503, "GOOGLE_TOKEN_ENCRYPTION_KEY is not configured on the backend.")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception as exc:
        raise HTTPException(503, "Google token encryption is not configured correctly.") from exc


def _exchange(code, config):
    body = urlencode({
        "code": code,
        "client_id": config["GOOGLE_CLIENT_ID"],
        "client_secret": config["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": config["GOOGLE_REDIRECT_URI"],
        "grant_type": "authorization_code",
    }).encode()
    try:
        with urlopen(Request("https://oauth2.googleapis.com/token", data=body), timeout=15) as response:
            result = json.load(response)
    except Exception as exc:
        raise HTTPException(502, "Google token exchange failed.") from exc
    if not result.get("refresh_token"):
        raise HTTPException(400, "Google did not return a refresh token. Reconnect with consent.")
    return result


@router.get("/connect")
@user_scoped
def connect(user=Depends(require_demo_auth)):
    config = _config()
    state = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO google_oauth(id) VALUES (1)")
        conn.execute("UPDATE google_oauth SET state_hash=?, state_expires_at=? WHERE id=1", (_hash(state), time.time() + 600))
    params = {
        "client_id": config["GOOGLE_CLIENT_ID"],
        "redirect_uri": config["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/callback")
@user_scoped
def callback(code: str | None = None, state: str | None = None, error: str | None = None, user=Depends(require_demo_auth)):
    home = os.getenv("GUARDIAN_FRONTEND_URL", "http://127.0.0.1:5173").strip()
    parsed = urlsplit(home)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503, "GUARDIAN_FRONTEND_URL must be an HTTP(S) dashboard URL.")
    if error:
        raise HTTPException(400, "Google authorization was declined.")
    if not code or not state:
        raise HTTPException(400, "Google authorization response is incomplete.")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT state_hash, state_expires_at FROM google_oauth WHERE id=1").fetchone()
        if not row or not row["state_hash"] or row["state_expires_at"] <= time.time() or not secrets.compare_digest(row["state_hash"], _hash(state)):
            raise HTTPException(400, "Google authorization state is invalid or expired.")
        conn.execute("UPDATE google_oauth SET state_hash=NULL, state_expires_at=NULL WHERE id=1")
    result = _exchange(code, _config())
    encrypted = _cipher().encrypt(result["refresh_token"].encode()).decode()
    with db() as conn:
        conn.execute("UPDATE google_oauth SET state_hash=NULL, state_expires_at=NULL, refresh_token=?, scopes=?, connected_at=? WHERE id=1", (encrypted, json.dumps(SCOPES), datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(home, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/status")
@user_scoped
def status(user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute("SELECT refresh_token, scopes, connected_at FROM google_oauth WHERE id=1").fetchone()
        contact = conn.execute("SELECT trusted_contact_email FROM integration_settings WHERE id=1").fetchone()
    return {"connected": bool(row and row["refresh_token"]), "scopes": json.loads(row["scopes"]) if row and row["scopes"] else [], "connected_at": row["connected_at"] if row else None, "trusted_contact_email": contact[0] if contact else ""}


@router.post("/contact")
@user_scoped
def set_contact(payload: ContactInput, user=Depends(require_demo_auth)):
    with db() as conn:
        conn.execute("INSERT INTO integration_settings(id, trusted_contact_email) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET trusted_contact_email=excluded.trusted_contact_email", (str(payload.email),))
    return {"saved": True}


@router.post("/disconnect")
@user_scoped
def disconnect(user=Depends(require_demo_auth)):
    with db() as conn:
        conn.execute("UPDATE google_oauth SET refresh_token=NULL, scopes=NULL, connected_at=NULL, state_hash=NULL, state_expires_at=NULL WHERE id=1")
    return {"connected": False}


def refresh_token_for_current_user():
    with db() as conn:
        row = conn.execute("SELECT refresh_token FROM google_oauth WHERE id=1").fetchone()
    if not row or not row["refresh_token"]:
        raise ValueError("Connect Google before using Gmail or Calendar")
    return _cipher().decrypt(row["refresh_token"].encode()).decode()
