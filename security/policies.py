"""General-purpose security helpers for Jarvis."""

from __future__ import annotations

from pathlib import Path


def safe_join(base_dir: Path, *parts: str) -> Path:
    """Join a path without allowing directory traversal."""

    candidate = (base_dir.joinpath(*parts)).resolve()
    base_resolved = base_dir.resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ValueError("Resolved path escapes the allowed base directory.")
    return candidate


def sanitize_prompt(prompt: str, max_length: int = 10_000) -> str:
    """Normalize assistant input before handing it to a model or tool."""

    sanitized = prompt.strip()
    if len(sanitized) > max_length:
        raise ValueError(f"Prompt exceeds the maximum length of {max_length} characters.")
    return sanitized