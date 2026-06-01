"""User interface entry points for Jarvis."""

from __future__ import annotations

from typing import Any

__all__ = ["ChatResponse", "ChatSession", "ConversationTurn", "TerminalChatApp", "run"]


def run(*args: Any, **kwargs: Any) -> Any:
    from .cli import run as cli_run

    return cli_run(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name in {"ChatResponse", "ChatSession", "ConversationTurn"}:
        from .session import ChatResponse, ChatSession, ConversationTurn

        mapping = {
            "ChatResponse": ChatResponse,
            "ChatSession": ChatSession,
            "ConversationTurn": ConversationTurn,
        }
        return mapping[name]

    if name == "TerminalChatApp":
        from .terminal import TerminalChatApp

        return TerminalChatApp

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
