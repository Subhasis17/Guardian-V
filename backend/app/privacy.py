"""Registration profile protection. Keys must be backed up separately from SQLite."""
import hashlib
import hmac
import json
import os
from cryptography.fernet import Fernet
from fastapi import HTTPException

CONSENT_VERSION = "2026-11-21-v1"
CONSENT_TEXT = "Guardian stores your username, age and address to maintain your account profile. Profile fields are encrypted at rest and masked in responses. Passwords are hashed. HTTPS protects submissions in production. These profile fields are not sent to the voice agent, bank or Google. Voice, incident summaries and Google actions have separate data flows; do not include sensitive credentials. You can decline before account creation."


def cipher():
    try:
        return Fernet(os.environ["GUARDIAN_PII_ENCRYPTION_KEY"].encode())
    except (KeyError, ValueError):
        raise HTTPException(503, "Account privacy protection is not configured.") from None


def username_key(username):
    cipher()
    return "protected:" + hmac.new(os.environ["GUARDIAN_PII_ENCRYPTION_KEY"].encode(), username.encode(), hashlib.sha256).hexdigest()


def encrypt_profile(username, age, address):
    return cipher().encrypt(json.dumps({"username": username, "age": age, "address": address}).encode()).decode()


def masked_profile(encrypted):
    profile = json.loads(cipher().decrypt(encrypted.encode()))
    return {"username": profile["username"][0] + "***", "age": "***", "address": "[hidden]"}
