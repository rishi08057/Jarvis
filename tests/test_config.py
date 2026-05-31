from __future__ import annotations

import unittest

from config import load_settings
from logs import configure_logging


class ConfigTests(unittest.TestCase):
    def test_load_settings_creates_runtime_directories(self) -> None:
        settings = load_settings()

        self.assertTrue(settings.logs_dir.exists())
        self.assertTrue(settings.memory_dir.exists())
        self.assertEqual(settings.app_name, "Jarvis")

    def test_configure_logging_attaches_handlers(self) -> None:
        settings = load_settings()
        logger = configure_logging(settings)

        self.assertEqual(logger.name, settings.app_name)
        self.assertGreaterEqual(len(logging_handlers := logger.parent.handlers), 1)
        self.assertIsInstance(logging_handlers[0].level, int)
