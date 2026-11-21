# Guardian

Hackathon materials: [submission details](docs/hackathon-submission.md) and
[PowerPoint presentation](docs/submission/Guardian-Hackathon.pptx).

Voice defaults to English (Murf Natalie). The dropdown has six English choices
(US, UK and Indian male/female voices), all native voices for the available
Indian languages, and one male/female choice per other language wherever the
catalog supports both. Current Indian languages: Bangla, Gujarati, Hindi,
Kannada, Malayalam, Marathi, Punjabi and Tamil. Greek, Croatian, Polish, Slovak
and Thai have only one listed gender in the saved catalog. Auto-detect and
explicit custom profiles remain available. Saved sessions can still resolve
profiles that are hidden from the picker. The catalog was retrieved on
2026-11-21; output support does not guarantee ASR coverage. Live voice
verification remains necessary.

Local sandbox bank: start `mock-bank/main.py` on port 8001 before Guardian.
See [mock bank setup](mock-bank/README.md) for commands and configuration.
Banking tools now use this separate service with per-user synthetic histories.

Multi-user update: use **Create an account** on the login screen to register a
username (3–100 letters/numbers or `_.@+-`) and a password of at least 12
characters. Signup then signs in automatically. Accounts have independent
SQLite sandbox files beside `GUARDIAN_DB_PATH`, including incidents, approvals,
card state, audit history and voice sessions. Back up the whole containing
directory. Existing operator data stays with the operator account; new users
cannot claim it. Agora creates account-specific agents/tool credentials.
Each user connects Google and saves a trusted contact in the dashboard. Until connected, email/calendar actions remain in the sandbox; operator credentials are never shared.
Password recovery and email verification are not yet available. Registration
uses usernames, so entering an email address does not verify ownership of it.
The single-operator-only statements below are superseded by this update.

Authentication update: the dashboard now uses password login and server-side
sessions. `DEMO_API_TOKEN` no longer grants dashboard access. Provision the
single sandbox operator from `backend` with `python -m app.manage`; it prompts
for a username and password without saving the password in `.env`. Set
`GUARDIAN_COOKIE_SECURE=true` on Render. Re-running the command resets the
account and revokes every session. Sessions expire after 30 idle minutes or
eight hours; logout revokes the current session. Passwords use salted scrypt;
only session token hashes are stored. CSRF tokens stay in application memory.
The backend-only `GUARDIAN_AGENT_TOOL_TOKEN` remains a service credential for
Agora callbacks and cannot sign in or approve an action. Public registration and account-specific storage are available. Google connections are per user.
Cross-site Render cookies use Secure/SameSite=None; browsers blocking third-party
cookies require a same-site custom domain or reverse proxy. Use the same host
(`localhost` or `127.0.0.1`) for frontend and API during local development.
The older demo-token instructions below are superseded by this section.

Latest integration implementation: see [Google setup and live acceptance](docs/integrations.md).
`GUARDIAN_INTEGRATION_MODE=google` enables approval-gated Gmail notification
and Google Calendar follow-up adapters; the default remains `sandbox`.
Google integrations are covered by mocked tests and still require credentials
and live acceptance. Older sandbox descriptions below apply to the default mode.

Guardian is a voice-first scam response and recovery assistant. The current local demo provides authenticated synthetic account context, suspicious transaction review, persistent incident planning, explicit approvals for demo-card freeze and trusted-contact notification, a local notification outbox record, and a persisted follow-up reminder. Banking, contact, and reminder actions are sandbox-only.

## Source layout

The backend entry point is `backend/app/main.py`. It registers HTTP routers from
`app/api/`; application workflows live in `app/services/`. SQLite connections,
schema setup, and audit persistence live in `app/database.py`. Request validation
lives in `app/schemas.py`, and demo authentication lives in `app/security.py`.
The tool registry remains in `app/tools.py`, with voice profiles and provider
configuration in `app/voice_config.py`.

The frontend starts in `frontend/src/main.tsx` and renders `App.tsx`.
Voice connection state, lifecycle, and diagnostics live in `hooks/useVoice.ts`.
The approval feed lives in `components/PendingApprovals.tsx`, shared API data
types live in `types.ts`, and presentation rules live in `style.css`.

## Runtime requirements

- Python 3.10 or later
- Node.js 20 or later
- Agora and Murf developer credentials are needed for live voice. The local incident workflow works without them.

## Run locally

Copy `.env.example` to `.env`, set `MOCK_BANK_SERVICE_SECRET` to a long random value, and keep `.env` uncommitted. Start the separate bank using `mock-bank/README.md`, then run the backend:

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

Open `http://127.0.0.1:5173`, choose Create an account, then sign in with your username and password. Use the same hostname for the API and frontend. The API health check is `http://127.0.0.1:8000/health`. SQLite creates `backend/guardian.db` and seeds synthetic transactions on first start.

To run backend workflow tests: `pip install -r requirements-dev.txt` from `backend`, then `pytest`.

## Demo behavior and boundaries

Create an incident from the scenario prompt, inspect the flagged synthetic ₹35,000 transaction, and approve or decline each sensitive action individually. Card freeze updates only local demo state. The trusted-contact action writes an outcome to the local incident plan; it does not send email. Follow-up is a stored reminder, not a calendar event. Do not enter OTPs, PINs, passwords, or real banking details.

See the [demo runbook](docs/demo-runbook.md) for a step-by-step voice-to-approval workflow and its verification limits.

## Live voice configuration

The browser connects through Agora RTC and RTM, and the backend prepares and starts Conversational AI sessions configured for Murf Falcon. The user verified a live spoken conversation on 2026-11-20. The saved-agent update uses an ETag-guarded raw update because SDK 3.0.0a4 adds a rejected `fields: null` to managed credentials. Real email and Google Calendar remain unconnected. Never expose provider credentials in the frontend.

Agora agent, ASR, and Falcon settings are isolated in `backend/app/voice_config.py`. The UI reads the non-secret profile list from authenticated `GET /api/voice/config`, then sends a `profile_id` when preparing a session. Each profile creates or updates its own saved Agora agent, and the chosen profile is persisted with the local voice session.

The built-in profiles are `default` and `auto`. `default` uses `GUARDIAN_ASR_LANGUAGE`, `MURF_LOCALE`, and `MURF_VOICE_ID`. `auto` sends `language=multi` to Deepgram Nova-3, which enables multilingual input detection, but it deliberately keeps the default Murf reply language and voice. Murf voice and locale are fixed when this Agora session starts, so matching spoken output requires the user to choose a configured language profile before starting the call.

The shipped default is Hindi: Deepgram ASR `hi`, Murf locale `hi-IN`, Murf Falcon voice `hi-IN-rachna` (Rachna), Hindi replies, and a Hindi greeting. Rachna is the sheet-recommended female voice for Hindi. Override these server-side environment values when a different default is required.

Add profiles with `GUARDIAN_VOICE_PROFILES_JSON`; see `.env.example` for the schema. For every profile, use a Murf Falcon voice that supports the configured `tts_locale`. Invalid JSON, duplicate IDs, or an unknown default profile fail closed. Restart the backend after changing `.env`. Provider credentials and Murf voice IDs are not returned to the browser.

See [AGENTS.md](AGENTS.md) for the engineering and safety contract.

## Application tools

## Voice diagnostics

Detailed technical events remain available through the authenticated diagnostics API. The dashboard focuses on conversation and action results.

After starting a conversation, expand **Voice session diagnostics**. It shows the local session ID, provider status, and timestamped milestones for RTC join/disconnect, microphone publishing, RTM connection, received messages/transcripts, remote audio playback requests, and failures. Status refreshes every 10 seconds; missing events are not proof of failure. A playback request does not prove audible speech. Client events are self reported and do not authorize actions or verify tool execution.

Authenticated `GET /api/voice/sessions/{id}/diagnostics` returns the timeline. Only allowlisted event names can be recorded, with no free text, transcript, audio, or credential fields. SQLite retains at most 1,000 events per session and prunes diagnostic events older than seven days on backend startup. Uvicorn logs contain session/event names and provider error type/HTTP status, never provider response bodies. Session records are retained separately. Browser SDK console logs are provider controlled and should not be shared without reviewing them for sensitive data.

## Tool API

Authenticated `GET /api/tools` lists input/output schemas for the eight required tool names. `POST /api/tools/{name}` accepts the tool input object. Unknown names return 404, invalid arguments 422, and conflicting idempotency keys 409. Successful calls return `sandbox`, `status`, and structured `data`; calls are audited without recording input contents. The single demo identity scopes access to the one sandbox; multi-user isolation is not implemented.

`create_incident` requires an `idempotency_key` and reuses the same persistent incident on retries. Freeze and notification tools require the incident and action IDs and return an approval URL while pending. They cannot grant approval: use the dashboard approval controls. `schedule_followup` retrieves the reminder already persisted with the incident, so repeated calls create no duplicates. Notifications remain local records. The LLM uses Agora-managed OpenAI `gpt-4o-mini`, so no separate LLM key is needed. Set `GUARDIAN_PUBLIC_API_URL` to enable Agora tool calling; the public URL must be HTTPS and point to this backend. Murf Falcon continues to use its server-side key.

Set `GUARDIAN_AGENT_TOOL_TOKEN` to a long random server-only secret for operator voice tools. Registered accounts receive separate tool credentials automatically. Start a new voice session after configuration changes.

Each incident can produce a downloadable Markdown summary labeled as a sandbox report; it is not a bank or police report.

## Render deployment

Completed incidents and their actions, audit events, and request keys are removed on startup after 30 days. In-progress incidents remain. Voice diagnostic events expire after seven days.

The root `render.yaml` creates a free Python API and a static dashboard. In Render, create a Blueprint from this repository and select the `master` branch. Enter the backend secrets requested by the Blueprint using the values in your local `.env`; never upload that file or put secrets in frontend variables. `AGORA_AGENT_ID` and `GUARDIAN_VOICE_PROFILES_JSON` are optional backend overrides; saved agents are created automatically by default.

After Render assigns the URLs, set backend `GUARDIAN_PUBLIC_API_URL` to the API HTTPS base URL and `GUARDIAN_FRONTEND_ORIGINS` to the dashboard HTTPS origin (no trailing slash). Set frontend `VITE_API_URL` to the API base URL and rebuild the static site. Use the actual assigned URLs, which may differ from the service names. Environment variables are loaded directly by Render; no `.env` file is needed there.

Verify `/health`, dashboard authentication, and a fresh voice conversation with tool activity after both services are live. Create an account and sign in with its password. Connect Google and save a trusted contact for approved external notifications and Calendar events.

Free web services can sleep and have ephemeral filesystems: SQLite incidents, approvals, diagnostics, and saved agent references can be lost on restart/redeploy. Keep this deployment for synthetic demo data. Durable storage requires a persistent disk on a suitable paid service or a database migration. See [Render Blueprints](https://render.com/docs/blueprint-spec).

For a single-instance deployment with a mounted persistent disk, set `GUARDIAN_DB_PATH` to a SQLite file on that disk. The parent directory must exist; mounting a disk and migrating any existing database are separate deployment steps. SQLite on an ephemeral free service remains ephemeral even when this setting is supplied.

### Separate bank on Render

The Blueprint includes a free authenticated mock-bank web service and shares its generated service secret with Guardian. Set the API service `MOCK_BANK_URL` to the bank service?s actual HTTPS URL (no trailing path). Free services can sleep; bank unavailability is shown without hiding saved incidents or approvals. Both databases remain ephemeral until durable storage is provisioned. The bank endpoint is public and requires service authentication.

## Registration and profile privacy

The landing page opens Sign in and always shows Login and Register choices. An unknown username opens registration and preserves the entered username. A wrong password for an existing username stays on login. Attempting to register an existing username returns to login. Successful registration signs in automatically. The signed-in profile panel shows masked username, age and address, and the header Profile button toggles it. Login errors carry explicit account_not_found or invalid_credentials codes to support this requested routing.

Registration requires username, password, age (1?120), address, and explicit acceptance of the versioned privacy notice. Details stay in browser memory until Agree & create account. The server validates consent and records its version and UTC timestamp. Declining returns to the form without creating an account.

Set `GUARDIAN_PII_ENCRYPTION_KEY` to a Fernet key before enabling registration (generated in the local .env during setup). Set a separate stable key in Render before releasing this version. Back it up securely outside the database. Losing or changing this key breaks protected username lookup and profile decryption; key rotation requires an explicit migration. No key is committed.

New usernames are stored as keyed lookup digests. Age, address and the original username are stored together as authenticated encrypted ciphertext. Passwords retain salted scrypt hashing. The authenticated /api/auth/profile endpoint returns masked values only with no-store headers. Legacy registered usernames are converted to protected lookup values after a successful login when the key is configured; existing operator usernames retain their legacy storage. Existing accounts can log in without supplying new profile fields.

The frontend refuses non-HTTPS remote APIs. Production registration requires HTTPS; plain HTTP is allowed only for local development (and the test host). TLS protects transport; masking is a display rule, not transport encryption. Browser autofill and the user's own browser can see values they enter. Validation responses omit submitted values; access logs omit bodies. Profile fields are not supplied to Agora, Google or the sandbox bank. Incident summaries, trusted-contact emails and provider data retain their existing storage and approval policies; this change does not encrypt every record across the application.

Encrypted registration profiles and consent records remain for the lifetime of their account database. Self-service profile deletion and consent withdrawal after registration are not implemented; an operator must handle account deletion, including all account-specific files and the central registration record. This is a technical consent record, not a claim of legal compliance.

### Separate Google OAuth configurations

Local development uses GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/integrations/google/callback.
Deployment values are kept separately as GOOGLE_DEPLOY_CLIENT_ID,
GOOGLE_DEPLOY_CLIENT_SECRET and GOOGLE_DEPLOY_REDIRECT_URI in the local .env.
When configuring Render, copy those three deployment values into its runtime
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI variables.
The deployed callback is https://guardian-api-j55w.onrender.com/api/integrations/google/callback.
Register it exactly under Authorized redirect URIs for the deployment Google
OAuth client. The application does not automatically select the deployment
variables during local startup.
