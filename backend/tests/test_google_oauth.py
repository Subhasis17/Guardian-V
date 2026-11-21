from app.privacy import username_key
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import database, main
from app.api import integrations


def test_google_oauth_connect_callback_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "oauth.db")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GUARDIAN_FRONTEND_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/integrations/google/callback")
    monkeypatch.setenv("GOOGLE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(integrations, "_exchange", lambda code, config: {"refresh_token": "refresh-secret"})
    with TestClient(main.app) as client:
        credentials = {"username": "oauth-user", "password": "long-password-for-test", "age": 30, "address": "Synthetic test address", "consent": True, "consent_version": "2026-11-21-v1"}
        assert client.post("/api/auth/register", json=credentials).status_code == 201
        login = client.post("/api/auth/login", json=credentials)
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        connect = client.get("/api/integrations/google/connect", follow_redirects=False)
        assert connect.status_code == 307
        assert "access_type=offline" in connect.headers["location"]
        assert "prompt=consent" in connect.headers["location"]
        callback = client.get("/api/integrations/google/callback?code=abc&state=" + connect.headers["location"].split("state=")[1], follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == "http://127.0.0.1:5173"
        assert callback.headers["referrer-policy"] == "no-referrer"
        assert client.get("/api/integrations/google/status").json()["connected"] is True
        blocked = client.post('/api/incidents', json={'summary': 'An impersonator demanded money.'})
        assert blocked.status_code == 409
        assert 'trusted contact' in blocked.json()['detail']
        assert client.post("/api/integrations/google/contact", json={"email": "friend@example.com"}).status_code == 200
        plan = client.post('/api/incidents', json={'summary': 'An impersonator demanded money.'}).json()
        calendar = next(a for a in plan['plan'] if a['kind'] == 'followup')
        for event in plan['followups']:
            assert event['due_at'] in calendar['title']
        assert client.get("/api/integrations/google/status").json()["trusted_contact_email"] == "friend@example.com"
        from app.services.external import configuration
        user_id = None
        with database.db() as conn:
            user_id = conn.execute("SELECT id FROM users WHERE username=?", (username_key("oauth-user"),)).fetchone()[0]
        token = database.current_user.set(user_id)
        try:
            with database.db() as conn:
                stored = conn.execute("SELECT refresh_token FROM google_oauth").fetchone()[0]
            assert configuration() == ("google", "friend@example.com")
        finally:
            database.current_user.reset(token)
        assert stored != "refresh-secret"
        assert client.post("/api/integrations/google/disconnect").json()["connected"] is False
        assert client.get("/api/integrations/google/status").json()["connected"] is False


def test_google_connection_is_account_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "accounts.db")
    with TestClient(main.app) as first, TestClient(main.app) as second:
        for client, name in ((first, "first"), (second, "second")):
            credentials = {"username": name, "password": "long-password-for-test", "age": 30, "address": "Synthetic test address", "consent": True, "consent_version": "2026-11-21-v1"}
            assert client.post("/api/auth/register", json=credentials).status_code == 201
            login = client.post("/api/auth/login", json=credentials)
            client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert first.post("/api/integrations/google/contact", json={"email": "first@example.com"}).status_code == 200
        assert second.get("/api/integrations/google/status").json()["trusted_contact_email"] == ""
