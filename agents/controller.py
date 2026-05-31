"""Routing controller between chat state, tools, and the LLM."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from security import PermissionManager, SecurityContext, SecurityMiddleware
from tools import ToolManager, ToolRegistry
from tools.manager import ToolValidationError

from ui.session import ChatResponse, ChatSession, ConversationTurn, SupportsLLMManager


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_? ]+", " ", message.lower())).strip()


def _coerce_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


@dataclass(slots=True)
class AgentController:
    """Route user messages to tools first, then fall back to the LLM."""

    session: ChatSession
    llm: SupportsLLMManager
    tool_registry: ToolRegistry
    permission_manager: PermissionManager = field(default_factory=PermissionManager)
    security_context: SecurityContext = field(
        default_factory=lambda: SecurityContext(actor_id="terminal-chat", roles=("operator",))
    )
    default_workspace: Path = field(default_factory=_project_root)
    tool_manager: ToolManager = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.tool_manager = ToolManager(
            registry=self.tool_registry,
            security_middleware=SecurityMiddleware(permission_manager=self.permission_manager),
        )

    def handle(
        self,
        message: str,
        *,
        on_chunk: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        """Handle a single user message with tool routing and LLM fallback."""

        start = perf_counter()
        self.session.history.append(ConversationTurn(role="user", content=message))

        if self._is_available_tools_request(message):
            response_text = self._format_available_tools()
            self.session.history.append(ConversationTurn(role="assistant", content=response_text))
            if on_chunk is not None:
                on_chunk(response_text)
            return ChatResponse(message=response_text, elapsed_seconds=perf_counter() - start, success=True)

        tool_name = self._match_tool(message)
        if tool_name is not None:
            return self._handle_tool_request(message, tool_name, start=start, on_chunk=on_chunk, timeout=timeout)

        response_text, success = self._stream_llm_response(message, on_chunk=on_chunk, timeout=timeout)
        elapsed = perf_counter() - start
        self.session.history.append(ConversationTurn(role="assistant", content=response_text or ""))
        return ChatResponse(message=response_text or None, elapsed_seconds=elapsed, success=success, error=None if success else self.llm.last_error)

    def clear_history(self) -> None:
        self.session.clear()

    def list_available_tools(self) -> list[str]:
        return [metadata.name for metadata in self.tool_registry.list_tools()]

    def _handle_tool_request(
        self,
        message: str,
        tool_name: str,
        *,
        start: float,
        on_chunk: Callable[[str], None] | None,
        timeout: float | None,
    ) -> ChatResponse:
        parameters = self._build_tool_parameters(tool_name, message)
        try:
            result = self.tool_manager.execute(tool_name, parameters, context=self.security_context)
        except (PermissionError, LookupError, ToolValidationError, ValueError, TypeError, RuntimeError, OSError) as exc:
            elapsed = perf_counter() - start
            response_text = f"Tool execution failed: {exc}"
            self.session.history.append(ConversationTurn(role="assistant", content=response_text))
            if on_chunk is not None:
                on_chunk(response_text)
            return ChatResponse(message=response_text, elapsed_seconds=elapsed, success=False, error=str(exc))

        if not result.success:
            elapsed = perf_counter() - start
            response_text = result.message or f"{tool_name} failed."
            self.session.history.append(ConversationTurn(role="assistant", content=response_text))
            if on_chunk is not None:
                on_chunk(response_text)
            return ChatResponse(message=response_text, elapsed_seconds=elapsed, success=False, error=result.message or tool_name)

        summary_prompt = self._build_tool_summary_prompt(message, tool_name, result.payload)
        response_text, success = self._stream_llm_from_prompt(summary_prompt, on_chunk=on_chunk, timeout=timeout)
        elapsed = perf_counter() - start
        if not response_text:
            response_text = self._fallback_tool_summary(tool_name, result.payload)
            success = True
            if on_chunk is not None:
                on_chunk(response_text)

        self.session.history.append(ConversationTurn(role="assistant", content=response_text))
        return ChatResponse(message=response_text, elapsed_seconds=elapsed, success=success, error=None if success else self.llm.last_error)

    def _stream_llm_response(
        self,
        message: str,
        *,
        on_chunk: Callable[[str], None] | None,
        timeout: float | None,
    ) -> tuple[str, bool]:
        prompt = self.session.build_prompt(message)
        return self._stream_llm_from_prompt(prompt, on_chunk=on_chunk, timeout=timeout)

    def _stream_llm_from_prompt(
        self,
        prompt: str,
        *,
        on_chunk: Callable[[str], None] | None,
        timeout: float | None,
    ) -> tuple[str, bool]:
        try:
            generate = getattr(self.llm, "generate")
            response_parts: list[str | None] = []
            response_parts.append(generate(prompt, system=self.session.system_prompt, timeout=timeout))
            response_text = response_parts[0]
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive fallback
            self.llm.last_error = str(exc)
            return "", False

        if response_text:
            if on_chunk is not None:
                on_chunk(response_text)
            return response_text, True
        return "", False

    def _build_tool_summary_prompt(self, message: str, tool_name: str, payload: dict[str, Any]) -> str:
        payload_text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        return (
            f"{self.session.build_prompt(message)}\n\n"
            f"Tool executed: {tool_name}\n"
            f"Tool result:\n{payload_text}\n\n"
            "Summarize the result for the user in a concise, helpful way."
        )

    def _fallback_tool_summary(self, tool_name: str, payload: dict[str, Any]) -> str:
        if payload:
            return f"{tool_name} completed successfully: {json.dumps(payload, ensure_ascii=False, default=str)}"
        return f"{tool_name} completed successfully."

    def _format_available_tools(self) -> str:
        lines = ["Available tools:"]
        for metadata in self.tool_registry.list_tools():
            tags = f" [{', '.join(metadata.tags)}]" if metadata.tags else ""
            lines.append(f"- {metadata.name}: {metadata.description}{tags}")
        return "\n".join(lines)

    def _is_available_tools_request(self, message: str) -> bool:
        return _normalize_message(message) in {
            "what tools are available",
            "what tools are available?",
            "what tools are available now",
        }

    def _match_tool(self, message: str) -> str | None:
        normalized = _normalize_message(message)
        tokens = shlex.split(message)
        lower_tokens = [token.lower() for token in tokens]

        git_map = {
            "status": "git_status",
            "diff": "git_diff",
            "log": "git_log",
            "branch": "git_branch",
            "checkout": "git_checkout",
            "commit": "git_commit",
        }
        if lower_tokens and lower_tokens[0] == "git":
            if len(lower_tokens) > 1 and lower_tokens[1] in git_map:
                return git_map[lower_tokens[1]]
            if len(lower_tokens) > 1 and lower_tokens[1] == "push":
                return "terminal_execute"

        phrase_map = {
            "read_file": ("read file", "open file"),
            "write_file": ("write file", "save file"),
            "list_directory": ("list directory", "list files", "show files"),
            "search_files": ("search files", "find files"),
            "search_code": ("search code", "grep", "find code"),
            "git_status": ("git status",),
            "git_diff": ("git diff",),
            "git_log": ("git log",),
            "git_branch": ("git branch",),
            "git_checkout": ("git checkout",),
            "git_commit": ("git commit",),
        }

        for tool_name, phrases in phrase_map.items():
            if any(phrase in normalized for phrase in phrases):
                return tool_name

        for metadata in self.tool_registry.list_tools():
            name = metadata.name.lower()
            if name in normalized or name.replace("_", " ") in normalized:
                return metadata.name

        if lower_tokens and lower_tokens[0] in {"git", "python", "pip", "npm"}:
            return "terminal_execute"

        return None

    def _build_tool_parameters(self, tool_name: str, message: str) -> dict[str, Any]:
        tokens = shlex.split(message)
        key_values: dict[str, Any] = {}
        free_tokens: list[str] = []

        for token in tokens:
            if "=" in token:
                key, value = token.split("=", 1)
                key_values[key.lower()] = _coerce_value(value)
            else:
                free_tokens.append(token)

        defaults: dict[str, Any] = {}
        if tool_name in {"git_status", "git_diff", "git_log", "git_branch", "git_checkout", "git_commit"}:
            defaults["repo_path"] = str(self.default_workspace)
        if tool_name in {"read_file", "write_file", "list_directory", "search_files", "search_code"}:
            defaults["path"] = str(self.default_workspace)
        if tool_name == "terminal_execute":
            defaults["cwd"] = str(self.default_workspace)

        parameters = {**defaults, **key_values}

        if tool_name == "terminal_execute" and "command" not in parameters and free_tokens:
            parameters["command"] = free_tokens[0]
            parameters.setdefault("args", free_tokens[1:])

        if tool_name == "terminal_execute" and "args" not in parameters:
            parameters["args"] = free_tokens[1:] if free_tokens else []

        return parameters


__all__ = ["AgentController"]