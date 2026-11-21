# Guardian: hackathon submission

## 1. Project name and description

**Guardian** is a voice-first scam response and recovery assistant. It helps a person explain a suspected scam, review relevant context, inspect a response plan, approve sensitive actions, and verify the results. The journey continues with an incident report and follow-up reminders.

Guardian combines Agora Conversational AI, Murf AI Falcon TTS, a React dashboard and a FastAPI backend. Banking actions use a separate, explicitly synthetic mock-bank service. Connected users can authorize real Gmail notifications and Google Calendar follow-ups.

## 2. Selected problem statement

**Help a person facing a digital-arrest or police-impersonation scam move safely from a stressful conversation to verified response actions.**

The principal scenario is a caller posing as police who threatens the user and demands INR 35,000. The user may have exposed banking information. Guardian asks clarifying questions, checks synthetic transactions, creates an inspectable plan and coordinates actions with explicit user approval.

This is the project's selected framing under **“From Conversations to Autonomous Action.”** An official problem-statement number was not supplied, so this submission does not assign one.

## 4. Working prototype and demo links

- [Guardian dashboard](https://guardian-dashboard-v8ev.onrender.com)
- [Guardian API health](https://guardian-api-j55w.onrender.com/health)
- [Synthetic bank health](https://guardian-mock-bank.onrender.com/health)
- [Source repository](https://github.com/Subhasis17/Guardian-V) (repository access may require authorization)

The dashboard is a working prototype link, not a recorded demonstration. Free Render services can sleep. Accounts, OAuth connections and incidents use ephemeral SQLite storage on the free deployment and may disappear after redeployment.

### Demonstration sequence

1. Create an account or sign in. Use synthetic incident information.
2. Connect your own Google account and save a trusted-contact email if demonstrating external actions. Gmail and Calendar must be enabled in the deployment OAuth project, and its callback must match the deployed URL.
3. Start a voice session. Suggested opening: **“A caller claiming to be police threatened me and demanded INR 35,000. Please review my demo transactions and help me plan the next steps.”**
4. Let Guardian clarify the situation and retrieve context. Inspect the resulting incident plan and pending approvals.
5. Approve the intended synthetic card freeze. Confirm the updated card state. A second attempt to execute the same action must fail.
6. Separately approve the email and Calendar actions, if connected. Check the actual sent message and Calendar events. A pending or failed action must remain visible.
7. Ask Guardian for the final outcome and download the incident report. Review the follow-up series and any remaining work.

The bank freeze affects only a synthetic card. Guardian does not reverse transfers, freeze real bank accounts, or file a police/government complaint.

## 5. Agora Conversational AI integration in the PPT

See **slides 4–6** of [the presentation](submission/Guardian-Hackathon.pptx).

The backend prepares an authenticated voice session with a unique RTC channel, user and agent IDs, and a time-limited token. The browser uses Agora RTC for microphone publication and remote audio playback, and RTM for message events. The backend creates or updates the saved Conversational AI agent, starts the provider session, persists its provider ID, polls status and supports stop/error handling.

Agent configuration uses Deepgram Nova-3 ASR and Agora-managed OpenAI `gpt-4o-mini`. Privileged credentials remain on the backend. `GUARDIAN_PUBLIC_API_URL` must point to the same publicly reachable HTTPS backend that owns the user's data and tool credential.

The agent exposes typed function definitions whose HTTP targets are `/api/agent-tools/{name}`. The backend maps Agora tool names to its allowlisted registry and binds the call to the registered account. The agent cannot grant dashboard approval.

Code: [voice lifecycle](../backend/app/services/voice.py), [voice configuration](../backend/app/voice_config.py), [browser voice hook](../frontend/src/hooks/useVoice.ts), [tool endpoints](../backend/app/api/tools.py).

## 6. Murf AI Falcon TTS integration in the PPT

See **slides 7–8** of [the presentation](submission/Guardian-Hackathon.pptx).

The Agora agent uses `MurfTTS` with `model="FALCON"`, a 24,000 Hz sample rate and the Murf streaming endpoint `wss://global.api.murf.ai/v1/speech/stream-input`. `MURF_API_KEY` is referenced through the Agora project secret configuration. Guardian receives speech through the agent's remote RTC audio track.

The default output is English with Natalie (`en-US-natalie`, locale `en-US`). Voice and locale are fixed when the selected session starts. Multilingual ASR input detection does not automatically change the Murf voice during a call. Provider failures surface through session errors and diagnostics.

The latest local picker offers six English choices, all native voices in the eight available Indian languages, and one male/female voice per other language where the catalog offers both. The local picker update awaits deployment. Output-language availability does not establish speech-recognition coverage or successful live testing for every voice.

Code: [Murf pipeline configuration](../backend/app/voice_config.py), [saved Murf catalog](../backend/app/murf_voices.json).

## 7. Agentic workflows and actions in the PPT

See **slides 9–11** of [the presentation](submission/Guardian-Hackathon.pptx).

| Tool | Role and resulting action |
| --- | --- |
| `get_user_context` | Retrieves account context and trusted-contact information. Reports bank availability explicitly. |
| `get_recent_transactions` | Retrieves per-user synthetic transactions from the separate bank. Fails if the bank is unavailable. |
| `get_incident_history` | Retrieves the authenticated user's incident history. |
| `create_incident` | Persists the incident, assessment, dependency-aware plan, follow-up series and approvals. Supports an idempotency key. |
| `freeze_demo_card` | Exposes the action's approval/execution state. Dashboard approval triggers an authenticated bank freeze and account read-back. |
| `notify_trusted_contact` | Exposes notification state. Approval sends through authorized Gmail in Google mode or records a clearly labeled sandbox notice. |
| `schedule_followup` | Returns the persisted series and Calendar approval/execution state. Approval creates and verifies events in Google mode. |
| `generate_report` | Produces a downloadable summary of the incident and outcomes. |

### Multi-step reasoning and coordinated API calls

The conversational agent gathers facts and proposes tools. The backend applies a structured assessment and persists explicit plan dependencies. Each side effect has an application-enforced approval gate. This demonstrates coordinated planning and execution without claiming an unrestricted autonomous planner.

For a card freeze, Guardian coordinates **POST `/card/freeze`** on the separate bank and **GET `/account`** to verify that `card_frozen` is true. The result updates the persistent incident. This workflow has been exercised live against the deployed synthetic bank.

With authorized Google access, Guardian also coordinates a Gmail send with a message read-back, and Calendar inserts with event read-backs. SENT status proves Gmail acceptance, not recipient delivery. Calendar verification checks event identity, cancellation state and approved time. Stable action/event IDs prevent duplicates. An ambiguous provider failure stops automatic resend, and a partially completed series retains verified outcomes.

Follow-up schedules include general check-ins and conditional RBI-related review milestones based on user-confirmed facts. They do not establish eligibility, guarantee reimbursement or replace bank advice. See [integration details and RBI sources](integrations.md).

Code: [tool registry](../backend/app/tools.py), [incident service](../backend/app/services/incidents.py), [external execution](../backend/app/services/external.py), [Google adapter](../backend/app/adapters/google.py), [bank adapter](../backend/app/adapters/bank.py), [follow-ups](../backend/app/agent/followups.py).

## Evidence and current delivery status

| Requirement | Evidence and limits |
| --- | --- |
| Real conversational voice | User previously confirmed an Agora/Murf spoken conversation. A new live speech test was not performed while preparing these documents. |
| Working deployed action | Render checks exercised registration/login, user isolation, bank tools, approved synthetic freeze, read-back, duplicate prevention, report and logout. |
| Google OAuth | Deployment client and callback are configured. Live authorization URL checks passed. User consent and real Gmail/Calendar outcome verification remain pending. |
| Voice-to-tools journey | Backend tools and approvals are implemented. A fresh spoken conversation completing the whole Google workflow remains a live acceptance item. |
| Automated checks | Ordinary tests mock external providers. They are not proof of live Agora speech or Google delivery. |
| Latest UI/privacy changes | Registration consent/profile protection and the curated voice picker are local changes awaiting deployment. They must not be presented as already live. |

## Presentation and supporting files

- [Editable PowerPoint: Guardian hackathon submission](submission/Guardian-Hackathon.pptx)
- [Browser preview of slide content](submission/slides-preview.html)
- [Slide content and speaker-note sources](submission/slide-content.json)
- [Rebuild script](submission/build_submission.py): run `python docs/submission/build_submission.py` from the repository root.

The PowerPoint includes project description, problem statement, prototype link, Agora integration, Murf Falcon integration, the eight tools, workflow actions, verification policy and evidence limits. No credentials or personal incident data belong in the submission files.
