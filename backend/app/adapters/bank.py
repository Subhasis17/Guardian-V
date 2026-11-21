"""Authenticated HTTP boundary to the separate synthetic bank."""
import hashlib
import hmac
import os

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from typing import Literal
from app.database import current_user


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
    except (httpx.HTTPError, ValueError):
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
