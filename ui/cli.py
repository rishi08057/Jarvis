"""Command-line interface for Jarvis."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Sequence

from agents import AgentController
from config import AppSettings
from llm import LLMManager
from memory import MemoryManager
from security import PermissionManager
from tools import ToolRegistry

from .session import ChatSession
from .terminal import TerminalChatApp

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis local AI assistant")
    parser.add_argument("--show-config", action="store_true", help="Print the active configuration")
    parser.add_argument("--message", help="Send a single message and exit")
    return parser


def run(settings: AppSettings, argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.show_config:
        print(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False))
        return 0

    with MemoryManager(settings.memory_dir) as memory:
        llm = LLMManager(endpoint=settings.ai_endpoint, model=settings.ai_model)
        session = ChatSession(llm=llm)
        registry = ToolRegistry()
        registry.discover("tools")
        permission_manager = PermissionManager()
        controller = AgentController(
            session=session,
            llm=llm,
            tool_registry=registry,
            permission_manager=permission_manager,
            default_workspace=settings.project_root,
        )
        conversation = memory.conversations.create(title=f"{settings.assistant_name} terminal session")

        memory.set_preference("assistant_name", settings.assistant_name)
        memory.set_preference("ai_model", settings.ai_model)
        memory.set_preference("ai_provider", settings.ai_provider)
        memory.projects.upsert(
            str(settings.project_root),
            summary=f"Jarvis workspace rooted at {settings.project_root}",
            title=settings.app_name,
            metadata={"environment": settings.environment},
        )

        def record_turn(user_message: str, assistant_message: str | None, elapsed_seconds: float, success: bool) -> None:
            memory.conversations.append(
                conversation.conversation_id,
                "user",
                user_message,
                metadata={"role": "user", "success": success, "elapsed_seconds": elapsed_seconds},
            )
            if assistant_message is not None:
                memory.conversations.append(
                    conversation.conversation_id,
                    "assistant",
                    assistant_message,
                    metadata={"role": "assistant", "success": success, "elapsed_seconds": elapsed_seconds},
                )

        app = TerminalChatApp(
            session=session,
            controller=controller,
            assistant_name=settings.assistant_name,
            on_turn=record_turn,
        )

        if args.message:
            response = controller.handle(args.message)
            if response.message:
                print(response.message)
                print(f"Response time: {response.elapsed_seconds:.2f}s")
                record_turn(args.message, response.message, response.elapsed_seconds, response.success)
                return 0

            logger.error("LLM request failed: %s", response.error)
            print(f"{settings.assistant_name} could not generate a response: {response.error}")
            record_turn(args.message, None, response.elapsed_seconds, response.success)
            return 1

        memory.set_preference("last_ui_mode", "terminal-chat")
        return app.run()
