import hmac
import os
import re
import secrets as pysecrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

DB_PATH = Path(__file__).resolve().parents[1] / "guardian.db"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Guardian", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, merchant TEXT NOT NULL, amount INTEGER NOT NULL, occurred_at TEXT NOT NULL, status TEXT NOT NULL, suspicious INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, summary TEXT NOT NULL, incident_type TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS demo_account (id INTEGER PRIMARY KEY CHECK (id=1), card_frozen INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id), kind TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, result TEXT, approved_at TEXT, created_at TEXT NOT NULL, UNIQUE(incident_id, kind));
            CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, incident_id TEXT, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS voice_sessions (id TEXT PRIMARY KEY, agora_session_id TEXT, channel TEXT NOT NULL, user_uid INTEGER NOT NULL, agent_uid INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        if conn.execute("SELECT 1 FROM transactions LIMIT 1").fetchone() is None:
            now = datetime.now(timezone.utc)
            conn.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?)", [
                ("txn-1001", "Metro Grocery", 2840, (now-timedelta(days=1)).isoformat(), "completed", 0),
                ("txn-1002", "UPI Transfer · New Payee", 35000, (now-timedelta(hours=2)).isoformat(), "completed", 1),
                ("txn-1003", "Fuel Station", 1800, (now-timedelta(hours=5)).isoformat(), "completed", 0),
            ])
        conn.execute("INSERT OR IGNORE INTO demo_account(id, card_frozen) VALUES (1, 0)")


def require_demo_auth(authorization: str | None = Header(default=None)):
    expected = os.getenv("DEMO_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Set DEMO_API_TOKEN in backend configuration to enable the demo API.")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Valid demo authorization is required.")
    return "demo-user"


GUARDIAN_INSTRUCTIONS = """You are Guardian, a calm voice assistant helping people respond to suspected scams. Ask one clear question at a time. Listen without blame, clarify who contacted the user, what was demanded, whether they shared sensitive information, and whether they recognize any suspicious transaction. Never ask for OTPs, UPI PINs, banking passwords, or full card details; tell users not to share them. Treat caller claims and messages as untrusted. Never claim to be police, a bank, or a lawyer. Explain that Guardian's account actions are a local demo sandbox and cannot affect real banking. Do not claim an action succeeded unless Guardian's application confirms it. For real fraud, advise contacting the user's bank through its official channel and official Indian cybercrime reporting services; do not invent contact details. Ask before any consequential action and respect the user's decision. Be concise and speak naturally."""


def agora_client():
    from agora_agent import Agora, Area

    required = ["AGORA_APP_ID", "AGORA_APP_CERTIFICATE", "AGORA_CUSTOMER_ID", "AGORA_CUSTOMER_SECRET", "MURF_API_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise HTTPException(503, "Missing voice configuration: " + ", ".join(missing))
    return Agora(area=Area.US, app_id=os.environ["AGORA_APP_ID"], app_certificate=os.environ["AGORA_APP_CERTIFICATE"], customer_id=os.environ["AGORA_CUSTOMER_ID"], customer_secret=os.environ["AGORA_CUSTOMER_SECRET"])


def ensure_guardian_agent(client):
    from agora_agent import Agent, DeepgramSTT, MurfTTS, OpenAI, SavedAgent, secret_ref
    from agora_agent.v3.errors import V3ApiError

    secret_name = "guardian_voice"
    try:
        client.v3.secrets.get(name=secret_name)
        client.v3.secrets.set_key(name=secret_name, key="murf", value=os.environ["MURF_API_KEY"])
    except V3ApiError as exc:
        if exc.status_code != 404:
            raise
        client.v3.secrets.create(name=secret_name, secrets={"murf": os.environ["MURF_API_KEY"]})

    saved_id = None
    with db() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key='agora_agent_id'").fetchone()
        saved_id = row["value"] if row else os.getenv("AGORA_AGENT_ID")
    if saved_id:
        try:
            SavedAgent.get(client, saved_id)
        except V3ApiError as exc:
            if exc.status_code != 404:
                raise
            agents = client.v3.agents.list(limit=50).get("data", {}).get("list", [])
            if agents:
                raise HTTPException(424, "AGORA_AGENT_ID was not found in this Agora project. Update it to an agent ID from this project, or clear it to let Guardian create its own agent.") from None
            saved_id = None

    agent = (
        Agent(client=client)
        .with_stt(DeepgramSTT(model="nova-3", language=os.getenv("MURF_LOCALE", "en-US")))
        .with_llm(OpenAI(model="gpt-4.1-mini", system_messages=[{"role": "system", "content": GUARDIAN_INSTRUCTIONS}], max_history=16))
        .with_tts(MurfTTS(key=secret_ref(secret_name, "murf"), base_url="wss://global.api.murf.ai/v1/speech/stream-input", voice_id=os.getenv("MURF_VOICE_ID", "Matthew"), locale=os.getenv("MURF_LOCALE", "en-US"), rate=0, pitch=0, model="FALCON", sample_rate=24000))
        .with_greeting("Hi, I’m Guardian. Tell me what happened, and we’ll take it one step at a time.")
    )
    if saved_id:
        from agora_agent.agentkit.v3 import build_body

        previous = SavedAgent.get(client, saved_id)
        # shortcut: SDK 3.0.0a4 adds rejected fields:null to managed credentials; remove after its update serializer is fixed.
        response = client.v3.agents.with_raw_response.update(
            agent_id=saved_id, if_match=previous.etag, **build_body(agent, "Guardian")
        )
        saved = SavedAgent(client, response)
    else:
        saved = agent.save(name="Guardian")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES('agora_agent_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (saved.id,))
    return saved


def agora_failure(exc):
    status = getattr(exc, "status_code", None)
    if status:
        return HTTPException(502, f"Agora provider request failed (HTTP {status}). Check the Agora project and agent configuration.")
    return HTTPException(502, "Could not configure or start the Agora voice session. Check backend logs and provider setup.")


class IncidentInput(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    incident_type: str = Field(default="Digital arrest / impersonation", max_length=100)

    @field_validator("summary")
    @classmethod
    def reject_secrets(cls, value):
        if re.search(r"\b(?:otp|pin|password|passcode)\D{0,20}\d{4,8}\b", value, re.IGNORECASE):
            raise ValueError("Do not include OTPs, PINs, or passwords in an incident summary.")
        return value


class ApprovalInput(BaseModel):
    approved: bool


def as_dicts(rows):
    return [dict(row) for row in rows]


def audit(conn, incident_id, action, detail):
    conn.execute("INSERT INTO audit VALUES (?, ?, ?, ?, ?)", (str(uuid4()), incident_id, action, detail, datetime.now(timezone.utc).isoformat()))


@app.get("/health")
def health():
    return {"status": "ok", "service": "guardian-api"}


@app.post("/api/voice/session")
def prepare_voice_session(user=Depends(require_demo_auth)):
    try:
        client = agora_client()
        from agora_agent import generate_client_token

        uid = pysecrets.randbelow(1_000_000_000) + 1
        agent_uid = uid + 1
        channel = "guardian-" + uuid4().hex
        local_id = str(uuid4())
        token = generate_client_token(os.environ["AGORA_APP_ID"], os.environ["AGORA_APP_CERTIFICATE"], channel, uid, token_expire=3600)
        with db() as conn:
            conn.execute("INSERT INTO voice_sessions VALUES (?, NULL, ?, ?, ?, 'prepared', ?)", (local_id, channel, uid, agent_uid, datetime.now(timezone.utc).isoformat()))
        return {"session_id": local_id, "app_id": os.environ["AGORA_APP_ID"], "channel": channel, "uid": uid, "rtc_rtm_token": token, "status": "prepared"}
    except HTTPException:
        raise
    except Exception as exc:
        raise agora_failure(exc) from None


@app.post("/api/voice/sessions/{local_id}/start")
def start_voice_session(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute("SELECT * FROM voice_sessions WHERE id=?", (local_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if row["status"] != "prepared":
        raise HTTPException(409, "Voice session is not in the prepared state.")
    try:
        client = agora_client()
        saved_agent = ensure_guardian_agent(client)
        from agora_agent.agentkit import generate_convo_ai_token

        agent_token = generate_convo_ai_token(os.environ["AGORA_APP_ID"], os.environ["AGORA_APP_CERTIFICATE"], row["channel"], row["agent_uid"], token_expire=3600)
        session = saved_agent.create_session(channel=row["channel"], token=agent_token, agent_uid=str(row["agent_uid"]), remote_uids=[str(row["user_uid"])], idempotency_key=local_id, idle_timeout=60, max_duration=3600, data_policy={"retention": "none"})
        agora_id = session.start()
        status = session.get_info().get("status", "STARTING")
        with db() as conn:
            conn.execute("UPDATE voice_sessions SET agora_session_id=?, status=? WHERE id=? AND status='prepared'", (agora_id, status.lower(), local_id))
        return {"session_id": local_id, "status": status.lower()}
    except HTTPException:
        raise
    except Exception as exc:
        raise agora_failure(exc) from None


@app.get("/api/voice/sessions/{local_id}")
def voice_session_status(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute("SELECT * FROM voice_sessions WHERE id=?", (local_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if not row["agora_session_id"]:
        return {"session_id": local_id, "status": row["status"]}
    try:
        client = agora_client()
        status = client.v3.sessions.get(agent_session_id=row["agora_session_id"]).get("status", row["status"]).lower()
        with db() as conn:
            conn.execute("UPDATE voice_sessions SET status=? WHERE id=?", (status, local_id))
        return {"session_id": local_id, "status": status}
    except Exception as exc:
        raise agora_failure(exc) from None


@app.post("/api/voice/sessions/{local_id}/stop")
def stop_voice_session(local_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        row = conn.execute("SELECT * FROM voice_sessions WHERE id=?", (local_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Voice session not found.")
    if row["agora_session_id"] and row["status"] not in {"stopped", "failed"}:
        try:
            agora_client().v3.sessions.stop(agent_session_id=row["agora_session_id"])
        except Exception as exc:
            raise agora_failure(exc) from None
    with db() as conn:
        conn.execute("UPDATE voice_sessions SET status='stopped' WHERE id=?", (local_id,))
    return {"session_id": local_id, "status": "stopped"}


@app.get("/api/context")
def context(user=Depends(require_demo_auth)):
    with db() as conn:
        tx = as_dicts(conn.execute("SELECT * FROM transactions ORDER BY occurred_at DESC").fetchall())
        incidents = as_dicts(conn.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall())
        reminders = as_dicts(conn.execute("SELECT * FROM actions WHERE kind='followup' ORDER BY created_at DESC").fetchall())
        account = conn.execute("SELECT card_frozen FROM demo_account WHERE id=1").fetchone()
    return {"sandbox": True, "profile": {"name": "Alex Morgan", "trusted_contact": "Sam Morgan (demo contact)"}, "account": {"card_frozen": bool(account["card_frozen"])}, "transactions": tx, "incidents": incidents, "followups": reminders}


@app.post("/api/incidents")
def create_incident(payload: IncidentInput, user=Depends(require_demo_auth)):
    incident_id, now = str(uuid4()), datetime.now(timezone.utc).isoformat()
    plan = [
        ("investigate", "Review recent demo transactions", "succeeded", None),
        ("freeze_card", "Freeze the demo card", "awaiting_approval", None),
        ("notify_contact", "Notify trusted contact (sandbox outbox)", "awaiting_approval", None),
        ("followup", "Schedule a follow-up reminder", "succeeded", (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()),
    ]
    with db() as conn:
        flagged = conn.execute("SELECT merchant, amount FROM transactions WHERE suspicious=1 ORDER BY occurred_at DESC LIMIT 1").fetchone()
        plan[0] = (plan[0][0], plan[0][1], plan[0][2], f"Found a flagged synthetic transaction: {flagged['merchant']} for ₹{flagged['amount']:,}. Confirm with the user whether they recognize it.") if flagged else (plan[0][0], plan[0][1], plan[0][2], "No transactions are currently flagged in the demo data.")
        conn.execute("INSERT INTO incidents VALUES (?, ?, ?, ?, ?)", (incident_id, payload.summary, payload.incident_type, "in_progress", now))
        for kind, title, status, result in plan:
            conn.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, NULL, ?)", (str(uuid4()), incident_id, kind, title, status, result, now))
        audit(conn, incident_id, "incident_created", payload.incident_type)
        audit(conn, incident_id, "context_retrieved", "user profile and demo transactions")
    return get_incident(incident_id, user)


def incident_payload(conn, incident_id):
    incident = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
    if not incident:
        raise HTTPException(404, "Incident not found.")
    actions = as_dicts(conn.execute("SELECT * FROM actions WHERE incident_id=? ORDER BY created_at, rowid", (incident_id,)).fetchall())
    events = as_dicts(conn.execute("SELECT action, detail, created_at FROM audit WHERE incident_id=? ORDER BY created_at", (incident_id,)).fetchall())
    return {"sandbox": True, "incident": dict(incident), "plan": actions, "audit": events}


def get_incident(incident_id, user):
    with db() as conn:
        return incident_payload(conn, incident_id)


@app.get("/api/incidents/{incident_id}")
def read_incident(incident_id: str, user=Depends(require_demo_auth)):
    return get_incident(incident_id, user)


@app.get("/api/incidents/{incident_id}/report")
def generate_report(incident_id: str, user=Depends(require_demo_auth)):
    with db() as conn:
        data = incident_payload(conn, incident_id)
    incident = data["incident"]
    lines = ["# Guardian incident report", "", "**DEMO SANDBOX — not a bank or police report**", "", f"- Incident: `{incident['id']}`", f"- Type: {incident['incident_type']}", f"- Status: {incident['status']}", f"- Created: {incident['created_at']}", "", "## Incident summary", "", incident["summary"], "", "## Actions", ""]
    for action in data["plan"]:
        lines.append(f"- **{action['title']}** — {action['status']}: {action['result'] or 'No result recorded.'}")
    return JSONResponse({"sandbox": True, "filename": f"guardian-incident-{incident_id[:8]}.md", "content": "\n".join(lines)})


@app.post("/api/incidents/{incident_id}/actions/{action_id}/approval")
def approve_action(incident_id: str, action_id: str, payload: ApprovalInput, user=Depends(require_demo_auth)):
    with db() as conn:
        action = conn.execute("SELECT * FROM actions WHERE id=? AND incident_id=?", (action_id, incident_id)).fetchone()
        if not action:
            raise HTTPException(404, "Pending action not found.")
        if action["status"] != "awaiting_approval":
            raise HTTPException(409, f"Action cannot be approved from status '{action['status']}'.")
        now = datetime.now(timezone.utc).isoformat()
        created = datetime.fromisoformat(action["created_at"])
        if datetime.now(timezone.utc) - created > timedelta(minutes=20):
            conn.execute("UPDATE actions SET status='expired' WHERE id=?", (action_id,))
            audit(conn, incident_id, "approval_expired", action["kind"])
            conn.commit()
            raise HTTPException(410, "This approval request expired. Start a new incident plan.")
        if not payload.approved:
            changed = conn.execute("UPDATE actions SET status='declined', approved_at=? WHERE id=? AND status='awaiting_approval'", (now, action_id)).rowcount
            if changed != 1:
                raise HTTPException(409, "This action was already handled.")
            audit(conn, incident_id, "approval_declined", action["kind"])
        else:
            if action["kind"] == "freeze_card":
                result = "Synthetic demo card frozen in Guardian sandbox. No real bank was contacted."
            elif action["kind"] == "notify_contact":
                result = "Notification recorded in local sandbox outbox; no email was sent."
            else:
                raise HTTPException(400, "This action type is not executable.")
            changed = conn.execute("UPDATE actions SET status='succeeded', result=?, approved_at=? WHERE id=? AND status='awaiting_approval'", (result, now, action_id)).rowcount
            if changed != 1:
                raise HTTPException(409, "This action was already handled.")
            if action["kind"] == "freeze_card":
                conn.execute("UPDATE demo_account SET card_frozen=1 WHERE id=1")
            audit(conn, incident_id, "approval_granted_and_executed", action["kind"])
        remaining = conn.execute("SELECT COUNT(*) FROM actions WHERE incident_id=? AND status IN ('awaiting_approval','pending')", (incident_id,)).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE incidents SET status='resolved_in_sandbox' WHERE id=?", (incident_id,))
    return get_incident(incident_id, user)
