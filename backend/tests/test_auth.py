import secrets
import time
from fastapi.testclient import TestClient
from app import main, database
from app.security import password_hash


def test_sessions_csrf_expiry_logout_and_legacy_token_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "auth.db")
    main._requests.clear()
    with TestClient(main.app) as client:
        salt = secrets.token_hex(16)
        with database.db() as conn:
            conn.execute("INSERT INTO operator VALUES (1,?,?,?)", ("operator", salt, password_hash("a-long-test-password", salt)))
        assert client.get("/api/context", headers={"Authorization": "Bearer test-secret"}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "operator", "password": "wrong"}).status_code == 401
        login = client.post("/api/auth/login", json={"username": "operator", "password": "a-long-test-password"})
        assert "HttpOnly" in login.headers["set-cookie"]
        csrf = login.json()["csrf_token"]
        assert client.get("/api/context").status_code == 200
        assert client.post("/api/incidents", json={"summary": "Someone threatened me for money."}).status_code == 403
        assert client.get("/api/auth/session").json()["csrf_token"] == csrf
        assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/context").status_code == 401
        client.post("/api/auth/login", json={"username": "operator", "password": "a-long-test-password"})
        with database.db() as conn:
            conn.execute("UPDATE auth_sessions SET last_seen=?", (time.time()-1801,))
        assert client.get("/api/context").status_code == 401
