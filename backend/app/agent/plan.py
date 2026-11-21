"""Inspectable dependencies enforced before execution."""
from pydantic import BaseModel
from fastapi import HTTPException


class Assessment(BaseModel):
    severity: str
    basis: list[str]
    missing_facts: list[str]


def assess(summary, transactions):
    text = summary.lower()
    indicators = [word for word in ("police", "threat", "transfer", "money", "bank", "arrest") if word in text]
    suspicious = any(t["suspicious"] for t in transactions)
    return Assessment(severity="high" if indicators or suspicious else "needs_clarification",
                      basis=(["Flagged synthetic transaction requires user confirmation."] if suspicious else []) + indicators,
                      missing_facts=["Does the user recognize the flagged transaction?", "Were any banking credentials exposed?", "Has the user contacted their bank?"]).model_dump()


class PlanStep(BaseModel):
    id: str
    kind: str
    status: str
    depends_on: list[str]
    reason: str


def describe(actions):
    root = next((a["id"] for a in actions if a["kind"] == "investigate"), None)
    return [PlanStep(id=a["id"], kind=a["kind"], status=a["status"],
                     depends_on=[root] if root and a["kind"] != "investigate" else [],
                     reason="Review stored context before protective and follow-up actions.").model_dump()
            for a in actions]


def check_dependencies(conn, incident_id, action_id):
    actions = [dict(a) for a in conn.execute("SELECT * FROM actions WHERE incident_id=?", (incident_id,))]
    steps = describe(actions)
    step = next((s for s in steps if s["id"] == action_id), None)
    if step is None:
        raise HTTPException(404, "Action not found.")
    states = {s["id"]: s["status"] for s in steps}
    if any(states[d] != "succeeded" for d in step["depends_on"]):
        raise HTTPException(409, "Context investigation must succeed first.")
