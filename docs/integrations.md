# Google email and calendar setup

## Follow-up series (2026-11-21)

New incidents persist a series of individual reminders. Day 1 and day 7 are
Guardian check-ins, not RBI deadlines; users must report fraud immediately.
Supply the actual bank complaint receipt date and transaction type in the
dashboard or createIncident tool. The series adds an escalation eligibility
review after 30 days have elapsed. RBI's 2026 scheme requires considering the
applicable RBI/NPCI/card-network response period if longer, or an unsatisfactory
reply; this reminder does not determine admissibility or file a complaint.

For confirmed unauthorised electronic transactions, the series also includes a
90-day resolution review. The 10-working-day shadow reversal date must be supplied
from bank confirmation; Guardian does not guess bank holidays. Without those facts
only general reminders are created. Authorised scam transfers are not automatically
treated as unauthorised transactions. These dates are conditional guidance and do
not establish liability or guarantee reimbursement. Dates use Asia/Kolkata;
historical milestones remain dated in the past and should be reviewed promptly.

The exact series titles/dates appear before calendar approval. Every Calendar
event has a stable ID and individual verification/status. Partial failures retain
verified events and stop the series without automatic resend. Local sandbox mode
stores the series without contacting Google. Existing incidents are unchanged.

Sources: [RBI unauthorised transaction circular, paragraphs 9–10](https://www.rbi.org.in/commonman/Upload/English/Notification/PDFs/NOTI1506072017.PDF),
[RBI Integrated Ombudsman Scheme 2026 FAQ](https://rbi.org.in/commonman/English/Scripts/FAQs.aspx?Id=3407).

Each signed-in Guardian user can connect their own Google account.
Banking always remains synthetic. Google mode sends real email and creates real
calendar events only after the user approves each named action in the dashboard.

1. In Google Cloud, enable Gmail API and Google Calendar API.
2. Configure the OAuth consent screen and add your account as a test user.
3. Create a web OAuth client and register the exact Guardian backend callback URL.
   Required scopes are
   `https://www.googleapis.com/auth/gmail.send`,
   `https://www.googleapis.com/auth/gmail.readonly` (read back sent status), and
   `https://www.googleapis.com/auth/calendar.events`.
4. Set server-only `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REDIRECT_URI`, and `GOOGLE_TOKEN_ENCRYPTION_KEY`. The connected
   account's primary calendar is used by default.
5. Sign in to Guardian, select **Connect Google**, grant consent, then save a
   trusted contact email in the dashboard. Each account stores its own encrypted
   refresh token and contact. Create a fresh incident after connecting.
   Successful authorization redirects to `GUARDIAN_FRONTEND_URL` (defaults to
   `http://127.0.0.1:5173`). Set this to the dashboard HTTPS URL on Render.
6. Check the exact email recipient and reminder time shown in the approval titles.
   Approve only the intended actions. Verify the sent message and calendar event
   in your Google account. No live message has been sent by automated tests.

The sent message is checked using Gmail read-back; this proves Gmail's SENT
state, not recipient delivery. Calendar uses a stable event ID and reads the
created event back. Network operations time out after 15 seconds. Ambiguous
failures are persisted and never blindly resent. A `running` action after a
process crash requires operator reconciliation against the Google account.
External action approvals snapshot their recipient/time, so later configuration
changes cannot redirect an already requested action.

Official references: [Gmail send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send),
[Calendar insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[Calendar read-back](https://developers.google.com/workspace/calendar/api/v3/reference/events/get).

## Live demo acceptance

Start a fresh Agora/Murf conversation. Ask Guardian to review the synthetic
transactions and help with an impersonation scam. Confirm at least two tool
invocations in the backend logs, approve the protective action and Google
actions, inspect the resulting card state, sent message, calendar event and
report, then ask Guardian to read back the outcomes. A passing mocked test is
not evidence this live journey has passed.

## Deployment and remaining limits

Set Google OAuth client variables on the Render backend; users connect from the
dashboard. Mount durable storage and set `GUARDIAN_DB_PATH` before relying on
OAuth connections or incident history surviving redeployment. Request limiting is per
process (120 POSTs per minute per connecting IP); multiple workers need a
shared ingress limiter. Live credential verification, audible speech,
interruption behavior and end-to-end Google actions require the operator.
