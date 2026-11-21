"""Freeze approved intent before network I/O; never blindly replay a send."""

import json
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.database import db, audit
from app.adapters import google


def configuration():
    from app.database import current_user
    if current_user.get() != "demo-user":
        with db() as conn:
            connection = conn.execute("SELECT refresh_token FROM google_oauth WHERE id=1").fetchone()
            contact = conn.execute("SELECT trusted_contact_email FROM integration_settings WHERE id=1").fetchone()
        if not connection or not connection[0]:
            return "sandbox", ""
        if not contact or not contact[0]:
            raise HTTPException(409, "Save a trusted contact email before creating a Google-connected incident.")
        return "google", contact[0] if contact else ""
    mode = os.getenv("GUARDIAN_INTEGRATION_MODE", "sandbox")
    if mode not in {"sandbox", "google"}:
        raise HTTPException(503, "GUARDIAN_INTEGRATION_MODE must be sandbox or google.")
    recipient = os.getenv("GUARDIAN_TRUSTED_CONTACT_EMAIL", "")
    if mode == "google" and ("@" not in recipient or any(c in recipient for c in "\r\n")):
        raise HTTPException(503, "Set a trusted contact email before starting a live incident.")
    return mode, recipient


def execute(incident_id, action_id):
    # Claim and commit before sending; a crash leaves a visible, non-retryable running action.
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        from app.agent.plan import check_dependencies
        check_dependencies(conn, incident_id, action_id)
        action = conn.execute("SELECT * FROM actions WHERE id=? AND incident_id=?", (action_id, incident_id)).fetchone()
        if not action or action["status"] != "awaiting_approval":
            raise HTTPException(409, "Action is no longer awaiting approval.")
        if datetime.now(timezone.utc) - datetime.fromisoformat(action["created_at"]) > timedelta(minutes=20):
            raise HTTPException(410, "Approval expired.")
        intent = json.loads(action["result"])
        if intent["kind"] == "notify_contact":
            summary = conn.execute("SELECT summary FROM incidents WHERE id=?", (incident_id,)).fetchone()[0]
        conn.execute("UPDATE actions SET status='running', approved_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), action_id))
        audit(conn, incident_id, "approval_granted", action["kind"])
    try:
        token = google.access_token()
        if intent["kind"] == "notify_contact":
            result = google.notify(action_id, intent["recipient"], summary, token)
        elif intent.get("series"):
            with db() as conn:
                events = conn.execute("SELECT * FROM followup_events WHERE incident_id=? ORDER BY rowid", (incident_id,)).fetchall()
            for event in events:
                details = json.loads(event["details"])
                outcome = google.schedule(event["id"], details["due_at"], token, details["title"], details["guidance"] + ("\nSource: " + details["source"] if details["source"] else ""))
                with db() as conn:
                    conn.execute("UPDATE followup_events SET status='succeeded', result=? WHERE id=?", (outcome, event["id"]))
                    audit(conn, incident_id, "followup_verified", details["key"])
            result = f"Created and verified {len(events)} Google Calendar follow-up events."
        else:
            result = google.schedule(action_id, intent["due_at"], token)
        status = "succeeded"
    except Exception:
        status = "failed"
        result = "Provider outcome is unverified. Check the Google account before retrying; automatic resend is disabled."
    with db() as conn:
        conn.execute("UPDATE actions SET status=?, result=? WHERE id=?", (status, result, action_id))
        if status == "failed" and intent.get("series"):
            conn.execute("UPDATE followup_events SET status='unverified', result='Series stopped after a provider failure; check Google Calendar before retrying.' WHERE incident_id=? AND status!='succeeded'", (incident_id,))
        audit(conn, incident_id, "external_action_" + status, action["kind"])
        pending = conn.execute("SELECT COUNT(*) FROM actions WHERE incident_id=? AND status IN ('pending','running','awaiting_approval')", (incident_id,)).fetchone()[0]
        if not pending:
            failed = conn.execute("SELECT COUNT(*) FROM actions WHERE incident_id=? AND status != 'succeeded'", (incident_id,)).fetchone()[0]
            conn.execute("UPDATE incidents SET status=? WHERE id=?", ("action_incomplete" if failed else "resolved_in_sandbox", incident_id))
