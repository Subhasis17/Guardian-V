# Guardian

Guardian is a voice-first scam response and recovery assistant. The current local demo provides authenticated synthetic account context, suspicious transaction review, persistent incident planning, explicit approvals for demo-card freeze and trusted-contact notification, a local notification outbox record, and a persisted follow-up reminder. Banking, contact, and reminder actions are sandbox-only.

## Requirements

- Python 3.10 or later
- Node.js 20 or later
- Agora and Murf developer credentials are needed for live voice. The local incident workflow works without them.

## Run locally

Copy `.env.example` to `.env`, set `DEMO_API_TOKEN` to a private random value, and keep `.env` uncommitted. Then run the backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --env-file ..\.env
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL (usually `http://127.0.0.1:5173`) and enter the same `DEMO_API_TOKEN`. The API health check is `http://127.0.0.1:8000/health`. SQLite creates `backend/guardian.db` and seeds synthetic transactions on first start.

To run backend workflow tests: `pip install -r requirements-dev.txt` from `backend`, then `pytest`.

## Demo behavior and boundaries

Create an incident from the scenario prompt, inspect the flagged synthetic ₹35,000 transaction, and approve or decline each sensitive action individually. Card freeze updates only local demo state. The trusted-contact action writes an outcome to the local incident plan; it does not send email. Follow-up is a stored reminder, not a calendar event. Do not enter OTPs, PINs, passwords, or real banking details.

## Live voice configuration

The browser connects through Agora RTC and RTM, and the backend prepares and starts Conversational AI sessions configured for Murf Falcon. The user verified a live spoken conversation on 2026-11-20. The saved-agent update uses an ETag-guarded raw update because SDK 3.0.0a4 adds a rejected `fields: null` to managed credentials. Real email and Google Calendar remain unconnected. Never expose provider credentials in the frontend.

Agora agent, ASR, and Falcon settings are isolated in `backend/app/voice_config.py`. The UI reads the non-secret profile list from authenticated `GET /api/voice/config`, then sends a `profile_id` when preparing a session. Each profile creates or updates its own saved Agora agent, and the chosen profile is persisted with the local voice session.

The built-in profiles are `default` and `auto`. `default` uses `GUARDIAN_ASR_LANGUAGE`, `MURF_LOCALE`, and `MURF_VOICE_ID`. `auto` sends `language=multi` to Deepgram Nova-3, which enables multilingual input detection, but it deliberately keeps the default Murf reply language and voice. Murf voice and locale are fixed when this Agora session starts, so matching spoken output requires the user to choose a configured language profile before starting the call.

The shipped default is Hindi: Deepgram ASR `hi`, Murf locale `hi-IN`, Murf Falcon voice `hi-IN-rachna` (Rachna), Hindi replies, and a Hindi greeting. Rachna is the sheet-recommended female voice for Hindi. Override these server-side environment values when a different default is required.

Add profiles with `GUARDIAN_VOICE_PROFILES_JSON`; see `.env.example` for the schema. For every profile, use a Murf Falcon voice that supports the configured `tts_locale`. Invalid JSON, duplicate IDs, or an unknown default profile fail closed. Restart the backend after changing `.env`. Provider credentials and Murf voice IDs are not returned to the browser.

See [AGENTS.md](AGENTS.md) for the engineering and safety contract.

## Application tools

## Voice diagnostics

After starting a conversation, expand **Voice session diagnostics**. It shows the local session ID, provider status, and timestamped milestones for RTC join/disconnect, microphone publishing, RTM connection, received messages/transcripts, remote audio playback requests, and failures. Status refreshes every 10 seconds; missing events are not proof of failure. A playback request does not prove audible speech. Client events are self reported and do not authorize actions or verify tool execution.

Authenticated `GET /api/voice/sessions/{id}/diagnostics` returns the timeline. Only allowlisted event names can be recorded, with no free text, transcript, audio, or credential fields. SQLite retains at most 1,000 events per session and prunes diagnostic events older than seven days on backend startup. Uvicorn logs contain session/event names and provider error type/HTTP status, never provider response bodies. Session records are retained separately. Browser SDK console logs are provider controlled and should not be shared without reviewing them for sensitive data.

## Tool API

Authenticated `GET /api/tools` lists input/output schemas for the eight required tool names. `POST /api/tools/{name}` accepts the tool input object. Unknown names return 404, invalid arguments 422, and conflicting idempotency keys 409. Successful calls return `sandbox`, `status`, and structured `data`; calls are audited without recording input contents. The single demo identity scopes access to the one sandbox; multi-user isolation is not implemented.

`create_incident` requires an `idempotency_key` and reuses the same persistent incident on retries. Freeze and notification tools require the incident and action IDs and return an approval URL while pending. They cannot grant approval: use the dashboard approval controls. `schedule_followup` retrieves the reminder already persisted with the incident, so repeated calls create no duplicates. Notifications remain local records. Set `VERCEL_AI_GATEWAY_API_KEY` and `GUARDIAN_PUBLIC_API_URL` to enable Agora tool calling; the public URL must be HTTPS and point to this backend. The gateway key is stored in Agora's project secret set and is never sent to the browser.

Each incident can produce a downloadable Markdown summary labeled as a sandbox report; it is not a bank or police report.

## Render deployment

The root `render.yaml` creates a free Python API and a static dashboard. In Render, create a Blueprint from this repository and select the `master` branch. Enter the backend secrets requested by the Blueprint using the values in your local `.env`; never upload that file or put secrets in frontend variables. `AGORA_AGENT_ID` and `GUARDIAN_VOICE_PROFILES_JSON` are optional backend overrides; saved agents are created automatically by default.

After Render assigns the URLs, set backend `GUARDIAN_PUBLIC_API_URL` to the API HTTPS base URL and `GUARDIAN_FRONTEND_ORIGINS` to the dashboard HTTPS origin (no trailing slash). Set frontend `VITE_API_URL` to the API base URL and rebuild the static site. Use the actual assigned URLs, which may differ from the service names. Environment variables are loaded directly by Render; no `.env` file is needed there.

Verify `/health`, dashboard authentication, and a fresh voice conversation with tool activity after both services are live. Use the same `DEMO_API_TOKEN` in the dashboard login. This is a shared-token sandbox demo, not production multi-user authentication. Notifications and reminders remain local records.

Free web services can sleep and have ephemeral filesystems: SQLite incidents, approvals, diagnostics, and saved agent references can be lost on restart/redeploy. Keep this deployment for synthetic demo data. Durable storage requires a persistent disk on a suitable paid service or a database migration. See [Render Blueprints](https://render.com/docs/blueprint-spec).
