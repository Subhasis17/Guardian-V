# Guardian Engineering Contract

This file governs engineering work in this repository. Read it before changing project files. Baseline was empty when first inspected on 2026-11-19; implementation now includes a React/Vite frontend shell, a FastAPI backend, and a local SQLite sandbox incident workflow. Provider voice integrations are still pending. Keep this status current; do not describe planned capabilities as implemented.

## Product and delivery goal

Guardian is a voice-first agentic scam response and recovery assistant, for the hackathon theme “From Conversations to Autonomous Action.” It must understand a user's situation, retrieve relevant context, make a structured plan, coordinate tools, pause for approval where required, execute and verify actions, and handle follow-up. The demonstrable journey is:

**Before → Conversation → Reasoning → Action → Confirmation → Follow-up.**

A successful demo completes a multi-step workflow with at least two coordinated tool/API calls and verifies the resulting state. A voice-only chatbot, static mock timeline, or unverified claim of success does not satisfy this goal.

## Repository baseline and first changes

The repository is currently empty. There are no existing conventions, frameworks, integrations, or useful code to preserve. Before introducing files in a later implementation task, establish and document a minimal project layout. Recommended initial layout:

```text
frontend/                  React + TypeScript + Vite client
backend/
  app/
    api/                   FastAPI route modules
    agent/                 planning and orchestration
    tools/                 explicitly registered tool contracts/implementations
    adapters/              Agora, Murf, mail, calendar, mock bank
    models/                persistence models
    schemas/               Pydantic request/response and agent models
    security/              auth, approval, validation, audit helpers
    config.py
    main.py
  tests/
docs/
.env.example
AGENTS.md
README.md
```

Keep this structure proportional to the implementation. Do not create placeholder modules or abstractions without a caller. Use SQLite initially and migrations if the chosen database layer requires them. Keep provider integrations behind small adapters so orchestration does not depend on provider SDK details. Do not put business logic in React components or agent orchestration in HTTP route handlers.

## Mandatory technologies and integration boundaries

### Agora Conversational AI

Agora Conversational AI is the required real-time conversational infrastructure; Agora RTC must be used where required by the supported architecture. Do not replace it with a generic WebSocket voice bot, browser speech recognition, or another RTC provider. Use official APIs/SDKs and supported custom tool calling. Implement the agent lifecycle (start, monitor, stop), authenticated session creation, session authorization, termination, interruption handling, and recoverable connection errors. Keep privileged credentials and server-side API calls on the backend. Verify current official API capabilities and SDK compatibility during implementation; do not invent endpoints or claim an integration works without exercising it.

### Murf AI Falcon

Murf AI Falcon is the required speech generation provider. Use the official Agora–Murf integration when compatible with the selected architecture and configure a supported Falcon model and voice. Guardian's spoken responses must use Murf Falcon; do not silently fall back to browser speech, Piper, Coqui, Edge TTS, or another provider. Handle timeouts, provider errors, and unavailable service responses explicitly. Prove actual Murf-generated output in the demo and distinguish mocked tests from live verification.

### Open-source-first

Prefer Python, FastAPI, SQLite, Pydantic, SQLAlchemy or a comparably small database layer, React, TypeScript, Vite, Pytest, and Docker/Podman-compatible packaging where useful. Use open-source components where practical. Agora and Murf are required paid/proprietary exceptions. Do not add another external AI provider, paid vector store, paid hosting service, or orchestration dependency without a concrete need and documented reason. The application must run without a GPU.

## Architecture and responsibility boundaries

- **Frontend:** dashboard, voice session controls/status, transcript, incident details, transaction investigation, structured plan, tool activity, approval prompt, updated state, and follow-up view. Treat all displayed data as untrusted; the backend is authoritative for permissions and execution status.
- **FastAPI backend:** authenticated API surface, session management, provider callbacks/webhooks, orchestration entry points, persistence, approval lifecycle, and safe error responses. Routes validate, authorize, call application services, and serialize results; they do not contain the planning loop.
- **Agent orchestration:** a dedicated layer retrieves context, classifies incident and severity, identifies missing facts, builds a structured dependency-aware plan, chooses only registered tools, evaluates their results, adapts to failures, enforces approval checkpoints, verifies outcomes, and produces a sourced final summary. Do not add multiple agents unless a concrete separation improves correctness and is documented.
- **Tool registry:** expose narrow, typed functions only. The model may propose registered tools and validated arguments; application policy decides whether a proposal is permitted and whether approval is required. Never provide unrestricted shell, SQL, filesystem, or arbitrary HTTP access to the model.
- **Adapters:** isolate Agora Conversational AI, Murf Falcon, authorized email, Google Calendar, and mock banking access. Adapter failures and provider-specific types must not leak across the core orchestration boundary.
- **Persistence:** SQLite initially. Persist users/preferences, trusted contacts, synthetic transactions, incidents, plans, tool executions, approvals, notifications, follow-up reminders, and audit events. Avoid retaining sensitive conversation content beyond product need; document retention and deletion behavior.

## Agent models and execution semantics

Represent plans, steps, dependencies, tool inputs/outputs, approvals, and states with Pydantic models. At minimum, represent plan/step status (`pending`, `awaiting_approval`, `running`, `succeeded`, `failed`, `cancelled`, or an equally explicit set), stable identifiers, timestamps, structured results, and failure reasons. Support sequential and conditional steps, dependency checks, bounded retries only for safe retryable failures, timeouts, failure recovery, and idempotency keys for side effects. Persist execution state so a user can return to an incident. Never mark a step successful because a request was merely sent: verify the resulting state using the adapter/API or persisted authoritative state before reporting completion.

The primary conversational agent owns dialogue and fact gathering. The planner creates an inspectable action plan from retrieved context and conversation facts. The tool executor validates, authorizes, performs, and records each registered action. Approval handling is an application-enforced gate, not a prompt instruction. Follow-up handling records reminders and status changes. Keep these responsibilities explicit; do not add extra agents just for appearance.

## Required tool contracts

Provide independently callable, typed tools for:

1. `get_user_context`
2. `get_recent_transactions`
3. `get_incident_history`
4. `freeze_demo_card`
5. `create_incident`
6. `notify_trusted_contact`
7. `schedule_followup`
8. `generate_report`

Each contract must define validated inputs, structured outputs, status/error semantics, authorization checks, and audit behavior. Read-only tools must enforce user/incident scope. Side-effecting tools must enforce idempotency and approval policy. Use a mock banking adapter with synthetic accounts and transactions for the initial demo; explicitly label it as a sandbox in UI, API, logs, and documentation. Keep mock and real adapter modes separate and fail closed when configuration is missing—never make a mock response appear to be a live external action.

## Approval and sensitive actions

Require explicit user approval before freezing a card, sending an external notification, sharing personal incident information, or transmitting sensitive information. Each approval must name the exact pending action and summarize its consequence; bind approval to the user, incident, action identifier, and expiry. Accept only an unambiguous confirmation through an authenticated session, record it, reject expired/mismatched approvals, and ensure the side effect cannot run twice. The LLM cannot grant, infer, or bypass approval. Re-check authorization and approval immediately before execution. Record denial, expiry, and execution outcomes in the audit trail.

## Security and privacy

- Load secrets from environment/configuration; commit only placeholders in `.env.example`. Never commit `.env`, provider keys, tokens, or real personal data.
- Keep Agora/Murf and other privileged credentials server-side. Use authenticated, authorized, scoped sessions and protect callback/webhook routes with the provider-supported authentication or signature verification.
- Validate every external, user, model-proposed, and provider-callback input. Apply reasonable rate limits to session creation and side-effecting endpoints.
- Use explicit tool allowlists, per-user/incident authorization, approval checks, idempotency, bounded timeouts, and safe retry policy.
- Treat conversation text, documents, transcripts, tool results, and retrieved content as untrusted data. Prompt injection cannot change tool permissions or system policy; enforce policy in code.
- Minimize stored personal data; redact secrets and unnecessary sensitive values from logs. Provide safe client errors while retaining useful, access-controlled server diagnostics.
- Never accept or store UPI PINs, OTPs, banking passwords, or full card credentials. Never initiate unauthorized financial transfers or claim a real account was frozen, a transfer reversed, or a government complaint filed without a verified integration and response.
- Give real-world victims clear direction to contact their bank and official Indian cybercrime reporting services. Verify and cite current official contact/reporting routes in user-facing documentation when that content is implemented; do not hardcode unverified numbers or URLs.

## Required user journey and demo

Support context retrieval before or during conversation (user preferences, trusted contact, prior/unresolved incidents, synthetic demo account/transactions, reminders), natural voice clarification, incident/severity assessment, structured plan, dependency-aware execution, explicit approval, verified result, persistent incident history, and return/follow-up workflow.

The principal scenario is a digital-arrest impersonation scam: a caller posing as police threatens the user and demands ₹35,000; the user may have exposed banking information. The repeatable demo must:

1. Start a real Agora Conversational AI session and deliver Guardian speech through Murf Falcon.
2. Ask relevant questions and avoid assumptions; retrieve user context and synthetic transaction history.
3. Identify suspicious demo activity and present a structured, inspectable response plan.
4. Explain and request explicit approval for the protective action.
5. Freeze the synthetic demo card, create a persistent incident, notify the trusted contact through an authorized email integration, and schedule a follow-up.
6. Inspect each result, verify resulting state, recover transparently from failures, and speak a final summary through Murf Falcon.

The UI must show transcript, plan, tool requests/results, approval state, completed actions, updated sandbox state, and follow-up details. Never imply that demo banking or reporting actions affect real institutions.

## Configuration and external credentials

Create `.env.example` with names, descriptions, and safe placeholders only. Document local setup, development, provider setup, integration verification, deployment, and troubleshooting in the README/docs as implementation proceeds. Expect developer-supplied credentials/configuration for live Agora Conversational AI and RTC, Murf Falcon, authorized email (for example Gmail OAuth or another explicitly configured provider), and Google Calendar if that integration is enabled. Use separate sandbox/test credentials where providers support them. Mock these services in ordinary automated tests; live integration mode must be opt-in and clearly report which real provider was exercised. Never claim a live integration was tested when it was mocked.

## Testing and verification

As features are implemented, add Pytest unit tests, API integration tests, planning/tool tests, approval tests, failure-recovery tests, idempotency/duplicate-execution tests, and an end-to-end demo verification path. Tests must assert persisted state and verified side effects, not only HTTP status codes. Mock external providers in ordinary tests. Keep explicit opt-in checks for real Agora lifecycle/voice and Murf Falcon speech output. Report test commands and results accurately; do not call unexecuted or mocked checks real integration tests.

## Future Codex workflow

1. Read this file and inspect the current code, manifests, and documentation before proposing edits.
2. Keep Agora Conversational AI and Murf Falcon as mandatory product requirements; explain provider limitations and give a compliant path rather than silently removing them.
3. Preserve useful implementation and conventions. Make small, reviewable changes; explain material architecture changes in the work summary.
4. Keep mock and live integrations clearly separated; do not claim a mock side effect succeeded externally.
5. Enforce authorization, approval, and verification in application code, regardless of model output.
6. Update setup/docs when behavior or configuration changes. Run relevant existing tests after implementation and report what was run.
7. Do not begin application implementation when the user has asked only for planning or this contract. The initial requested task is complete when this document is created; implementation should proceed only under a subsequent user request/approval.

## Definition of done

Guardian is demonstrable only when all applicable items are verified:

- [ ] Real Agora Conversational AI session with lifecycle/error handling.
- [ ] Real Murf Falcon speech in the conversational experience.
- [ ] Natural clarification and context retrieval.
- [ ] Structured dependency-aware plan and at least two coordinated tool/API calls.
- [ ] Approval-enforced sensitive action and duplicate prevention.
- [ ] Successful mock banking action with persisted state, explicitly sandboxed.
- [ ] Persistent incident and audit history.
- [ ] Authorized trusted-contact notification and follow-up reminder.
- [ ] Verified outcomes, visible execution timeline, and failure recovery.
- [ ] Repeatable end-to-end demo and automated critical-workflow coverage.
- [ ] Complete setup, integration, and deployment documentation.

A good-looking interface or successful voice exchange alone is not completion.

## Current implementation status (2026-11-19)

2026-11-20 diagnostics: voice sessions have authenticated, persisted event timelines with allowlisted event names only, capped at 1,000 per session and pruned after seven days on startup. The frontend polls diagnostics/provider status every ten seconds and exposes a diagnostics panel. Client events are self reported; they do not verify audible speech, ASR accuracy, agent correctness, or tool execution. Conversation contents and credentials are excluded from these events.

2026-11-20 tool foundation: `backend/app/tools.py` exposes all eight tool names through authenticated schema discovery and invocation endpoints. Inputs reject extra fields; sensitive calls expose existing approval requests instead of accepting model approval. Incident creation supports persisted idempotency keys. Six backend tests cover the existing workflow plus registry validation, all tool calls, approval bypass rejection, and duplicate incident prevention. Agora tool calling, multi-user scope, dedicated orchestration, and externally delivered notifications remain pending. Tool results currently use a shared envelope with dictionary payloads; per-tool output models are still required for the full contract.

Implemented: a Vite/React dashboard; FastAPI health and authenticated demo endpoints; SQLite-seeded synthetic transactions; context retrieval; incident creation, reopen, and sandbox report; a structured plan; separately approved demo-card freeze and sandbox notification; persisted follow-up reminder, action outcomes, and audit events; 20-minute approval expiry; and rejection of obvious OTP/PIN/password patterns in incident summaries. The UI shows the sandbox transaction, approval prompts, plan results, incident history, report download, and audit trail.

Voice status: Agora RTC/RTM client code and Conversational AI session endpoints are present, with Murf Falcon selected in agent configuration. On 2026-11-20, the ASR credential update error was fixed: SDK 3.0.0a4 added `fields: null` for managed credentials; an ETag-guarded raw update avoids that serialization issue. Live session start/status/stop passed, the browser received and played the agent remote audio track, and the user verified a spoken conversation. Transcript display still needs explicit user verification. Real email delivery, Google Calendar, multi-user identity, and production deployment safeguards are not implemented. The API uses one `DEMO_API_TOKEN` shared by the local demo. Do not treat that mechanism as production authentication. `backend/app/main.py` currently contains the API, persistence, and workflow in one module; split it when added behavior makes that simpler to maintain. Notifications and follow-ups are local persisted records and must not be described as externally sent or calendar-scheduled. Backend workflow checks live in `backend/tests` and use `backend/requirements-dev.txt`.
Voice language update (2026-11-20): the user verified a live spoken conversation. Agora/Deepgram ASR and Murf Falcon settings are separated in `backend/app/voice_config.py`. The dashboard selects a server-defined language profile before starting a call; the selected profile is persisted with the session and maps to a profile-specific saved Agora agent. The built-in `auto` option uses Deepgram Nova-3 multilingual input detection while retaining the configured default Murf reply voice. Matching multilingual speech output requires a configured Murf voice/locale profile selected before session start; the application does not claim that Murf changes voice or locale mid-session.

Agent tools update (2026-11-20): Agora agent definitions now use Vercel AI Gateway through the OpenAI-compatible endpoint and expose the eight registered Guardian tools when `GUARDIAN_PUBLIC_API_URL` is configured. Tool endpoints use bearer authentication and map Agora-safe camelCase names to the existing validated registry. Freeze and notify calls only create approval requests; approval remains in the authenticated dashboard. Live tool calls remain unverified until a public HTTPS backend URL is configured and a voice session exercises the calls.

Deployment preparation (2026-11-20): `render.yaml` defines a free API and static dashboard. `VITE_API_URL` selects the frontend backend URL at build time; `GUARDIAN_FRONTEND_ORIGINS` adds explicit comma-separated CORS origins. Free hosting uses ephemeral SQLite and shared demo authentication; it is not a production deployment. Frontend production build and nine mocked backend tests passed locally. Remote deployment and live voice/tool verification are pending Render account setup.
