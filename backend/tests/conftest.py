"""Exercise the real mock-bank HTTP contract with an isolated database."""
import importlib.util
import os
import logging
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.adapters import bank

# Set before test modules import the application and configure its log handlers.
_test_logs = tempfile.TemporaryDirectory(prefix="guardian-test-logs-")
os.environ["GUARDIAN_LOG_DIR"] = str(Path(_test_logs.name) / "backend")
os.environ["MOCK_BANK_LOG_DIR"] = str(Path(_test_logs.name) / "bank")


def pytest_sessionfinish(session, exitstatus):
    logging.shutdown()
    _test_logs.cleanup()


@pytest.fixture(autouse=True)
def sandbox_bank(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('GUARDIAN_PII_ENCRYPTION_KEY', Fernet.generate_key().decode())
    spec = importlib.util.spec_from_file_location("guardian_test_bank", Path(__file__).resolve().parents[2] / "mock-bank" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "bank.db")
    monkeypatch.setenv("MOCK_BANK_URL", "http://bank.test")
    monkeypatch.setenv("MOCK_BANK_SERVICE_SECRET", "test-bank-service-secret")
    monkeypatch.setattr(bank, "start_warmup", lambda: None)
    with TestClient(module.app) as client:
        monkeypatch.setattr(bank.httpx, "request", lambda method, url, **kwargs: client.request(method, url, **kwargs))
        yield client
