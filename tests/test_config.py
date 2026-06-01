from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import load_settings
from logs import configure_logging


class ConfigTests(unittest.TestCase):
    def test_load_settings_creates_runtime_directories(self) -> None:
        settings = load_settings()

        self.assertTrue(settings.logs_dir.exists())
        self.assertTrue(settings.memory_dir.exists())
        self.assertEqual(settings.app_name, "Jarvis")
        self.assertFalse(settings.summarize_tool_results)

    def test_load_settings_reads_tool_summary_flag(self) -> None:
        with patch.dict(os.environ, {"JARVIS_SUMMARIZE_TOOL_RESULTS": "true"}, clear=False):
            settings = load_settings()

        self.assertTrue(settings.summarize_tool_results)

    def test_configure_logging_attaches_handlers(self) -> None:
        settings = load_settings()
        logger = configure_logging(settings)

        self.assertEqual(logger.name, settings.app_name)
        self.assertGreaterEqual(len(logging_handlers := logger.parent.handlers), 1)
        self.assertIsInstance(logging_handlers[0].level, int)
