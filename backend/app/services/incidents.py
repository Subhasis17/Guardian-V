"""Sandbox incident planning, approval execution, and reports."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from app.database import db, as_dicts, audit, user_scoped
from app.schemas import IncidentInput, ApprovalInput
from app.security import require_demo_auth
from app.adapters import bank


def bank_context():
    snapshot = bank.snapshot()
    # Keep an investigation snapshot for persisted incident assessment.
    with db() as conn:
        conn.execute("DELETE FROM transactions")
        conn.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?)", [
            (t["id"], t["merchant"], t["amount"], t["occurred_at"], t["status"], t["suspicious"])
            for t in snapshot["transactions"]])
    return snapshot


@user_scoped
def context(user=Depends(require_demo_auth)):
    bank_error = None
    try:
        banking = bank_context()
    except HTTPException as exc:
        bank_error = exc.detail
        banking = {"account": {"card_frozen": None}, "transactions": []}
    with db() as conn:
        expired = conn.execute(
            "SELECT id, incident_id, kind FROM actions WHERE status='awaiting_approval' AND created_at < ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),),
        ).fetchall()
        for action in expired:
            changed = conn.execute(
                "UPDATE actions SET status='expired' WHERE id=? AND status='awaiting_approval'",
                (action["id"],),
            ).rowcount
            if changed:
                if action["kind"] == "followup":
                    conn.execute("UPDATE followup_events SET status='expired' WHERE incident_id=? AND status='awaiting_approval'", (action["incident_id"],))
                audit(conn, action["incident_id"], "approval_expired", action["kind"])
                conn.execute(
                    "UPDATE incidents SET status='action_incomplete' WHERE id=? AND NOT EXISTS (SELECT 1 FROM actions WHERE incident_id=? AND status IN ('awaiting_approval','pending'))",
                    (action["incident_id"], action["incident_id"]),
                )
        incidents = as_dicts(
            conn.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall()
        )
        reminders = as_dicts(
            conn.execute(
                "SELECT * FROM actions WHERE kind='followup' ORDER BY created_at DESC"
            ).fetchall()
        )
        contact = conn.execute("SELECT trusted_contact_email FROM integration_settings WHERE id=1").fetchone()
        approvals = as_dicts(conn.execute("""
            SELECT a.id, a.incident_id, a.kind, a.title, a.status, a.result,
                   i.summary AS incident_summary
            FROM actions a JOIN incidents i ON i.id=a.incident_id
            WHERE a.status='awaiting_approval'
            ORDER BY a.created_at DESC
        """).fetchall())
    return {
        "sandbox": True,
        "profile": {
            "name": "Your sandbox account",
            "trusted_contact": contact[0] if contact else "No trusted contact configured",
        },
        "account": banking["account"],
        "bank_available": bank_error is None,
        "bank_error": bank_error,
        "transactions": banking["transactions"],
        "incidents": incidents,
        "followups": reminders,
        "pending_approvals": approvals,
    }


@user_scoped
def create_incident(payload: IncidentInput, user=Depends(require_demo_auth)):
    bank_context()
    from app.services.external import configuration
    mode, recipient = configuration()
    incident_id, now = str(uuid4()), datetime.now(timezone.utc).isoformat()
    from app.agent.followups import build_followups
    followups = build_followups(payload, datetime.fromisoformat(now))
    facts = payload.model_dump_json(exclude={"summary", "incident_type", "idempotency_key"})
    plan = [
        ("investigate", "Review recent demo transactions", "succeeded", None),
        ("freeze_card", "Freeze the demo card", "awaiting_approval", None),
        (
            "notify_contact",
            "Notify trusted contact (sandbox outbox)",
            "awaiting_approval",
            None,
        ),
        (
            "followup",
            "Schedule a follow-up reminder",
            "succeeded",
            (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        ),
    ]
    if mode == "google":
        plan[2] = ("notify_contact", f"Email incident summary to {recipient}", "awaiting_approval",
                   json.dumps({"kind": "notify_contact", "recipient": recipient}))
    plan[3] = ("followup", f"{'Create Google Calendar' if mode == 'google' else 'Record local'} follow-up series ({len(followups)} reminders): " + "; ".join(f"{item['title']} — {item['due_at']} (UTC offset included)" for item in followups),
               "awaiting_approval" if mode == "google" else "succeeded",
               json.dumps({"kind": "followup", "series": True}) if mode == "google" else "Local follow-up series recorded; no Google Calendar events created.")
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if payload.idempotency_key:
            previous = conn.execute(
                "SELECT * FROM incident_requests WHERE request_key=?",
                (payload.idempotency_key,),
            ).fetchone()
            if previous:
                previous_facts = conn.execute("SELECT facts FROM followup_facts WHERE incident_id=?", (previous["incident_id"],)).fetchone()
                if previous_facts and previous_facts[0] != facts:
                    raise HTTPException(409, "Idempotency key was already used with different follow-up facts.")
                if (
                    previous["summary"] != payload.summary
                    or previous["incident_type"] != payload.incident_type
                ):
                    raise HTTPException(
                        409, "Idempotency key was already used with different input."
                    )
                return incident_payload(conn, previous["incident_id"])
        flagged = conn.execute(
            "SELECT merchant, amount FROM transactions WHERE suspicious=1 ORDER BY occurred_at DESC LIMIT 1"
        ).fetchone()
        plan[0] = (
            (
                plan[0][0],
                plan[0][1],
                plan[0][2],
                f"Found a flagged synthetic transaction: {flagged['merchant']} for ₹{flagged['amount']:,}. Confirm with the user whether they recognize it.",
            )
            if flagged
            else (
                plan[0][0],
                plan[0][1],
                plan[0][2],
                "No transactions are currently flagged in the demo data.",
            )
        )
        conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?)",
            (incident_id, payload.summary, payload.incident_type, "in_progress", now),
        )
        if payload.idempotency_key:
            conn.execute(
                "INSERT INTO incident_requests VALUES (?, ?, ?, ?)",
                (
                    payload.idempotency_key,
                    payload.summary,
                    payload.incident_type,
                    incident_id,
                ),
            )
        conn.execute("INSERT INTO followup_facts VALUES (?,?)", (incident_id, facts))
        for item in followups:
            conn.execute("INSERT INTO followup_events VALUES (?,?,?,?,NULL)", (str(uuid4()), incident_id, json.dumps(item), "awaiting_approval" if mode == "google" else "scheduled_local"))
        for kind, title, status, result in plan:
            conn.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (str(uuid4()), incident_id, kind, title, status, result, now),
            )
        audit(conn, incident_id, "incident_created", payload.incident_type)
        audit(
            conn, incident_id, "context_retrieved", "user profile and demo transactions"
        )
    return get_incident(incident_id, user)


def incident_payload(conn, incident_id):
    incident = conn.execute(
        "SELECT * FROM incidents WHERE id=?", (incident_id,)
    ).fetchone()
    if not incident:
        raise HTTPException(404, "Incident not found.")
    actions = as_dicts(
        conn.execute(
            "SELECT * FROM actions WHERE incident_id=? ORDER BY created_at, rowid",
            (incident_id,),
        ).fetchall()
    )
    events = as_dicts(
        conn.execute(
            "SELECT action, detail, created_at FROM audit WHERE incident_id=? ORDER BY created_at",
            (incident_id,),
        ).fetchall()
    )
    from app.agent.plan import describe, assess
    assessment = assess(incident["summary"], as_dicts(conn.execute("SELECT * FROM transactions").fetchall()))
    dependencies = {step["id"]: step for step in describe(actions)}
    for action in actions:
        action["depends_on"] = dependencies[action["id"]]["depends_on"]
        action["reason"] = dependencies[action["id"]]["reason"]
    return {
        "sandbox": True,
        "incident": dict(incident),
        "plan": actions,
        "audit": events,
        "assessment": assessment,
        "followups": [{"id": row["id"], **json.loads(row["details"]), "status": row["status"], "result": row["result"]} for row in conn.execute("SELECT * FROM followup_events WHERE incident_id=? ORDER BY rowid", (incident_id,))],
    }


@user_scoped
def get_incident(incident_id, user):
    with db() as conn:
        return incident_payload(conn, incident_id)


@user_scoped
def generate_report(incident_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        data = incident_payload(conn, incident_id)
    incident = data["incident"]
    lines = [
        "# Guardian incident report",
        "",
        "**DEMO SANDBOX — not a bank or police report**",
        "",
        f"- Incident: `{incident['id']}`",
        f"- Type: {incident['incident_type']}",
        f"- Status: {incident['status']}",
        f"- Created: {incident['created_at']}",
        "",
        "## Incident summary",
        "",
        incident["summary"],
        "",
        "## Actions",
        "",
    ]
    for action in data["plan"]:
        lines.append(
            f"- **{action['title']}** — {action['status']}: {action['result'] or 'No result recorded.'}"
        )
    lines.extend(["", "## Follow-up schedule", ""])
    for item in data["followups"]:
        lines.append(f"- {item['title']} — {item['due_at']} ({item['status']}): {item['guidance']}")
        if item["source"]:
            lines.append(f"  Source: {item['source']}")
    return JSONResponse(
        {
            "sandbox": True,
            "filename": f"guardian-incident-{incident_id[:8]}.md",
            "content": "\n".join(lines),
        }
    )


@user_scoped
def approve_action(
    incident_id: str,
    action_id: str,
    payload: ApprovalInput,
    user=Depends(require_demo_auth),
):
    with db() as conn:
        from app.agent.plan import check_dependencies
        check_dependencies(conn, incident_id, action_id)
        external_action = conn.execute("SELECT result FROM actions WHERE id=? AND incident_id=?", (action_id, incident_id)).fetchone()
    if payload.approved and external_action and (external_action["result"] or "").startswith('{"kind":'):
        from app.services.external import execute
        execute(incident_id, action_id)
        return get_incident(incident_id, user)
    with db() as conn:
        action = conn.execute(
            "SELECT * FROM actions WHERE id=? AND incident_id=?",
            (action_id, incident_id),
        ).fetchone()
        if not action:
            raise HTTPException(404, "Pending action not found.")
        if action["status"] != "awaiting_approval":
            raise HTTPException(
                409, f"Action cannot be approved from status '{action['status']}'."
            )
        now = datetime.now(timezone.utc).isoformat()
        created = datetime.fromisoformat(action["created_at"])
        if datetime.now(timezone.utc) - created > timedelta(minutes=20):
            conn.execute("UPDATE actions SET status='expired' WHERE id=?", (action_id,))
            audit(conn, incident_id, "approval_expired", action["kind"])
            conn.commit()
            raise HTTPException(
                410, "This approval request expired. Start a new incident plan."
            )
        if not payload.approved:
            changed = conn.execute(
                "UPDATE actions SET status='declined', approved_at=? WHERE id=? AND status='awaiting_approval'",
                (now, action_id),
            ).rowcount
            if changed != 1:
                raise HTTPException(409, "This action was already handled.")
            audit(conn, incident_id, "approval_declined", action["kind"])
            if action["kind"] == "followup":
                conn.execute("UPDATE followup_events SET status='declined' WHERE incident_id=? AND status='awaiting_approval'", (incident_id,))
        else:
            if action["kind"] == "freeze_card":
                claimed = conn.execute("UPDATE actions SET status='running', approved_at=? WHERE id=? AND status='awaiting_approval'", (now, action_id)).rowcount
                if claimed != 1:
                    raise HTTPException(409, "This action was already handled.")
                audit(conn, incident_id, "approval_granted", "freeze_card")
                conn.commit()
                try:
                    bank.freeze(action_id)
                except HTTPException:
                    conn.execute("UPDATE actions SET status='failed', result=? WHERE id=?", ("Sandbox bank outcome unverified. Check bank state before retrying.", action_id))
                    conn.execute("UPDATE incidents SET status='action_incomplete' WHERE id=?", (incident_id,))
                    audit(conn, incident_id, "bank_freeze_failed", "sandbox bank outcome unverified")
                    conn.commit()
                    raise
                result = "Synthetic demo card frozen in Guardian sandbox. No real bank was contacted."
            elif action["kind"] == "notify_contact":
                result = (
                    "Notification recorded in local sandbox outbox; no email was sent."
                )
            else:
                raise HTTPException(400, "This action type is not executable.")
            changed = conn.execute(
                "UPDATE actions SET status='succeeded', result=?, approved_at=? WHERE id=? AND status IN ('awaiting_approval','running')",
                (result, now, action_id),
            ).rowcount
            if changed != 1:
                raise HTTPException(409, "This action was already handled.")
            if action["kind"] == "freeze_card":
                conn.execute("UPDATE demo_account SET card_frozen=1 WHERE id=1")
            audit(conn, incident_id, "approval_granted_and_executed", action["kind"])
        remaining = conn.execute(
            "SELECT COUNT(*) FROM actions WHERE incident_id=? AND status IN ('awaiting_approval','pending')",
            (incident_id,),
        ).fetchone()[0]
        if remaining == 0:
            unsuccessful = conn.execute(
                "SELECT COUNT(*) FROM actions WHERE incident_id=? AND status IN ('declined','expired','failed')",
                (incident_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE incidents SET status=? WHERE id=?",
                (
                    "action_incomplete" if unsuccessful else "resolved_in_sandbox",
                    incident_id,
                ),
            )
    return get_incident(incident_id, user)
