"""Application tool allowlist. Tools cannot grant approval."""

import json
import os
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentScope(EmptyInput):
    incident_id: str = Field(min_length=1, max_length=64)


class ActionScope(IncidentScope):
    action_id: str = Field(min_length=1, max_length=64)


class CreateInput(EmptyInput):
    summary: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ToolResult(BaseModel):
    sandbox: Literal[True] = True
    status: Literal["succeeded", "awaiting_approval", "failed"]
    data: dict


CONTRACTS = {
    "get_user_context": EmptyInput,
    "get_recent_transactions": EmptyInput,
    "get_incident_history": EmptyInput,
    "freeze_demo_card": ActionScope,
    "create_incident": CreateInput,
    "notify_trusted_contact": ActionScope,
    "schedule_followup": IncidentScope,
    "generate_report": IncidentScope,
}

AGORA_TOOL_NAMES = {
    "get_user_context": "getUserContext",
    "get_recent_transactions": "getRecentTransactions",
    "get_incident_history": "getIncidentHistory",
    "freeze_demo_card": "freezeDemoCard",
    "create_incident": "createIncident",
    "notify_trusted_contact": "notifyTrustedContact",
    "schedule_followup": "scheduleFollowup",
    "generate_report": "generateReport",
}


def agora_tool_definitions(public_url):
    descriptions = {
        "get_user_context": "Retrieve this demo user's trusted contact and sandbox account status.",
        "get_recent_transactions": "Review recent synthetic sandbox transactions.",
        "get_incident_history": "Retrieve prior and unresolved incidents for this demo user.",
        "freeze_demo_card": "Request the demo card freeze. This only creates an approval request; never claim frozen until approved.",
        "create_incident": "Create a persistent sandbox incident and response plan after clarifying the situation.",
        "notify_trusted_contact": "Request a sandbox trusted-contact notification. This only creates an approval request; no email is sent.",
        "schedule_followup": "Retrieve the persisted follow-up reminder for an incident.",
        "generate_report": "Generate a sandbox incident report; it is not a bank or police report.",
    }
    return [{
        "type": "function",
        "name": AGORA_TOOL_NAMES[name],
        "description": descriptions[name],
        "parameters": {**model.model_json_schema(), "additionalProperties": False},
        "execution": {"mode": "sync"},
        "server": {
            "method": "POST",
            "url": f"{public_url}/api/agent-tools/{AGORA_TOOL_NAMES[name]}",
            "headers": {"Authorization": f"Bearer {os.environ['DEMO_API_TOKEN']}"},
            "body": {"arguments": {field: "{{args." + field + "}}" for field in model.model_fields}, "tool_call_id": "{{tool_call_id}}"},
            "timeout_ms": 10000,
        },
    } for name, model in CONTRACTS.items()]


def execute(name, arguments, user, services):
    """User identity comes from authentication, never from model arguments."""
    if user != "demo-user":
        raise HTTPException(403, "Tool access is limited to the authenticated demo user.")
    if name not in CONTRACTS:
        raise HTTPException(404, "Tool is not registered.")
    args = CONTRACTS[name].model_validate(arguments)
    status = "succeeded"
    if name in {"get_user_context", "get_recent_transactions", "get_incident_history"}:
        context = services.context(user)
        key = {"get_user_context": "profile", "get_recent_transactions": "transactions", "get_incident_history": "incidents"}[name]
        data = {key: context[key]}
        if name == "get_user_context":
            data["account"] = context["account"]
    elif name == "create_incident":
        # Use the same sensitive-data validation as the dashboard.
        payload = services.IncidentInput(summary=args.summary, idempotency_key=args.idempotency_key)
        data = services.create_incident(payload, user)
    elif name == "generate_report":
        data = json.loads(services.generate_report(args.incident_id, user).body)
    else:
        incident = services.get_incident(args.incident_id, user)
        kind = {"freeze_demo_card": "freeze_card", "notify_trusted_contact": "notify_contact", "schedule_followup": "followup"}[name]
        action = next((a for a in incident["plan"] if a["kind"] == kind and (not isinstance(args, ActionScope) or a["id"] == args.action_id)), None)
        if action is None:
            raise HTTPException(404, "Matching incident action not found.")
        # Sensitive actions execute only through the authenticated approval endpoint.
        status = "succeeded" if action["status"] == "succeeded" else "awaiting_approval" if action["status"] == "awaiting_approval" else "failed"
        data = {"action": action}
        if status == "awaiting_approval":
            data["approval_url"] = f"/api/incidents/{args.incident_id}/actions/{args.action_id}/approval"
    with services.db() as conn:
        services.audit(conn, getattr(args, "incident_id", None), "tool_called", name + ":" + status)
    return ToolResult(status=status, data=data)
