"""Command-line interface for Jarvis."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Sequence

from config import AppSettings
from memory import MemoryStore
from security import sanitize_prompt

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jarvis local AI assistant")
    parser.add_argument("--show-config", action="store_true", help="Print the active configuration")
    parser.add_argument("--message", help="Send a single message to the assistant shell")
    return parser


def run(settings: AppSettings, argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.show_config:
        print(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.message:
        message = sanitize_prompt(args.message)
        memory_store = MemoryStore(settings.memory_dir)
        memory_store.remember("last_user_message", message)
        logger.info("Captured prompt for future model integration")
        print(
            f"{settings.assistant_name} is initialized. "
            "Connect a local model adapter to handle live responses."
        )
        return 0

    parser.print_help()
    return 0
