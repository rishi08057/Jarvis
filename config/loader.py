"""Configuration loading for Jarvis."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience dependency
    load_dotenv = None

from .settings import AppSettings


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_settings() -> AppSettings:
    """Load settings from .env and environment variables."""

    project_root = _project_root()
    if load_dotenv is not None:
        load_dotenv(project_root / ".env")

    settings = AppSettings(
        project_root=project_root,
        app_name=os.getenv("JARVIS_APP_NAME", "Jarvis"),
        environment=os.getenv("JARVIS_ENVIRONMENT", "development"),
        log_level=os.getenv("JARVIS_LOG_LEVEL", "INFO"),
        assistant_name=os.getenv("JARVIS_ASSISTANT_NAME", "Jarvis"),
        ai_provider=os.getenv("JARVIS_AI_PROVIDER", "ollama"),
        ai_model=os.getenv("JARVIS_AI_MODEL", "llama3.1"),
        ai_endpoint=os.getenv("JARVIS_AI_ENDPOINT", "http://localhost:11434"),
        logs_dir_name=os.getenv("JARVIS_LOGS_DIR", "logs"),
        memory_dir_name=os.getenv("JARVIS_MEMORY_DIR", "memory"),
        enable_file_logging=_parse_bool(os.getenv("JARVIS_ENABLE_FILE_LOGGING"), True),
    )

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    return settings
