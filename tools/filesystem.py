"""Filesystem tools for Jarvis."""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from security import safe_join
from security.risk import RiskLevel

from .base import Tool, ToolMetadata, ToolResult, build_object_schema

logger = logging.getLogger("jarvis.security.audit")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_directory(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _default_approved_directories() -> tuple[Path, ...]:
    env_value = os.getenv("JARVIS_APPROVED_DIRECTORIES", "")
    if env_value.strip():
        return tuple(_normalize_directory(part) for part in env_value.split(os.pathsep) if part.strip())
    root = _project_root()
    return (root, root / "memory", root / "logs")


def _audit(tool_name: str, action: str, path: Path | None, outcome: str, details: dict[str, Any] | None = None) -> None:
    payload = {
        "event_type": "filesystem.access",
        "tool_name": tool_name,
        "action": action,
        "path": str(path) if path is not None else None,
        "outcome": outcome,
        "details": details or {},
    }
    logger.info("%s", payload)


@dataclass(slots=True)
class FilesystemToolBase(Tool):
    """Base class that resolves and validates filesystem access."""

    approved_directories: tuple[Path, ...] = field(default_factory=_default_approved_directories)

    def _resolve_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path).expanduser()
        resolved = candidate.resolve()
        if candidate.is_absolute():
            for approved in self.approved_directories:
                try:
                    resolved.relative_to(approved)
                    return resolved
                except ValueError:
                    continue
        else:
            for approved in self.approved_directories:
                try:
                    return safe_join(approved, str(candidate))
                except ValueError:
                    continue

        raise PermissionError(f"Path '{resolved}' is outside the approved directories.")

    def _read_text(self, path: Path, start_line: int | None = None, end_line: int | None = None) -> str:
        text = path.read_text(encoding="utf-8")
        if start_line is None and end_line is None:
            return text

        lines = text.splitlines()
        start_index = max((start_line or 1) - 1, 0)
        end_index = end_line if end_line is not None else len(lines)
        return "\n".join(lines[start_index:end_index])


@dataclass(slots=True)
class ReadFileTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="read_file",
        description="Read a text file within approved directories.",
        risk_level=RiskLevel.LOW,
        parameters_schema=build_object_schema(
            properties={
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            required=("path",),
        ),
        tags=("filesystem", "read"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        path = self._resolve_path(kwargs["path"])
        start_line = kwargs.get("start_line")
        end_line = kwargs.get("end_line")
        _audit(self.name, "read_file", path, "attempt")
        try:
            content = self._read_text(path, start_line=start_line, end_line=end_line)
        except OSError as exc:
            _audit(self.name, "read_file", path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"path": str(path)})

        _audit(self.name, "read_file", path, "success", {"bytes": len(content.encode("utf-8"))})
        return ToolResult(success=True, payload={"path": str(path), "content": content})


@dataclass(slots=True)
class WriteFileTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="write_file",
        description="Write text to a file within approved directories.",
        risk_level=RiskLevel.MEDIUM,
        parameters_schema=build_object_schema(
            properties={
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=("path", "content"),
        ),
        tags=("filesystem", "write"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        path = self._resolve_path(kwargs["path"])
        content = kwargs["content"]
        _audit(self.name, "write_file", path, "attempt")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            _audit(self.name, "write_file", path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"path": str(path)})

        _audit(self.name, "write_file", path, "success", {"bytes": len(content.encode("utf-8"))})
        return ToolResult(success=True, payload={"path": str(path), "bytes_written": len(content.encode("utf-8"))})


@dataclass(slots=True)
class ListDirectoryTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="list_directory",
        description="List files and folders within an approved directory.",
        risk_level=RiskLevel.LOW,
        parameters_schema=build_object_schema(
            properties={"path": {"type": "string"}},
            required=("path",),
        ),
        tags=("filesystem", "list"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        path = self._resolve_path(kwargs["path"])
        _audit(self.name, "list_directory", path, "attempt")
        try:
            entries = sorted(child.name + ("/" if child.is_dir() else "") for child in path.iterdir())
        except OSError as exc:
            _audit(self.name, "list_directory", path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"path": str(path)})

        _audit(self.name, "list_directory", path, "success", {"entry_count": len(entries)})
        return ToolResult(success=True, payload={"path": str(path), "entries": entries})


@dataclass(slots=True)
class SearchFilesTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="search_files",
        description="Search filenames under approved directories using glob patterns.",
        risk_level=RiskLevel.LOW,
        parameters_schema=build_object_schema(
            properties={
                "path": {"type": "string"},
                "pattern": {"type": "string"},
            },
            required=("path", "pattern"),
        ),
        tags=("filesystem", "search"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        root = self._resolve_path(kwargs["path"])
        pattern = kwargs["pattern"]
        _audit(self.name, "search_files", root, "attempt", {"pattern": pattern})
        try:
            matches = [str(path) for path in root.rglob("*") if fnmatch.fnmatch(path.name, pattern)]
        except OSError as exc:
            _audit(self.name, "search_files", root, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"path": str(root)})

        _audit(self.name, "search_files", root, "success", {"match_count": len(matches)})
        return ToolResult(success=True, payload={"path": str(root), "pattern": pattern, "matches": matches})


@dataclass(slots=True)
class SearchCodeTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="search_code",
        description="Search file contents under approved directories.",
        risk_level=RiskLevel.LOW,
        parameters_schema=build_object_schema(
            properties={
                "path": {"type": "string"},
                "query": {"type": "string"},
            },
            required=("path", "query"),
        ),
        tags=("filesystem", "search", "code"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        root = self._resolve_path(kwargs["path"])
        query = kwargs["query"]
        _audit(self.name, "search_code", root, "attempt", {"query": query})
        try:
            matches: list[dict[str, Any]] = []
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                lines = content.splitlines()
                for index, line in enumerate(lines, start=1):
                    if query in line:
                        matches.append({"path": str(file_path), "line": index, "content": line})
        except OSError as exc:
            _audit(self.name, "search_code", root, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"path": str(root)})

        _audit(self.name, "search_code", root, "success", {"match_count": len(matches)})
        return ToolResult(success=True, payload={"path": str(root), "query": query, "matches": matches})
