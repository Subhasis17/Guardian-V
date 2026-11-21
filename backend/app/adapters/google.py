"""Authorized Google APIs. No credentials or incident text enter error messages."""

import base64
import json
import os
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote
from urllib.request import Request, urlopen


def request(url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url, data=payload, headers=headers), timeout=15) as response:
        return json.load(response)


def access_token():
    from urllib.parse import urlencode

    names = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    from app.api.integrations import refresh_token_for_current_user
    refresh_token = refresh_token_for_current_user()
    if not all(os.getenv(name) for name in names) or not refresh_token:
        raise ValueError("Google OAuth credentials are missing")
    body = urlencode({"client_id": os.environ[names[0]],
                      "client_secret": os.environ[names[1]],
                      "refresh_token": refresh_token,
                      "grant_type": "refresh_token"}).encode()
    with urlopen(Request("https://oauth2.googleapis.com/token", data=body), timeout=15) as response:
        return json.load(response)["access_token"]


def notify(action_id, recipient, summary, token):
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = "Guardian incident summary (banking sandbox)"
    message["Message-ID"] = f"<guardian-{action_id}@guardian.invalid>"
    message.set_content("Shared with explicit approval. Banking actions are synthetic.\n\n" + summary)
    sent = request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", token,
                   {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()})
    verified = request("https://gmail.googleapis.com/gmail/v1/users/me/messages/" + quote(sent["id"], safe=""), token)
    if "SENT" not in verified.get("labelIds", []):
        raise RuntimeError("Sent message was not verified")
    return "Gmail accepted and verified the sent message; recipient delivery is not confirmed."


def schedule(action_id, due_at, token, title="Guardian follow-up", guidance="Review your Guardian incident and contact your bank through its official channel."):
    calendar = quote(os.getenv("GOOGLE_CALENDAR_ID", "primary"), safe="")
    base = f"https://www.googleapis.com/calendar/v3/calendars/{calendar}/events"
    event_id = action_id.replace("-", "")
    body = {"id": event_id, "summary": title,
            "description": guidance,
            "start": {"dateTime": due_at},
            "end": {"dateTime": (datetime.fromisoformat(due_at) + timedelta(minutes=15)).isoformat()},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}}
    from urllib.error import HTTPError
    try:
        request(base, token, body)
    except HTTPError as exc:
        if exc.code != 409:
            raise
    verified = request(base + "/" + event_id, token)
    if verified.get("status") == "cancelled" or verified.get("id") != event_id:
        raise RuntimeError("Calendar event was not verified")
    if datetime.fromisoformat(verified["start"]["dateTime"]) != datetime.fromisoformat(due_at):
        raise RuntimeError("Calendar event date does not match the approved reminder")
    return "Google Calendar follow-up created and verified: " + verified["start"]["dateTime"]
