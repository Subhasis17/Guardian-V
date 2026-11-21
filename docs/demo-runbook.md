# Guardian demo runbook

This runbook covers the local sandbox workflow. Card state, trusted-contact notices, and reminders are synthetic/local records; it does not contact a bank, send email, or create a calendar event.

## Start the app

1. Follow [Run locally](../README.md#run-locally) to start the FastAPI backend and Vite frontend.
2. Open the dashboard and enter the same `DEMO_API_TOKEN` configured for the backend.
3. Confirm the dashboard shows **DEMO SANDBOX** and the synthetic suspicious transfer.

## Run the incident workflow

1. Start a voice conversation with the Hindi profile. The `auto` profile can recognize multilingual input, but the response language and Murf voice remain Hindi for that session.
2. Describe the digital-arrest scenario: someone claiming to be police threatened you and demanded ₹35,000. Do not provide account credentials, OTPs, PINs, or real card details.
3. Let Guardian clarify what happened and review the synthetic transaction. Inspect the transcript and voice diagnostics; client diagnostics do not prove that a tool ran or that audio was heard.
4. When Guardian creates the incident and requests sensitive actions, the **Pending approvals** panel should appear without opening the incident manually. It refreshes every five seconds. Each approval names the action and sandbox consequence.
5. Approve or decline each action separately. An approval updates only the local synthetic card or local outbox record. Verify the plan status and the demo account card state in the dashboard.
6. Open the incident from **Incidents** to review the execution history, follow-up reminder, and downloadable sandbox report.

You can also verify the approval queue in an authenticated API response. In PowerShell, substitute the token without sharing it:

```powershell
$guardianToken = "your DEMO_API_TOKEN"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/context" -Headers @{ Authorization = "Bearer $guardianToken" }
```

`pending_approvals` should contain outstanding actions. Once approved or declined, they disappear from that list and remain visible in the incident plan/history.

## What this run does not verify

- A spoken conversation verifies Agora/RTC/Murf voice only to the extent actually heard by the user. The dashboard diagnostics are client-reported milestones.
- The deployed Agora agent's live tool invocation has not yet been verified end to end. A visible approval is evidence that the backend created an approval request; it does not prove external notification delivery.
- Trusted-contact notices remain local sandbox records. Email delivery, Google Calendar scheduling, durable production storage, and production user authentication are not configured.

For remote deployments, use the deployed HTTPS API URL in place of `http://127.0.0.1:8000`. Free Render storage can be ephemeral, so do not rely on demo records surviving a restart or redeploy.
