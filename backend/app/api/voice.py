"""HTTP routes; application behavior lives in the service module."""

from fastapi import APIRouter, Depends
from app.schemas import IncidentInput, ApprovalInput, VoiceEvent, VoiceSessionInput
from app.security import require_demo_auth
from app.services import voice

router = APIRouter()


@router.post("/api/voice/sessions/{local_id}/events")
def voice_event(local_id: str, payload: VoiceEvent, user=Depends(require_demo_auth)):
    return voice.voice_event(local_id, payload, user)


@router.get("/api/voice/sessions/{local_id}/diagnostics")
def voice_diagnostics(local_id: str, user=Depends(require_demo_auth)):
    return voice.voice_diagnostics(local_id, user)


@router.get("/api/voice/config")
def voice_config(user=Depends(require_demo_auth)):
    return voice.voice_config(user)


@router.post("/api/voice/session")
def prepare_voice_session(payload: VoiceSessionInput, user=Depends(require_demo_auth)):
    return voice.prepare_voice_session(payload, user)


@router.post("/api/voice/sessions/{local_id}/start")
def start_voice_session(local_id: str, user=Depends(require_demo_auth)):
    return voice.start_voice_session(local_id, user)


@router.get("/api/voice/sessions/{local_id}")
def voice_session_status(local_id: str, user=Depends(require_demo_auth)):
    return voice.voice_session_status(local_id, user)


@router.post("/api/voice/sessions/{local_id}/stop")
def stop_voice_session(local_id: str, user=Depends(require_demo_auth)):
    return voice.stop_voice_session(local_id, user)
