"""Command-line interface for Jarvis."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Sequence

from config import AppSettings
from llm import LLMManager
from memory import MemoryStore

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

    memory_store = MemoryStore(settings.memory_dir)
    llm = LLMManager(endpoint=settings.ai_endpoint, model=settings.ai_model)
    session = ChatSession(llm=llm)
    app = TerminalChatApp(session=session, assistant_name=settings.assistant_name)

    if args.message:
        memory_store.remember("last_user_message", args.message)
        response = session.stream_response(args.message)
        if response.message:
            print(response.message)
            print(f"Response time: {response.elapsed_seconds:.2f}s")
            return 0

        logger.error("LLM request failed: %s", response.error)
        print(f"{settings.assistant_name} could not generate a response: {response.error}")
        return 1

    memory_store.remember("last_ui_mode", "terminal-chat")
    return app.run()
