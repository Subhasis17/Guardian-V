"""Authenticated HTTP boundary to the separate synthetic bank."""
import hashlib
import hmac
import os
import logging
from threading import Lock, Thread

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from typing import Literal
from app.database import current_user


_wake_lock = Lock()


def is_warming():
    return _wake_lock.locked()


def _wake_bank(url):
    logger = logging.getLogger('guardian')
    try:
        # A sleeping free Render service can take a minute to start. Only probe health.
        response = httpx.request('GET', url + '/health', timeout=httpx.Timeout(70, connect=5), follow_redirects=False)
        response.raise_for_status()
        health = response.json()
        if not isinstance(health, dict) or health.get('sandbox') is not True or health.get('status') != 'ok':
            raise ValueError('Invalid sandbox bank health response')
        logger.info('sandbox_bank_warmup_finished')
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning('sandbox_bank_warmup_failed type=%s', type(exc).__name__)
    finally:
        _wake_lock.release()


def start_warmup():
    url = os.getenv('MOCK_BANK_URL', '').rstrip('/')
    if not url or not _wake_lock.acquire(blocking=False):
        return
    try:
        Thread(target=_wake_bank, args=(url,), daemon=True).start()
    except RuntimeError:
        _wake_lock.release()



class Account(BaseModel):
    card_frozen: bool


class Transaction(BaseModel):
    id: str
    merchant: str
    amount: int = Field(ge=0)
    occurred_at: str
    status: str
    suspicious: bool


class Snapshot(BaseModel):
    sandbox: Literal[True]
    account: Account
    transactions: list[Transaction]


def request(method, path, body=None):
    url = os.getenv("MOCK_BANK_URL", "").rstrip("/")
    secret = os.getenv("MOCK_BANK_SERVICE_SECRET", "")
    if not url or not secret:
        raise HTTPException(503, "Configure the separate sandbox bank before using banking tools.")
    user = current_user.get()
    signature = hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()
    try:
        response = httpx.request(method, url + path, json=body, headers={"Authorization": "Bearer " + signature, "X-Guardian-User": user}, timeout=5, follow_redirects=False)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        logging.getLogger('guardian').warning('sandbox_bank_request_failed method=%s type=%s http_status=%s', method, type(exc).__name__, status)
        if method == 'GET' and (status is None or status in {502, 503, 504}):
            start_warmup()
        raise HTTPException(503, "Sandbox bank is unavailable; no real bank was contacted.") from None


def snapshot():
    try:
        return Snapshot.model_validate(request("GET", "/account")).model_dump()
    except ValidationError:
        raise HTTPException(502, "Sandbox bank returned invalid account data.") from None


def freeze(action_id):
    request("POST", "/card/freeze", {"idempotency_key": action_id})
    if not snapshot()["account"]["card_frozen"]:
        raise HTTPException(502, "Sandbox card freeze could not be verified.")
