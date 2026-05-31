"""Jarvis application entrypoint."""

from __future__ import annotations

from config import load_settings
from logs import configure_logging
from ui import run


def main() -> int:
    settings = load_settings()
    configure_logging(settings)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
