"""Application settings for Jarvis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Typed runtime configuration for the assistant."""

    project_root: Path
    app_name: str = "Jarvis"
    environment: str = "development"
    log_level: str = "INFO"
    assistant_name: str = "Jarvis"
    ai_provider: str = "ollama"
    ai_model: str = "qwen3:8b"
    ai_endpoint: str = "http://localhost:11434"
    logs_dir_name: str = "logs"
    memory_dir_name: str = "memory"
    enable_file_logging: bool = True
    summarize_tool_results: bool = False

    @property
    def logs_dir(self) -> Path:
        return self.project_root / self.logs_dir_name

    @property
    def memory_dir(self) -> Path:
        return self.project_root / self.memory_dir_name

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "jarvis.log"

    def to_dict(self) -> dict[str, str | bool]:
        payload = asdict(self)
        payload["project_root"] = str(self.project_root)
        payload["logs_dir"] = str(self.logs_dir)
        payload["memory_dir"] = str(self.memory_dir)
        payload["log_file"] = str(self.log_file)
        return payload
