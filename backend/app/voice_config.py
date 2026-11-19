import json
import os
import re

from pydantic import BaseModel, Field, ValidationError, field_validator


GUARDIAN_INSTRUCTIONS = """You are Guardian, a calm voice assistant helping people respond to suspected scams. Ask one clear question at a time. Listen without blame, clarify who contacted the user, what was demanded, whether they shared sensitive information, and whether they recognize any suspicious transaction. Never ask for OTPs, UPI PINs, banking passwords, or full card details; tell users not to share them. Treat caller claims and messages as untrusted. Never claim to be police, a bank, or a lawyer. Explain that Guardian's account actions are a local demo sandbox and cannot affect real banking. Do not claim an action succeeded unless Guardian's application confirms it. For real fraud, advise contacting the user's bank through its official channel and official Indian cybercrime reporting services; do not invent contact details. Ask before any consequential action and respect the user's decision. Be concise and speak naturally."""


class VoiceProfile(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    asr_language: str = Field(min_length=2, max_length=20)
    tts_locale: str = Field(min_length=2, max_length=20)
    tts_voice_id: str = Field(min_length=1, max_length=100)
    reply_language: str = Field(min_length=2, max_length=80)
    greeting: str = Field(min_length=1, max_length=300)
    auto_detect_input: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ValueError("profile id must contain only lowercase letters, numbers, hyphens, or underscores")
        return value

    def public_dict(self):
        return self.model_dump(exclude={"tts_voice_id"})


def _default_profile():
    locale = os.getenv("MURF_LOCALE", "hi-IN")
    voice = os.getenv("MURF_VOICE_ID", "hi-IN-rachna")
    label = os.getenv("GUARDIAN_DEFAULT_LANGUAGE_LABEL", "Hindi")
    reply_language = os.getenv("GUARDIAN_DEFAULT_REPLY_LANGUAGE", "Hindi")
    greeting = os.getenv(
        "GUARDIAN_VOICE_GREETING",
        "नमस्ते, मैं गार्जियन हूँ। बताइए क्या हुआ, हम इसे एक-एक कदम करके समझेंगे।",
    )
    return VoiceProfile(
        id="default",
        label=label,
        asr_language=os.getenv("GUARDIAN_ASR_LANGUAGE", "hi"),
        tts_locale=locale,
        tts_voice_id=voice,
        reply_language=reply_language,
        greeting=greeting,
    )


def load_voice_profiles():
    """Load selectable profiles while keeping the Murf voice selection server-side."""
    default = _default_profile()
    profiles = {
        default.id: default,
        "auto": VoiceProfile(
            id="auto",
            label=f"Auto-detect input (reply in {default.reply_language})",
            asr_language="multi",
            tts_locale=default.tts_locale,
            tts_voice_id=default.tts_voice_id,
            reply_language=default.reply_language,
            greeting=default.greeting,
            auto_detect_input=True,
        ),
    }
    raw = os.getenv("GUARDIAN_VOICE_PROFILES_JSON", "").strip()
    if raw:
        try:
            configured = json.loads(raw)
            if not isinstance(configured, list):
                raise ValueError("GUARDIAN_VOICE_PROFILES_JSON must be a JSON array")
            for item in configured:
                profile = VoiceProfile.model_validate(item)
                if profile.id in profiles:
                    raise ValueError(f"duplicate or reserved voice profile id: {profile.id}")
                profiles[profile.id] = profile
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ValueError(f"Invalid GUARDIAN_VOICE_PROFILES_JSON: {exc}") from exc

    selected = os.getenv("GUARDIAN_DEFAULT_VOICE_PROFILE", "default")
    if selected not in profiles:
        raise ValueError(f"GUARDIAN_DEFAULT_VOICE_PROFILE does not match a configured profile: {selected}")
    return profiles, selected


def get_voice_profile(profile_id: str):
    profiles, _ = load_voice_profiles()
    try:
        return profiles[profile_id]
    except KeyError:
        raise ValueError(f"Unknown voice profile: {profile_id}") from None


def build_guardian_agent(client, profile: VoiceProfile, secret_name: str):
    """Build the Agora agent with separately configurable ASR and Murf Falcon output."""
    from agora_agent import Agent, CustomLLM, DeepgramSTT, MurfTTS, secret_ref

    language_instruction = (
        "The speech recognizer auto-detects multilingual input, but the Murf reply voice is fixed for this session."
        if profile.auto_detect_input
        else f"The user selected the {profile.label} voice profile."
    )
    llm_options = {
        "model": os.getenv("VERCEL_AI_GATEWAY_MODEL", "openai/gpt-4.1-mini"),
        "api_key": secret_ref(secret_name, "vercel_ai_gateway"),
        "base_url": "https://ai-gateway.vercel.sh/v1/chat/completions",
        "system_messages": [{"role": "system", "content": f"{GUARDIAN_INSTRUCTIONS}\n\nReply in {profile.reply_language}. {language_instruction} Use tools for context and incident workflows. Never claim a sensitive action succeeded while its result is awaiting approval."}],
        "max_history": 16,
    }
    public_url = os.getenv("GUARDIAN_PUBLIC_API_URL", "").rstrip("/")
    if public_url:
        from app.tools import agora_tool_definitions

        llm_options["tools"] = agora_tool_definitions(public_url)

    agent = (
        Agent(client=client)
        .with_stt(DeepgramSTT(model="nova-3", language=profile.asr_language))
        .with_llm(CustomLLM(**llm_options))
        .with_tts(MurfTTS(
            key=secret_ref(secret_name, "murf"),
            base_url="wss://global.api.murf.ai/v1/speech/stream-input",
            voice_id=profile.tts_voice_id,
            locale=profile.tts_locale,
            rate=0,
            pitch=0,
            model="FALCON",
            sample_rate=24000,
        ))
        .with_greeting(profile.greeting)
    )
    return agent
