import pytest
from fastapi import HTTPException
from app import database
from app.adapters import bank


def test_account_isolation_freeze_readback_and_duplicate_prevention(sandbox_bank):
    marker = database.current_user.set("alice")
    try:
        alice = bank.snapshot()
        bank.freeze("alice-freeze-action")
        bank.freeze("alice-freeze-action")
        assert bank.snapshot()["account"]["card_frozen"] is True
        database.current_user.set("bob")
        bob = bank.snapshot()
        assert not bob["account"]["card_frozen"]
        assert alice["transactions"] != bob["transactions"]
        with pytest.raises(HTTPException):
            bank.freeze("alice-freeze-action")
        assert not bank.snapshot()["account"]["card_frozen"]
        response = sandbox_bank.get("/account", headers={"X-Guardian-User": "bob", "Authorization": "Bearer invalid"})
        assert response.status_code == 401
    finally:
        database.current_user.reset(marker)


def test_missing_bank_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("MOCK_BANK_SERVICE_SECRET")
    with pytest.raises(HTTPException) as exc:
        bank.snapshot()
    assert exc.value.status_code == 503


def test_bank_outage_preserves_local_approvals(tmp_path, monkeypatch):
    from test_workflow import client_for
    with client_for(tmp_path, monkeypatch) as client:
        client.headers['Authorization'] = 'Bearer test-secret'
        plan = client.post('/api/incidents', json={'summary': 'An impersonator demanded money.'}).json()
        def unavailable():
            raise HTTPException(503, 'Sandbox bank unavailable')
        monkeypatch.setattr(bank, 'snapshot', unavailable)
        result = client.get('/api/context')
        assert result.status_code == 200
        data = result.json()
        assert not data['bank_available']
        assert data['account']['card_frozen'] is None
        assert data['pending_approvals']
        assert data['incidents'][0]['id'] == plan['incident']['id']
        assert client.post('/api/tools/get_recent_transactions', json={}).status_code == 503


def test_existing_bank_snapshot_does_not_take_write_lock(sandbox_bank):
    import sqlite3
    bank.snapshot()
    module_path = sandbox_bank.app
    # Hold the SQLite writer lock while another connection serves an existing account.
    endpoint = next(r.endpoint for r in module_path.routes if r.path == '/account')
    path = endpoint.__globals__['DB_PATH']
    with sqlite3.connect(path) as writer:
        writer.execute('BEGIN IMMEDIATE')
        assert bank.snapshot()['sandbox'] is True


def test_bank_failure_is_persisted_without_claiming_success(tmp_path, monkeypatch):
    from test_workflow import client_for
    with client_for(tmp_path, monkeypatch) as client:
        headers = {"Authorization": "Bearer test-secret"}
        plan = client.post("/api/incidents", headers=headers, json={"summary": "An impersonator threatened me for money."}).json()
        action = next(a for a in plan["plan"] if a["kind"] == "freeze_card")
        def unavailable(action_id):
            raise HTTPException(503, "Sandbox bank unavailable")
        monkeypatch.setattr(bank, "freeze", unavailable)
        result = client.post(f"/api/incidents/{plan['incident']['id']}/actions/{action['id']}/approval", headers=headers, json={"approved": True})
        assert result.status_code == 503
        persisted = client.get(f"/api/incidents/{plan['incident']['id']}", headers=headers).json()
        assert next(a for a in persisted["plan"] if a["kind"] == "freeze_card")["status"] == "failed"
        assert client.get("/api/context", headers=headers).json()["account"]["card_frozen"] is False
