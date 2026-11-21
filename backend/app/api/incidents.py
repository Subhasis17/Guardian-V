"""HTTP routes; application behavior lives in the service module."""

from fastapi import APIRouter, Depends
from app.schemas import IncidentInput, ApprovalInput, VoiceEvent, VoiceSessionInput
from app.security import require_demo_auth
from app.services import incidents

router = APIRouter()


@router.get("/api/context")
def context(user=Depends(require_demo_auth)):
    return incidents.context(user)


@router.post("/api/incidents")
def create_incident(payload: IncidentInput, user=Depends(require_demo_auth)):
    return incidents.create_incident(payload, user)


@router.get("/api/incidents/{incident_id}/report")
def generate_report(incident_id: str, user=Depends(require_demo_auth)):
    return incidents.generate_report(incident_id, user)


@router.post("/api/incidents/{incident_id}/actions/{action_id}/approval")
def approve_action(
    incident_id: str,
    action_id: str,
    payload: ApprovalInput,
    user=Depends(require_demo_auth),
):
    return incidents.approve_action(incident_id, action_id, payload, user)


@router.get("/api/incidents/{incident_id}")
def read_incident(incident_id: str, user=Depends(require_demo_auth)):
    return incidents.get_incident(incident_id, user)
