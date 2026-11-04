from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw == "" else int(raw)


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("COLLECTIONS_DB_PATH", "./data/collections.db")
    database_url: str = os.getenv("COLLECTIONS_DATABASE_URL", "")
    webhook_url: str = os.getenv("COLLECTIONS_WEBHOOK_URL", "")
    webhook_timeout_seconds: int = _int_env("COLLECTIONS_WEBHOOK_TIMEOUT_SECONDS", 5)
    webhook_retries: int = _int_env("COLLECTIONS_WEBHOOK_RETRIES", 3)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    openai_reasoning_effort: str = os.getenv("OPENAI_REASONING_EFFORT", "none")
    openai_service_tier: str = os.getenv("OPENAI_SERVICE_TIER", "default")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    voice_provider: str = os.getenv("VOICE_PROVIDER", "deepgram").strip().lower()
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    deepgram_api_base_url: str = os.getenv("DEEPGRAM_API_BASE_URL", "https://api.in.deepgram.com").rstrip("/")
    deepgram_stt_model: str = os.getenv("DEEPGRAM_STT_MODEL", "nova-3")
    sarvam_api_key: str = os.getenv("SARVAM_API_KEY", "")
    sarvam_stt_model: str = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
    sarvam_stt_language: str = os.getenv("SARVAM_STT_LANGUAGE", "auto")
    sarvam_stt_mode: str = os.getenv("SARVAM_STT_MODE", "translate")
    sarvam_stt_stream_type: str = os.getenv("SARVAM_STT_STREAM_TYPE", "balanced")
    sarvam_stt_keyterms: str = os.getenv(
        "SARVAM_STT_KEYTERMS",
        '["pay","payment","paid","minimum payment","minimum due","Mumbai Bank","late fee"]',
    )
    sarvam_tts_model: str = os.getenv("SARVAM_TTS_MODEL", "bulbul:v4-flash")
    sarvam_tts_speaker: str = os.getenv("SARVAM_TTS_SPEAKER", "shubh_enhi_banking")
    collections_api_token: str = os.getenv("COLLECTIONS_API_TOKEN", "")
    mock_bank_admin_token: str = os.getenv("MOCK_BANK_ADMIN_TOKEN", "")
    mock_otp_ttl_seconds: int = _int_env("MOCK_OTP_TTL_SECONDS", 300)
    app_env: str = os.getenv("APP_ENV", "development").lower()
    demo_access_token: str = os.getenv("DEMO_ACCESS_TOKEN", "")
    mock_bank_enabled: bool = os.getenv("MOCK_BANK_ENABLED", "true").lower() == "true"
    auth_mode: str = os.getenv("AUTH_MODE", "static").lower()
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "")
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "")
    oidc_jwks_url: str = os.getenv("OIDC_JWKS_URL", "")


settings = Settings()
