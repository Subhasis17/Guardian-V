"""Authentication for the shared demo identity."""

import hmac
import os
import hashlib
import time
from fastapi import Request, HTTPException
from app.database import db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def require_demo_auth(request: Request):
    now = time.time()
    key = digest(request.cookies.get("guardian_session", ""))
    with db() as conn:
        row = conn.execute("SELECT * FROM auth_sessions WHERE token_hash=?", (key,)).fetchone()
        if not row or row["expires_at"] <= now or row["last_seen"] + 1800 <= now:
            raise HTTPException(401, "Sign in to Guardian.")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), row["csrf"]):
            raise HTTPException(403, "Session verification failed.")
        conn.execute("UPDATE auth_sessions SET last_seen=? WHERE token_hash=?", (now, key))
    return row["user_id"]
