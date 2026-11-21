from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from app.agent.followups import build_followups
from app.schemas import IncidentInput
from test_workflow import client_for
from app.adapters import google


def test_regulatory_milestones_require_confirmed_facts():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    payload = IncidentInput(summary="A scammer demanded money.")
    assert len(build_followups(payload, now)) == 2
    payload = IncidentInput(summary="An unauthorised payment occurred.", transaction_type="unauthorised", bank_complaint_received_on="2026-11-01", bank_shadow_reversal_due_on="2026-11-16")
    series = {item["key"]: item for item in build_followups(payload, now)}
    assert len(series) == 5
    assert series["shadow_reversal"]["due_at"].startswith("2026-11-16T10:00:00+05:30")
    assert series["resolution"]["due_at"].startswith("2027-01-30")
    assert series["escalation"]["due_at"].startswith("2026-12-02")
    authorised = payload.model_copy(update={"transaction_type": "authorised", "bank_shadow_reversal_due_on": None})
    assert len(build_followups(authorised, now)) == 3
    with pytest.raises(ValidationError):
        IncidentInput(summary="A scammer demanded money.", bank_shadow_reversal_due_on="2026-12-01")


def test_series_preserves_partial_results_and_rejects_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_INTEGRATION_MODE", "google")
    monkeypatch.setenv("GUARDIAN_TRUSTED_CONTACT_EMAIL", "trusted@example.com")
    monkeypatch.setattr(google, "access_token", lambda: "test-token")
    calls = []
    def schedule(*args):
        calls.append(args[0])
        if len(calls) == 2:
            raise TimeoutError()
        return "Verified calendar event"
    monkeypatch.setattr(google, "schedule", schedule)
    headers = {"Authorization": "Bearer test-secret"}
    with client_for(tmp_path, monkeypatch) as client:
        plan = client.post("/api/incidents", headers=headers, json={"summary": "A scammer demanded money."}).json()
        assert len(plan["followups"]) == 2
        assert calls == []
        action = next(a for a in plan["plan"] if a["kind"] == "followup")
        url = f"/api/incidents/{plan['incident']['id']}/actions/{action['id']}/approval"
        result = client.post(url, headers=headers, json={"approved": True}).json()
        assert [e["status"] for e in result["followups"]] == ["succeeded", "unverified"]
        assert client.post(url, headers=headers, json={"approved": True}).status_code == 409
        assert len(calls) == 2
