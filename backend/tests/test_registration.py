from app.privacy import username_key
from fastapi.testclient import TestClient
from app import main, database


def test_registration_isolates_users_and_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "users.db")
    main._requests.clear()
    with TestClient(main.app) as alice, TestClient(main.app) as bob:
        for client, name in ((alice, "alice"), (bob, "bob")):
            data = {"username": name, "password": "long-password-for-test", "age": 30, "address": "Synthetic test address", "consent": True, "consent_version": "2026-11-21-v1"}
            assert client.post("/api/auth/register", json=data).status_code == 201
            assert client.post("/api/auth/register", json=data).status_code == 409
            response = client.post("/api/auth/login", json=data)
            assert response.status_code == 200
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        incident = alice.post("/api/incidents", json={"summary": "A police impersonator demanded money."}).json()
        iid = incident["incident"]["id"]
        freeze = next(a for a in incident["plan"] if a["kind"] == "freeze_card")
        assert bob.get(f"/api/incidents/{iid}").status_code == 404
        assert bob.get(f"/api/incidents/{iid}/report").status_code == 404
        assert bob.post(f"/api/incidents/{iid}/actions/{freeze['id']}/approval", json={"approved": True}).status_code == 404
        assert bob.get("/api/context").json()["incidents"] == []
        assert alice.post(f"/api/incidents/{iid}/actions/{freeze['id']}/approval", json={"approved": True}).status_code == 200
        assert alice.get("/api/context").json()["account"]["card_frozen"] is True
        assert bob.get("/api/context").json()["account"]["card_frozen"] is False
        with database.db() as conn:
            bob_token = conn.execute("SELECT tool_token FROM users WHERE username=?", ( username_key("bob"),)).fetchone()[0]
        result = bob.post("/api/agent-tools/generateReport", headers={"Authorization": "Bearer " + bob_token}, json={"arguments": {"incident_id": iid}, "tool_call_id": "cross-user"})
        assert result.status_code == 404
        assert bob.get("/api/voice/sessions/another-users-session/diagnostics").status_code == 404
