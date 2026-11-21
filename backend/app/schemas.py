"""Validated request bodies shared by routes and services."""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator


class IncidentInput(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    incident_type: str = Field(default="Digital arrest / impersonation", max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    transaction_type: Literal["unknown", "unauthorised", "authorised"] = "unknown"
    bank_complaint_received_on: date | None = None
    bank_shadow_reversal_due_on: date | None = None

    @model_validator(mode="after")
    def validate_bank_dates(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        if self.bank_complaint_received_on and self.bank_complaint_received_on > today:
            raise ValueError("Bank complaint receipt cannot be in the future.")
        if self.bank_shadow_reversal_due_on and (not self.bank_complaint_received_on or self.transaction_type != "unauthorised" or self.bank_shadow_reversal_due_on < self.bank_complaint_received_on):
            raise ValueError("Shadow reversal date requires an unauthorised transaction and bank receipt date, and cannot precede receipt.")
        return self

    @field_validator("summary")
    @classmethod
    def reject_secrets(cls, value):
        if re.search(
            r"\b(?:otp|pin|password|passcode)\D{0,20}\d{4,8}\b", value, re.IGNORECASE
        ):
            raise ValueError(
                "Do not include OTPs, PINs, or passwords in an incident summary."
            )
        return value


class ApprovalInput(BaseModel):
    approved: StrictBool


class VoiceEvent(BaseModel):
    model_config = {"extra": "forbid"}
    event: Literal[
        "prepared",
        "rtc_joined",
        "rtc_disconnected",
        "mic_published",
        "rtm_connected",
        "message_received",
        "transcript_received",
        "transcript_unrecognized",
        "remote_audio_play_requested",
        "remote_audio_failed",
        "agent_started",
        "agent_start_failed",
        "status_check_failed",
        "stop_failed",
        "stopped",
    ]


class VoiceSessionInput(BaseModel):
    model_config = {"extra": "forbid"}
    profile_id: str = Field(
        default="default", min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )


class AgentToolInput(BaseModel):
    model_config = {"extra": "forbid"}
    arguments: dict
    tool_call_id: str = Field(min_length=1, max_length=128)
