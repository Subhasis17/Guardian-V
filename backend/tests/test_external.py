from test_workflow import client_for
from app import database
from app.adapters import google


def test_google_actions_require_approval_verify_and_prevent_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_INTEGRATION_MODE", "google")
    monkeypatch.setenv("GUARDIAN_TRUSTED_CONTACT_EMAIL", "trusted@example.com")
    calls = []
    monkeypatch.setattr(google, "access_token", lambda: "mock-token")
    monkeypatch.setattr(google, "notify", lambda *args: calls.append("email") or "Verified sent message")
    monkeypatch.setattr(google, "schedule", lambda *args: calls.append("calendar") or "Verified calendar event")
    h = {"Authorization": "Bearer test-secret"}
    with client_for(tmp_path, monkeypatch) as client:
        plan = client.post("/api/tools/create_incident", headers=h, json={"summary": "Police impersonator demanded money.", "idempotency_key": "external-workflow"}).json()["data"]
        incident = plan["incident"]["id"]
        assert calls == []
        for action in plan["plan"]:
            if action["status"] == "awaiting_approval":
                assert action["depends_on"]
                url = f"/api/incidents/{incident}/actions/{action['id']}/approval"
                assert client.post(url, headers=h, json={"approved": True}).status_code == 200
                assert client.post(url, headers=h, json={"approved": True}).status_code == 409
        assert calls == ["email", "calendar", "calendar"]
        assert client.get("/api/context", headers=h).json()["account"]["card_frozen"]


def test_provider_failure_is_persisted_without_resend(tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_INTEGRATION_MODE", "google")
    monkeypatch.setenv("GUARDIAN_TRUSTED_CONTACT_EMAIL", "trusted@example.com")
    def fail():
        raise TimeoutError("private provider information")
    monkeypatch.setattr(google, "access_token", fail)
    h = {"Authorization": "Bearer test-secret"}
    with client_for(tmp_path, monkeypatch) as client:
        plan = client.post("/api/incidents", headers=h, json={"summary": "Police impersonator demanded money."}).json()
        action = next(a for a in plan["plan"] if a["kind"] == "notify_contact")
        url = f"/api/incidents/{plan['incident']['id']}/actions/{action['id']}/approval"
        result = client.post(url, headers=h, json={"approved": True}).json()
        failed = next(a for a in result["plan"] if a["id"] == action["id"])
        assert failed["status"] == "failed"
        assert "private" not in failed["result"]
        assert client.post(url, headers=h, json={"approved": True}).status_code == 409


def test_google_adapter_reads_back_outcomes(monkeypatch):
    calls = []
    def fake(url, token=None, body=None):
        calls.append((url, body))
        if "gmail" in url:
            return {"id": "sent", "labelIds": ["SENT"]}
        return {"id": "abc123", "start": {"dateTime": "2026-12-01T10:00:00+00:00"}}
    monkeypatch.setattr(google, "request", fake)
    google.notify("abc123", "trusted@example.com", "Test summary", "token")
    google.schedule("abc123", "2026-12-01T10:00:00+00:00", "token")
    assert len(calls) == 4
    assert calls[0][1] and calls[1][1] is None
    assert calls[2][1]["id"] == "abc123" and calls[3][1] is None


def test_dependencies_block_action_until_investigation_succeeds(tmp_path, monkeypatch):
    h = {"Authorization": "Bearer test-secret"}
    with client_for(tmp_path, monkeypatch) as client:
        plan = client.post("/api/incidents", headers=h, json={"summary": "Police impersonator demanded money."}).json()
        incident = plan["incident"]["id"]
        freeze = next(a for a in plan["plan"] if a["kind"] == "freeze_card")
        with database.db() as conn:
            conn.execute("UPDATE actions SET status='failed' WHERE incident_id=? AND kind='investigate'", (incident,))
        url = f"/api/incidents/{incident}/actions/{freeze['id']}/approval"
        assert client.post(url, headers=h, json={"approved": True}).status_code == 409
        assert not client.get("/api/context", headers=h).json()["account"]["card_frozen"]


def test_post_rate_limit_returns_retry_after(tmp_path, monkeypatch):
    from app import main
    from collections import deque
    import time
    with client_for(tmp_path, monkeypatch) as client:
        main._requests["testclient"] = deque([time.monotonic()] * 120)
        result = client.post("/api/incidents", json={})
        assert result.status_code == 429 and result.headers["Retry-After"] == "60"
        main._requests.clear()
