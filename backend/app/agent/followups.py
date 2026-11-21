"""Review reminders with conditional RBI milestones, never a refund guarantee."""
from datetime import datetime, timedelta, timezone

RBI_TRANSACTIONS = "https://www.rbi.org.in/commonman/Upload/English/Notification/PDFs/NOTI1506072017.PDF"
RBI_OMBUDSMAN = "https://rbi.org.in/commonman/English/Scripts/FAQs.aspx?Id=3407"
IST = timezone(timedelta(hours=5, minutes=30))


def build_followups(payload, now):
    items = []
    def add(key, title, when, guidance, source=None):
        items.append({"key": key, "title": title, "due_at": when.isoformat(), "guidance": guidance, "source": source})
    add("acknowledgement", "Check bank reporting and acknowledgement", now + timedelta(days=1),
        "Report suspected fraud to your bank immediately; do not wait for this reminder. Keep the complaint acknowledgement. This is a Guardian check-in, not an RBI deadline.")
    add("progress", "Review complaint progress and evidence", now + timedelta(days=7),
        "Check the bank's response and preserve evidence. This is a Guardian check-in, not an RBI deadline.")
    received = payload.bank_complaint_received_on
    if received:
        anchor = datetime.combine(received, datetime.min.time(), IST).replace(hour=10)
        add("escalation", "Review Ombudsman escalation eligibility", anchor + timedelta(days=31),
            "Check whether the bank replied or resolved the complaint. Eligibility depends on the reply and applicable response period: 30 days or the specified RBI/NPCI/card-network period, whichever is higher. This reminder does not file a complaint or establish eligibility.", RBI_OMBUDSMAN)
        if payload.transaction_type == "unauthorised":
            if not payload.bank_shadow_reversal_due_on:
                items[1]["guidance"] += " For applicable unauthorised electronic transactions, RBI specifies shadow reversal within 10 working days of notification. Obtain the exact due date from the bank; no holiday-adjusted deadline has been calculated."
                items[1]["source"] = RBI_TRANSACTIONS
            add("resolution", "Review the 90-day resolution milestone", anchor + timedelta(days=90),
                "For applicable unauthorised electronic banking complaints, check resolution and liability determination within 90 days of bank receipt. Refund or zero liability is not guaranteed.", RBI_TRANSACTIONS)
            if payload.bank_shadow_reversal_due_on:
                due = datetime.combine(payload.bank_shadow_reversal_due_on, datetime.min.time(), IST).replace(hour=10)
                add("shadow_reversal", "Check bank-confirmed shadow reversal due date", due,
                    "RBI specifies shadow reversal within 10 working days of notification for applicable unauthorised electronic transactions. This date is supplied by you from bank confirmation; Guardian does not infer bank holidays or eligibility.", RBI_TRANSACTIONS)
    return sorted(items, key=lambda item: item["due_at"])
