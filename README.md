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

## Live voice status

The browser connects through Agora RTC and RTM, and the backend prepares and starts Conversational AI sessions configured for Murf Falcon. A live browser check on 2026-11-20 connected successfully, received the agent remote audio track, and entered playback; stopping returned the UI to "Voice session ended". The saved-agent update uses an ETag-guarded raw update because SDK 3.0.0a4 adds a rejected `fields: null` to managed credentials. A spoken user reply and transcript display still need verification. Real email and Google Calendar remain unconnected. Never expose provider credentials in the frontend.

See [AGENTS.md](AGENTS.md) for the engineering and safety contract.

Each incident can produce a downloadable Markdown summary labeled as a sandbox report; it is not a bank or police report.
