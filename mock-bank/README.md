# Guardian sandbox bank

Guardian tool requests are also recorded in backend/logs/tools.log, including
rejected authentication/validation and execution start/results. Correlate by
request_id. Automated tests write separate temporary logs. Voice callbacks only
appear here when GUARDIAN_PUBLIC_API_URL routes to this API instance; local
testing requires a public HTTPS tunnel to port 8000.

Both services write rotating JSON files: info.log, error.log (warnings/errors),
and access.log under backend/logs/ and mock-bank/logs/ respectively. Files rotate
at 5 MB with five backups each. Access entries contain route templates, status,
duration and generated request IDs; request bodies, headers and query strings
are excluded. Log directories are ignored by Git. Guardian logs each tool
execution and Agora-managed LLM session lifecycle. Per-turn LLM calls inside
Agora are not visible locally. The dashboard no longer displays transcripts.

This separate FastAPI process owns synthetic bank accounts, card status and
transactions in `mock-bank/bank.db`. It never contacts real institutions.
Guardian derives the account identity from the authenticated user; model inputs
cannot select a different account. Server requests use an HMAC credential bound
to that identity. Every account receives a distinct, persistent synthetic history.

From the repository root, start it using the existing backend environment:

```powershell
backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir mock-bank --host 127.0.0.1 --port 8001 --env-file .env
```

Set `MOCK_BANK_URL=http://127.0.0.1:8001` and the same
`MOCK_BANK_SERVICE_SECRET` in both processes. The checked-in example contains
only a placeholder; replace the local development secret before hosting.
Keep this service private, use HTTPS between hosts, and persist its database.
Guardian fails explicitly when the bank cannot be reached. Card freezes require
dashboard approval, use action IDs for duplicate prevention, and read account
state back before Guardian reports success. Legacy Guardian bank tables are
retained for old records; live sandbox reads use this service.

Agora's `GUARDIAN_PUBLIC_API_URL` must reach the same Guardian API that owns the
signed-in account. For local voice tool tests, supply a public HTTPS tunnel to
port 8000. A Render URL routes callbacks to Render, not to this local database.
Start a fresh voice session after changing it. No real bank connection exists.
