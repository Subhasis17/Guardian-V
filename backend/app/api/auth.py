"""Password login with revocable, expiring database sessions."""
import hmac
import os
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool
from datetime import datetime, timezone
from app import privacy
from app.database import db
from app.security import digest, password_hash, require_demo_auth

router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class Registration(Login):
    model_config = {"extra": "forbid"}
    age: int = Field(strict=True, ge=1, le=120)
    address: str = Field(min_length=5, max_length=500)
    consent: StrictBool
    consent_version: str


@router.get("/consent")
def consent(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {"version": privacy.CONSENT_VERSION, "text": privacy.CONSENT_TEXT}


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request):
    import re
    from uuid import uuid4
    import sqlite3
    allowed = {"http://127.0.0.1:5173", "http://localhost:5173"}
    allowed.update(x.strip() for x in os.getenv("GUARDIAN_FRONTEND_ORIGINS", "").split(","))
    if request.headers.get("origin") and request.headers["origin"] not in allowed:
        raise HTTPException(403, "Origin is not allowed.")
    username = payload.username.strip().lower()
    if len(payload.address.strip()) < 5:
        raise HTTPException(422, "Enter an address of at least five characters.")
    if payload.consent is not True or payload.consent_version != privacy.CONSENT_VERSION:
        raise HTTPException(422, "Accept the current privacy notice before registration.")
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "testserver"}:
        raise HTTPException(400, "Use HTTPS to register.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@+-]{2,99}", username) or len(payload.password) < 12:
        raise HTTPException(422, "Use a username of 3–100 characters and a password of at least 12 characters.")
    salt = secrets.token_hex(16)
    hashed = password_hash(payload.password, salt)
    protected_username = privacy.username_key(username)
    encrypted = privacy.encrypt_profile(username, payload.age, payload.address.strip())
    user_id = str(uuid4())
    try:
        with db() as conn:
            if conn.execute("SELECT 1 FROM operator WHERE lower(username)=?", (username,)).fetchone():
                raise HTTPException(409, "Username unavailable.")
            if conn.execute("SELECT 1 FROM users WHERE username IN (?,?)", (username, protected_username)).fetchone():
                raise HTTPException(409, "Username unavailable.")
            conn.execute("INSERT INTO users VALUES (?,?,?,?,?)", (user_id, protected_username, salt, hashed, secrets.token_urlsafe(32)))
            conn.execute("INSERT INTO registration_profiles VALUES (?,?,?,?)", (user_id, encrypted, privacy.CONSENT_VERSION, datetime.now(timezone.utc).isoformat()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username unavailable.") from None
    return {"registered": True}


@router.post("/login")
def login(payload: Login, request: Request, response: Response):
    allowed = {"http://127.0.0.1:5173", "http://localhost:5173"}
    allowed.update(os.getenv("GUARDIAN_FRONTEND_ORIGINS", "").split(","))
    if request.headers.get("origin") and request.headers["origin"] not in allowed:
        raise HTTPException(403, "Origin is not allowed.")
    now = time.time()
    address = digest(request.client.host if request.client else "unknown")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM login_attempts WHERE address=? AND attempted_at>?", (address, now - 900)).fetchone()[0] >= 10:
            raise HTTPException(429, "Try signing in again in 15 minutes.")
        username = payload.username.strip().lower()
        protected = privacy.username_key(username) if os.getenv('GUARDIAN_PII_ENCRYPTION_KEY') else ''
        row = conn.execute("SELECT *, id AS user_id FROM users WHERE username IN (?,?)", (username, protected)).fetchone()
        if row is None:
            row = conn.execute("SELECT *, 'demo-user' AS user_id FROM operator WHERE id=1").fetchone()
        matches = row and row['username'] in {username, protected}
        if not row or not hmac.compare_digest(password_hash(payload.password, row["salt"]), row["password_hash"]) or not matches:
            conn.execute("INSERT INTO login_attempts VALUES (?,?)", (address, now))
            conn.commit()
            raise HTTPException(401, "Invalid username or password.")
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=? OR expires_at<? OR last_seen<?", (digest(request.cookies.get("guardian_session", "")), now, now - 1800))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        if protected and row['user_id'] != 'demo-user':
            conn.execute('UPDATE users SET username=? WHERE id=?', (protected, row['user_id']))
        conn.execute("INSERT INTO auth_sessions(token_hash,csrf,expires_at,last_seen,user_id) VALUES (?,?,?,?,?)", (digest(token), csrf, now + 28800, now, row["user_id"]))
        conn.execute("DELETE FROM login_attempts WHERE attempted_at<?", (now - 900,))
    secure = request.url.scheme == "https" or os.getenv("GUARDIAN_COOKIE_SECURE") == "true"
    response.set_cookie("guardian_session", token, httponly=True, secure=secure, samesite="none" if secure else "lax", max_age=28800, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf}


@router.get('/profile')
def profile(response: Response, user=Depends(require_demo_auth)):
    response.headers['Cache-Control'] = 'no-store'
    with db() as conn:
        row = conn.execute('SELECT encrypted_profile FROM registration_profiles WHERE user_id=?', (user,)).fetchone()
    return privacy.masked_profile(row[0]) if row else {"username": "[hidden]", "age": "[hidden]", "address": "[hidden]"}


@router.get("/session")
def session(request: Request, response: Response, user=Depends(require_demo_auth)):
    response.headers["Cache-Control"] = "no-store"
    with db() as conn:
        row = conn.execute("SELECT csrf FROM auth_sessions WHERE token_hash=?", (digest(request.cookies["guardian_session"]),)).fetchone()
    return {"csrf_token": row["csrf"]}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(require_demo_auth)):
    with db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest(request.cookies["guardian_session"]),))
    response.delete_cookie("guardian_session", path="/")
    return {"signed_out": True}
