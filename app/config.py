from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, fallback: bool = False) -> bool:
    if value is None or value == "":
        return fallback
    return value.strip().lower() in {"1", "true", "yes"}


def _as_int(value: str | None, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class AppConfig:
    port: int
    public_base_url: str
    openai_api_key: str
    openai_model: str
    faq_vector_store_id: str
    issue_tracker_url: str
    issue_tracker_token: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_validate_signature: bool
    state_file: Path
    max_tool_iterations: int


def load_config() -> AppConfig:
    config = AppConfig(
        port=_as_int(os.getenv("PORT"), 8080),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip(),
        openai_api_key=_required("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        faq_vector_store_id=os.getenv("FAQ_VECTOR_STORE_ID", "").strip(),
        issue_tracker_url=os.getenv("ISSUE_TRACKER_URL", "").strip(),
        issue_tracker_token=os.getenv("ISSUE_TRACKER_TOKEN", "").strip(),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        twilio_validate_signature=_as_bool(os.getenv("TWILIO_VALIDATE_SIGNATURE"), True),
        state_file=Path(os.getenv("STATE_FILE", "./data/state.json")).resolve(),
        max_tool_iterations=_as_int(os.getenv("MAX_TOOL_ITERATIONS"), 3),
    )

    if config.twilio_validate_signature and not config.twilio_auth_token:
        raise RuntimeError(
            "TWILIO_AUTH_TOKEN is required when TWILIO_VALIDATE_SIGNATURE=true"
        )

    if config.twilio_validate_signature and not config.public_base_url:
        print(
            "WARNING: PUBLIC_BASE_URL is empty. Twilio signature validation may fail behind reverse proxies."
        )

    return config
