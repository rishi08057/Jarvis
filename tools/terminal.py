"""Secure terminal execution tool for Jarvis."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    return (_project_root(),)


def _audit(tool_name: str, action: str, outcome: str, details: dict[str, Any] | None = None) -> None:
    payload = {
        "event_type": "terminal.access",
        "tool_name": tool_name,
        "action": action,
        "outcome": outcome,
        "details": details or {},
    }
    logger.info("%s", json.dumps(payload, ensure_ascii=False))


def _allowed_commands() -> tuple[str, ...]:
    return ("git", "python", "pip", "npm")


def _blocked_commands() -> tuple[str, ...]:
    return ("rm", "shutdown", "format", "diskpart", "chkdsk", "fsutil", "mkfs")


def _is_blocked_git_command(args: list[str]) -> bool:
    if not args:
        return False
    first_non_option = next((arg for arg in args if not arg.startswith("-")), None)
    return first_non_option == "push"


@dataclass(slots=True)
class TerminalExecutionTool(Tool):
    """Execute a whitelisted terminal command with timeout and monitoring."""

    approved_directories: tuple[Path, ...] = field(default_factory=_default_approved_directories)
    allowed_commands: tuple[str, ...] = field(default_factory=_allowed_commands)
    blocked_commands: tuple[str, ...] = field(default_factory=_blocked_commands)
    default_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.1

    metadata = ToolMetadata(
        name="terminal_execute",
        description="Run an approved terminal command with security checks.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "command": {"type": "string"},
                "args": {"type": "array"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "number"},
            },
            required=("command",),
        ),
        tags=("terminal", "process", "security"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"]).strip()
        args = list(kwargs.get("args") or [])
        cwd = kwargs.get("cwd")
        timeout_seconds = float(kwargs.get("timeout_seconds", self.default_timeout_seconds))

        _audit(self.name, "execute", "attempt", {"command": command, "args": args, "cwd": cwd, "timeout_seconds": timeout_seconds})

        try:
            if command == "git" and _is_blocked_git_command([str(item) for item in args]):
                raise PermissionError("git push is blocked and cannot be executed.")
            if command.lower() in self.blocked_commands:
                raise PermissionError(f"Command '{command}' is blocked.")

            executable = self._resolve_executable(command)
            resolved_cwd = self._resolve_cwd(cwd)
            command_line = [executable, *map(str, args)]

            started_at = time.perf_counter()
            process = subprocess.Popen(
                command_line,
                cwd=str(resolved_cwd) if resolved_cwd is not None else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=False,
            )
            stdout, stderr, timed_out = self._monitor_process(process, timeout_seconds)
            duration_seconds = time.perf_counter() - started_at
            exit_code = process.returncode if process.returncode is not None else -1

        except PermissionError:
            raise
        except (FileNotFoundError, subprocess.SubprocessError, OSError, ValueError) as exc:
            _audit(self.name, "execute", "failure", {"command": command, "error": str(exc)})
            return ToolResult(
                success=False,
                message=str(exc),
                payload={"command": command, "args": args, "cwd": cwd, "timed_out": False},
            )

        payload = {
            "command": command,
            "args": args,
            "cwd": str(resolved_cwd) if resolved_cwd is not None else None,
            "pid": process.pid,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": timed_out,
            "duration_seconds": duration_seconds,
        }

        if exit_code == 0 and not timed_out:
            _audit(self.name, "execute", "success", {"command": command, "pid": process.pid, "exit_code": exit_code, "duration_seconds": duration_seconds})
            return ToolResult(success=True, payload=payload)

        message = "Command timed out." if timed_out else f"Command exited with code {exit_code}."
        _audit(self.name, "execute", "failure", {"command": command, "pid": process.pid, "exit_code": exit_code, "timed_out": timed_out})
        return ToolResult(success=False, message=message, payload=payload)

    def _resolve_executable(self, command: str) -> str:
        normalized = command.strip().lower()
        if normalized not in self.allowed_commands:
            raise PermissionError(f"Command '{command}' is not allowed.")

        if normalized == "python":
            return sys.executable

        resolved = shutil.which(command)
        if resolved is None:
            raise FileNotFoundError(f"Command '{command}' was not found on PATH.")
        return resolved

    def _resolve_cwd(self, cwd: str | None) -> Path | None:
        if cwd is None:
            return None

        candidate = Path(cwd).expanduser().resolve()
        for approved in self.approved_directories:
            try:
                candidate.relative_to(approved)
                return candidate
            except ValueError:
                continue

        raise PermissionError(f"Working directory '{candidate}' is outside the approved directories.")

    def _monitor_process(self, process: subprocess.Popen[str], timeout_seconds: float) -> tuple[str, str, bool]:
        deadline = time.monotonic() + timeout_seconds
        timed_out = False

        while process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                break
            time.sleep(min(self.poll_interval_seconds, max(deadline - time.monotonic(), 0.0)))

        stdout, stderr = process.communicate()
        return stdout or "", stderr or "", timed_out


__all__ = ["TerminalExecutionTool"]