"""Framework-neutral chat session state for Jarvis."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Iterator, Protocol


class SupportsLLMManager(Protocol):
    """Minimal interface required by the chat session."""

    last_error: str | None

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str | None:
        ...

    def stream_generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        ...


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A single item in the conversation history."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """Result of a chat exchange."""

    message: str | None
    elapsed_seconds: float
    success: bool
    error: str | None = None


@dataclass(slots=True)
class ChatSession:
    """Manage reusable conversation history and prompt assembly."""

    llm: SupportsLLMManager
    system_prompt: str = "You are Jarvis, a concise and helpful terminal assistant."
    max_turns: int = 12
    history: list[ConversationTurn] = field(default_factory=list)

    def clear(self) -> None:
        """Remove all conversation turns."""

        self.history.clear()

    def build_prompt(self, message: str) -> str:
        """Build a plain-text prompt from the current conversation state."""

        lines = [self.system_prompt, "", "Conversation:"]
        for turn in self._trimmed_history():
            label = "User" if turn.role == "user" else "Assistant"
            lines.append(f"{label}: {turn.content}")
        lines.append(f"User: {message}")
        lines.append("Assistant:")
        return "\n".join(lines)

    def stream_response(
        self,
        message: str,
        *,
        on_chunk: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        """Stream a response, update history, and return timing information."""

        prompt = self.build_prompt(message)
        self.history.append(ConversationTurn(role="user", content=message))

        start = perf_counter()
        chunks: list[str] = []
        for chunk in self.llm.stream_generate(prompt, system=self.system_prompt, timeout=timeout):
            if not chunk:
                continue
            chunks.append(chunk)
            if on_chunk is not None:
                on_chunk(chunk)

        elapsed_seconds = perf_counter() - start
        response_text = "".join(chunks)
        if response_text:
            self.history.append(ConversationTurn(role="assistant", content=response_text))
            return ChatResponse(message=response_text, elapsed_seconds=elapsed_seconds, success=True)

        return ChatResponse(
            message=None,
            elapsed_seconds=elapsed_seconds,
            success=False,
            error=self.llm.last_error or "No response was generated.",
        )

    def generate_response(self, message: str, *, timeout: float | None = None) -> ChatResponse:
        """Generate a non-streaming response, primarily for one-shot prompts."""

        prompt = self.build_prompt(message)
        self.history.append(ConversationTurn(role="user", content=message))

        start = perf_counter()
        response_text = self.llm.generate(prompt, system=self.system_prompt, timeout=timeout)
        elapsed_seconds = perf_counter() - start

        if response_text:
            self.history.append(ConversationTurn(role="assistant", content=response_text))
            return ChatResponse(message=response_text, elapsed_seconds=elapsed_seconds, success=True)

        return ChatResponse(
            message=None,
            elapsed_seconds=elapsed_seconds,
            success=False,
            error=self.llm.last_error or "No response was generated.",
        )

    def _trimmed_history(self) -> list[ConversationTurn]:
        if self.max_turns <= 0:
            return []
        return self.history[-self.max_turns * 2 :]