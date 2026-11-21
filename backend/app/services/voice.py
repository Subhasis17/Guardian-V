"""Agora lifecycle and persisted voice diagnostics."""

import logging
import os
import secrets as pysecrets
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import Depends, HTTPException
from app.database import db, as_dicts, user_scoped, current_user
from app.schemas import VoiceEvent, VoiceSessionInput
from app.security import require_demo_auth
from app.voice_config import (
    VoiceProfile,
    build_guardian_agent,
    get_voice_profile,
    load_voice_profiles,
)


def agora_client():
    from agora_agent import Agora, Area

    required = [
        "AGORA_APP_ID",
        "AGORA_APP_CERTIFICATE",
        "AGORA_CUSTOMER_ID",
        "AGORA_CUSTOMER_SECRET",
        "MURF_API_KEY",
    ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise HTTPException(503, "Missing voice configuration: " + ", ".join(missing))
    return Agora(
        area=Area.US,
        app_id=os.environ["AGORA_APP_ID"],
        app_certificate=os.environ["AGORA_APP_CERTIFICATE"],
        customer_id=os.environ["AGORA_CUSTOMER_ID"],
        customer_secret=os.environ["AGORA_CUSTOMER_SECRET"],
    )


def ensure_guardian_agent(client, profile: VoiceProfile):
    from agora_agent import SavedAgent
    from agora_agent.v3.errors import V3ApiError

    secret_name = "guardian_voice"
    if current_user.get() == "demo-user" and os.getenv("GUARDIAN_PUBLIC_API_URL") and (
        not os.getenv("GUARDIAN_AGENT_TOOL_TOKEN")
        or os.getenv("GUARDIAN_AGENT_TOOL_TOKEN") == os.getenv("DEMO_API_TOKEN")
    ):
        raise HTTPException(
            503,
            "Set a distinct GUARDIAN_AGENT_TOOL_TOKEN before enabling Agora tool calls.",
        )
    try:
        client.v3.secrets.get(name=secret_name)
        client.v3.secrets.set_key(
            name=secret_name, key="murf", value=os.environ["MURF_API_KEY"]
        )
    except V3ApiError as exc:
        if exc.status_code != 404:
            raise

    setting_key = f"agora_agent_id:{profile.id}"
    saved_id = None
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (setting_key,)
        ).fetchone()
        legacy = (
            conn.execute(
                "SELECT value FROM app_settings WHERE key='agora_agent_id'"
            ).fetchone()
            if profile.id == "default"
            else None
        )
        saved_id = (
            row["value"]
            if row
            else (
                legacy["value"]
                if legacy
                else os.getenv("AGORA_AGENT_ID") if profile.id == "default" and current_user.get() == "demo-user" else None
            )
        )
    if saved_id:
        try:
            SavedAgent.get(client, saved_id)
        except V3ApiError as exc:
            if exc.status_code != 404:
                raise
            agents = client.v3.agents.list(limit=50).get("data", {}).get("list", [])
            if agents:
                raise HTTPException(
                    424,
                    "AGORA_AGENT_ID was not found in this Agora project. Update it to an agent ID from this project, or clear it to let Guardian create its own agent.",
                ) from None
            saved_id = None

    agent = build_guardian_agent(client, profile, secret_name)
    if saved_id:
        from agora_agent.agentkit.v3 import build_body

        previous = SavedAgent.get(client, saved_id)
        # shortcut: SDK 3.0.0a4 adds rejected fields:null to managed credentials; remove after its update serializer is fixed.
        response = client.v3.agents.with_raw_response.update(
            agent_id=saved_id, if_match=previous.etag, **build_body(agent, "Guardian")
        )
        saved = SavedAgent(client, response)
    else:
        saved = agent.save(name=f"Guardian - {profile.id}")
    with db() as conn:
        conn.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (setting_key, saved.id),
        )
    return saved


def agora_failure(exc):
    status = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if detail:
        from app.database import tool_token
        credential = tool_token()
        if credential:
            detail = detail.replace(credential, "[redacted]")
        for name in (
            "DEMO_API_TOKEN",
            "GUARDIAN_AGENT_TOOL_TOKEN",
            "AGORA_APP_CERTIFICATE",
            "AGORA_CUSTOMER_SECRET",
            "MURF_API_KEY",
        ):
            secret = os.getenv(name)
            if secret:
                detail = detail.replace(secret, "[redacted]")
    logging.getLogger("uvicorn.error").warning(
        "guardian_provider_failure type=%s http_status=%s reason=%s request_id=%s detail=%s",
        type(exc).__name__,
        status,
        getattr(exc, "reason", None),
        getattr(exc, "request_id", None),
        detail[:500] if detail else None,
    )
    if status:
        return HTTPException(
            502,
            f"Agora provider request failed (HTTP {status}). Check the Agora project and agent configuration.",
        )
    return HTTPException(
        502,
        "Could not configure or start the Agora voice session. Check backend logs and provider setup.",
    )


def record_voice_event(local_id, event):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM voice_sessions WHERE id=?", (local_id,)
        ).fetchone():
            raise HTTPException(404, "Voice session not found.")
        if (
            conn.execute(
                "SELECT COUNT(*) FROM voice_events WHERE session_id=?", (local_id,)
            ).fetchone()[0]
            >= 1000
        ):
            raise HTTPException(429, "Session diagnostic event limit reached.")
        conn.execute(
            "INSERT INTO voice_events(session_id,event,created_at) VALUES (?,?,?)",
            (local_id, event, datetime.now(timezone.utc).isoformat()),
        )
    logging.getLogger("uvicorn.error").info(
        "guardian_voice session=%s event=%s", local_id, event
    )


@user_scoped
def voice_event(local_id: str, payload: VoiceEvent, user=Depends(require_demo_auth)):
    record_voice_event(local_id, payload.event)
    return {"recorded": True}


@user_scoped
def voice_diagnostics(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        session = conn.execute(
            "SELECT id,status,created_at FROM voice_sessions WHERE id=?", (local_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Voice session not found.")
        events = as_dicts(
            conn.execute(
                "SELECT event,created_at FROM voice_events WHERE session_id=? ORDER BY id",
                (local_id,),
            ).fetchall()
        )
    return {
        "session": dict(session),
        "events": events,
        "client_events_are_self_reported": True,
    }


def voice_config(user=Depends(require_demo_auth)):
    try:
        profiles, selected = load_voice_profiles()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    return {
        "default_profile_id": selected,
        "profiles": [profile.public_dict() for profile in profiles.values()],
    }


@user_scoped
def prepare_voice_session(payload: VoiceSessionInput, user=Depends(require_demo_auth)):
    try:
        profile = get_voice_profile(payload.profile_id)
        client = agora_client()
        from agora_agent import generate_client_token

        uid = pysecrets.randbelow(1_000_000_000) + 1
        agent_uid = uid + 1
        channel = "guardian-" + uuid4().hex
        local_id = str(uuid4())
        token = generate_client_token(
            os.environ["AGORA_APP_ID"],
            os.environ["AGORA_APP_CERTIFICATE"],
            channel,
            uid,
            token_expire=3600,
        )
        with db() as conn:
            conn.execute(
                "INSERT INTO voice_sessions(id,agora_session_id,channel,user_uid,agent_uid,status,created_at,profile_id) VALUES (?,NULL,?,?,?,'prepared',?,?)",
                (
                    local_id,
                    channel,
                    uid,
                    agent_uid,
                    datetime.now(timezone.utc).isoformat(),
                    profile.id,
                ),
            )
        record_voice_event(local_id, "prepared")
        return {
            "session_id": local_id,
            "app_id": os.environ["AGORA_APP_ID"],
            "channel": channel,
            "uid": uid,
            "rtc_rtm_token": token,
            "status": "prepared",
            "profile_id": profile.id,
            "profile_label": profile.label,
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except HTTPException:
        raise
    except Exception as exc:
        raise agora_failure(exc) from None


@user_scoped
def start_voice_session(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM voice_sessions WHERE id=?", (local_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if row["status"] != "prepared":
        raise HTTPException(409, "Voice session is not in the prepared state.")
    stage = "agora_client"
    try:
        client = agora_client()
        stage = "voice_profile"
        profile = get_voice_profile(row["profile_id"])
        stage = "agent_configuration"
        logging.getLogger("guardian").info("llm_session_configuration session=%s provider=agora_managed model=gpt-4o-mini per_turn_visibility=unavailable", local_id)
        saved_agent = ensure_guardian_agent(client, profile)
        from agora_agent.agentkit import generate_convo_ai_token

        stage = "session_start"
        agent_token = generate_convo_ai_token(
            os.environ["AGORA_APP_ID"],
            os.environ["AGORA_APP_CERTIFICATE"],
            row["channel"],
            row["agent_uid"],
            token_expire=3600,
        )
        session = saved_agent.create_session(
            channel=row["channel"],
            token=agent_token,
            agent_uid=str(row["agent_uid"]),
            remote_uids=[str(row["user_uid"])],
            idempotency_key=local_id,
            idle_timeout=60,
            max_duration=3600,
            data_policy={"retention": "none"},
        )
        agora_id = session.start()
        logging.getLogger("guardian").info("llm_session_started session=%s provider=agora_managed", local_id)
        try:
            with db() as conn:
                changed = conn.execute(
                    "UPDATE voice_sessions SET agora_session_id=?, status=? WHERE id=? AND status='prepared'",
                    (agora_id, "starting", local_id),
                ).rowcount
            if not changed:
                raise RuntimeError("Voice session was no longer prepared")
        except Exception:
            client.v3.sessions.stop(agent_session_id=agora_id)
            raise
        status = session.get_info().get("status", "STARTING")
        with db() as conn:
            conn.execute(
                "UPDATE voice_sessions SET status=? WHERE id=? AND status='starting'",
                (status.lower(), local_id),
            )
        record_voice_event(local_id, "agent_started")
        return {"session_id": local_id, "status": status.lower()}
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger("uvicorn.error").warning(
            "guardian_voice_start_failed session=%s stage=%s", local_id, stage
        )
        raise agora_failure(exc) from None


@user_scoped
def voice_session_status(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM voice_sessions WHERE id=?", (local_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if not row["agora_session_id"]:
        return {"session_id": local_id, "status": row["status"]}
    try:
        client = agora_client()
        status = (
            client.v3.sessions.get(agent_session_id=row["agora_session_id"])
            .get("status", row["status"])
            .lower()
        )
        with db() as conn:
            conn.execute(
                "UPDATE voice_sessions SET status=? WHERE id=? AND status NOT IN ('stopped', 'failed')",
                (status, local_id),
            )
            status = conn.execute(
                "SELECT status FROM voice_sessions WHERE id=?", (local_id,)
            ).fetchone()[0]
        return {"session_id": local_id, "status": status}
    except Exception as exc:
        raise agora_failure(exc) from None


@user_scoped
def stop_voice_session(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM voice_sessions WHERE id=?", (local_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if row["agora_session_id"] and row["status"] not in {"stopped", "failed"}:
        try:
            agora_client().v3.sessions.stop(agent_session_id=row["agora_session_id"])
        except Exception as exc:
            raise agora_failure(exc) from None
    with db() as conn:
        conn.execute(
            "UPDATE voice_sessions SET status='stopped' WHERE id=?", (local_id,)
        )
    record_voice_event(local_id, "stopped")
    return {"session_id": local_id, "status": "stopped"}
