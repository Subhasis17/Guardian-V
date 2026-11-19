from fastapi.testclient import TestClient

from app import main


def client_for(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setenv("DEMO_API_TOKEN", "test-secret")
    return TestClient(main.app)


def test_plan_requires_approval_then_freezes_only_demo_account(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        headers = {"Authorization": "Bearer test-secret"}
        context = client.get("/api/context", headers=headers).json()
        assert context["sandbox"] is True
        assert context["account"]["card_frozen"] is False
        assert any(row["suspicious"] for row in context["transactions"])

        plan = client.post("/api/incidents", headers=headers, json={"summary": "A caller threatened me and asked me to send money."}).json()
        freeze = next(action for action in plan["plan"] if action["kind"] == "freeze_card")
        assert freeze["status"] == "awaiting_approval"

        completed = client.post(f"/api/incidents/{plan['incident']['id']}/actions/{freeze['id']}/approval", headers=headers, json={"approved": True})
        assert completed.status_code == 200
        assert next(action for action in completed.json()["plan"] if action["id"] == freeze["id"])["status"] == "succeeded"
        assert client.get("/api/context", headers=headers).json()["account"]["card_frozen"] is True

        repeated = client.post(f"/api/incidents/{plan['incident']['id']}/actions/{freeze['id']}/approval", headers=headers, json={"approved": True})
        assert repeated.status_code == 409


def test_authentication_and_sensitive_summary_validation(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        assert client.get("/api/context").status_code == 401
        response = client.post("/api/incidents", headers={"Authorization": "Bearer test-secret"}, json={"summary": "My OTP is 123456 and I was scammed."})
        assert response.status_code == 422


def test_declined_action_cannot_be_executed_later(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        headers = {"Authorization": "Bearer test-secret"}
        plan = client.post("/api/incidents", headers=headers, json={"summary": "A caller asked me to transfer money."}).json()
        freeze = next(action for action in plan["plan"] if action["kind"] == "freeze_card")
        url = f"/api/incidents/{plan['incident']['id']}/actions/{freeze['id']}/approval"
        assert client.post(url, headers=headers, json={"approved": False}).status_code == 200
        assert client.post(url, headers=headers, json={"approved": True}).status_code == 409
        assert client.get("/api/context", headers=headers).json()["account"]["card_frozen"] is False


def test_report_is_explicitly_labeled_sandbox(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        headers = {"Authorization": "Bearer test-secret"}
        plan = client.post("/api/incidents", headers=headers, json={"summary": "Someone impersonated police and demanded a transfer."}).json()
        report = client.get(f"/api/incidents/{plan['incident']['id']}/report", headers=headers).json()
        assert report["sandbox"] is True
        assert "not a bank or police report" in report["content"]
