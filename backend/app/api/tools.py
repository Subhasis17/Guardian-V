"""Authenticated entry points for registered application tools."""

import hmac
import logging
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError
from app.tools import CONTRACTS, ToolResult, execute
from app.schemas import AgentToolInput
from app.security import require_demo_auth
from app.services import incidents
from app.database import db, audit, user_scoped

router = APIRouter()


@user_scoped
def record_failure(user, name, status):
    with db() as conn:
        audit(conn, None, "tool_failed", f"{name}:http_{status}")


@router.get("/api/tools")
def tool_contracts(user=Depends(require_demo_auth)):
    return {
        name: {
            "input_schema": model.model_json_schema(),
            "output_schema": ToolResult.model_json_schema(),
            "sandbox": True,
        }
        for name, model in CONTRACTS.items()
    }


@router.post("/api/tools/{name}", response_model=ToolResult)
def call_tool(name: str, arguments: dict, user=Depends(require_demo_auth)):
    try:
        return execute(name, arguments, user, incidents)
    except ValidationError:
        raise HTTPException(
            422,
            "Invalid tool arguments; use the registered schema and omit sensitive credentials.",
        ) from None


@router.post("/api/agent-tools/{name}")
def agent_tool(
    name: str, payload: AgentToolInput, authorization: str | None = Header(default=None)
):
    expected = os.getenv("GUARDIAN_AGENT_TOOL_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    from app.database import db
    with db() as conn:
        matched = next((row["id"] for row in conn.execute("SELECT id,tool_token FROM users") if hmac.compare_digest(supplied, row["tool_token"])), None)
    if not matched and (
        not expected
        or expected == os.getenv("DEMO_API_TOKEN", "")
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(401, "Valid tool authorization is required.")
    from app.tools import AGORA_TOOL_NAMES

    internal_name = next(
        (key for key, value in AGORA_TOOL_NAMES.items() if value == name), None
    )
    if internal_name is None:
        raise HTTPException(404, "Tool is not registered.")
    try:
        result = execute(internal_name, payload.arguments, matched or "demo-user", incidents)
    except ValidationError:
        record_failure(matched or "demo-user", internal_name, 422)
        raise HTTPException(422, "Invalid tool arguments.") from None
    except HTTPException as exc:
        record_failure(matched or "demo-user", internal_name, exc.status_code)
        raise
    logging.getLogger("uvicorn.error").info(
        "guardian_agent_tool id=%s tool=%s status=%s",
        payload.tool_call_id,
        name,
        result.status,
    )
    return result.model_dump()
