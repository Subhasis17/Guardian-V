import json
import os
from pathlib import Path
from app.logging_setup import configure_logs


def test_logs_redact_tokens_and_oauth_query(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "private-test-secret")
    logger, access = configure_logs(tmp_path, "test_guardian_logs")
    logger.info("request https://example.com/callback?code=private-code secret=private-test-secret")
    logger.error("tool_failed")
    access.info("method=GET route=/health status=200")
    info = (tmp_path / "info.log").read_text()
    assert "private-code" not in info
    assert "private-test-secret" not in info
    assert "tool_failed" not in info
    assert "tool_failed" in (tmp_path / "error.log").read_text()
    assert "tool_failed" in (tmp_path / "tools.log").read_text()
    assert json.loads((tmp_path / "access.log").read_text())["message"].endswith("status=200")


def test_rejected_tool_requests_are_logged_before_execution(tmp_path, monkeypatch):
    from test_workflow import client_for
    with client_for(tmp_path, monkeypatch) as client:
        response = client.post("/api/agent-tools/getUserContext", json={"arguments": {}, "tool_call_id": "test"})
        assert response.status_code == 401
        response = client.post("/api/agent-tools/getUserContext", json={"invalid": "private-input"})
        assert response.status_code == 422
    log = (Path(os.environ["GUARDIAN_LOG_DIR"]) / "tools.log").read_text()
    assert "tool_request_received tool=getUserContext" in log
    assert "http_status=401" in log and "http_status=422" in log
    assert "private-input" not in log
