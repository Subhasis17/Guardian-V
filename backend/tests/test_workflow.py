from fastapi.testclient import TestClient

from app import main


def test_agora_saved_agent_builds_with_public_tools(monkeypatch):
    from agora_agent.agentkit.v3 import build_body
    from agora_agent.v3.contract import validate_write
    from app.voice_config import build_guardian_agent, get_voice_profile

    monkeypatch.setenv("GUARDIAN_PUBLIC_API_URL", "https://guardian.example")
    monkeypatch.setenv("DEMO_API_TOKEN", "test-secret")
    agent = build_guardian_agent(object(), get_voice_profile("default"), "guardian_voice")
    body = build_body(agent, "Guardian")
    assert body["pipeline"]["llm"]["vendor"] == "custom"
    assert body["pipeline"]["llm"]["url"] == "https://ai-gateway.vercel.sh/v1/chat/completions"
    assert len(body["pipeline"]["llm"]["tools"]) == 8
    validate_write("POST", "/conversational-ai/v1/projects/test-app/agents", body)


def test_voice_diagnostics_exclude_secrets_and_require_auth(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        with main.db() as conn:
            conn.execute("INSERT INTO voice_sessions(id,agora_session_id,channel,user_uid,agent_uid,status,created_at,profile_id) VALUES ('test-session',NULL,'private-channel',1,2,'prepared','2026-11-20T00:00:00+00:00','default')")
        url = "/api/voice/sessions/test-session"
        h = {"Authorization": "Bearer test-secret"}
        assert client.get(url + "/diagnostics").status_code == 401
        assert client.post(url + "/events", headers=h, json={"event": "mic_published", "transcript": "private"}).status_code == 422
        assert client.post(url + "/events", headers=h, json={"event": "arbitrary secret"}).status_code == 422
        assert client.post(url + "/events", headers=h, json={"event": "mic_published"}).status_code == 200
        result = client.get(url + "/diagnostics", headers=h).json()
        assert result["events"][0]["event"] == "mic_published"
        assert result["session"]["status"] == "prepared"
        assert "private-channel" not in str(result)
        assert "test-secret" not in str(result)
        assert client.get("/api/voice/sessions/missing/diagnostics", headers=h).status_code == 404


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


def test_tool_allowlist_and_approval_boundary(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        h = {"Authorization": "Bearer test-secret"}
        assert client.get("/api/tools").status_code == 401
        assert len(client.get("/api/tools", headers=h).json()) == 8
        assert client.post("/api/tools/shell", headers=h, json={}).status_code == 404
        args = {"summary": "Police impersonator demanded money.", "idempotency_key": "incident-001"}
        first = client.post("/api/tools/create_incident", headers=h, json=args).json()["data"]
        second = client.post("/api/tools/create_incident", headers=h, json=args).json()["data"]
        assert first["incident"]["id"] == second["incident"]["id"]
        incident_scope = {"incident_id": first["incident"]["id"]}
        reminder = client.post("/api/tools/schedule_followup", headers=h, json=incident_scope).json()
        assert reminder["data"]["action"]["result"]
        report = client.post("/api/tools/generate_report", headers=h, json=incident_scope).json()
        assert "not a bank or police report" in report["data"]["content"]
        notify = next(a for a in first["plan"] if a["kind"] == "notify_contact")
        assert client.post("/api/tools/notify_trusted_contact", headers=h, json={**incident_scope, "action_id": notify["id"]}).json()["status"] == "awaiting_approval"
        freeze = next(a for a in first["plan"] if a["kind"] == "freeze_card")
        scope = {"incident_id": first["incident"]["id"], "action_id": freeze["id"]}
        result = client.post("/api/tools/freeze_demo_card", headers=h, json=scope).json()
        assert result["status"] == "awaiting_approval"
        assert client.post("/api/tools/freeze_demo_card", headers=h, json={**scope, "approved": True}).status_code == 422
        assert client.get("/api/context", headers=h).json()["account"]["card_frozen"] is False
        assert client.post(result["data"]["approval_url"], headers=h, json={"approved": True}).status_code == 200
        assert client.post("/api/tools/freeze_demo_card", headers=h, json=scope).json()["status"] == "succeeded"
        assert client.post("/api/tools/create_incident", headers=h, json={**args, "summary": "A different incident description."}).status_code == 409


def test_tools_preserve_scope_and_secret_validation(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        h = {"Authorization": "Bearer test-secret"}
        assert client.post("/api/tools/get_user_context", headers=h, json={"user_id": "someone-else"}).status_code == 422
        assert client.post("/api/tools/create_incident", headers=h, json={"summary": "My OTP is 123456 and I was scammed.", "idempotency_key": "secret-test"}).status_code == 422
        assert client.post("/api/tools/generate_report", headers=h, json={"incident_id": "missing"}).status_code == 404
        for name in ("get_user_context", "get_recent_transactions", "get_incident_history"):
            result = client.post(f"/api/tools/{name}", headers=h, json={}).json()
            assert result["sandbox"] is True and result["status"] == "succeeded"


def test_voice_profiles_are_dynamic_and_do_not_expose_murf_voice_id(tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_VOICE_PROFILES_JSON", '[{"id":"hindi","label":"Hindi","asr_language":"hi","tts_locale":"hi-IN","tts_voice_id":"configured-server-side","reply_language":"Hindi","greeting":"Namaste, I am Guardian.","auto_detect_input":false}]')
    with client_for(tmp_path, monkeypatch) as client:
        response = client.get("/api/voice/config", headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 200
        config = response.json()
        assert [profile["id"] for profile in config["profiles"]] == ["default", "auto", "hindi"]
        auto = next(profile for profile in config["profiles"] if profile["id"] == "auto")
        assert auto["asr_language"] == "multi" and auto["auto_detect_input"] is True
        assert "tts_voice_id" not in str(config)


def test_invalid_voice_profile_configuration_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_VOICE_PROFILES_JSON", "not-json")
    with client_for(tmp_path, monkeypatch) as client:
        response = client.get("/api/voice/config", headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 503
