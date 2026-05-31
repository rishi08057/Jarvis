from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from tools import ToolRegistry
from tools.filesystem import ListDirectoryTool, ReadFileTool, SearchCodeTool, SearchFilesTool, WriteFileTool


class FilesystemToolTests(unittest.TestCase):
    def test_registry_discovers_filesystem_tools(self) -> None:
        registry = ToolRegistry()
        registry.discover("tools")

        self.assertIsInstance(registry.get("read_file"), ReadFileTool)
        self.assertIsInstance(registry.get("write_file"), WriteFileTool)
        self.assertIsInstance(registry.get("list_directory"), ListDirectoryTool)
        self.assertIsInstance(registry.get("search_files"), SearchFilesTool)
        self.assertIsInstance(registry.get("search_code"), SearchCodeTool)

    def test_read_write_and_search_work_with_approved_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            writer = WriteFileTool(approved_directories=(root,))
            reader = ReadFileTool(approved_directories=(root,))
            lister = ListDirectoryTool(approved_directories=(root,))
            file_search = SearchFilesTool(approved_directories=(root,))
            code_search = SearchCodeTool(approved_directories=(root,))

            write_result = writer.execute(path="note.txt", content="hello jarvis\nsecond line")
            read_result = reader.execute(path="note.txt")
            list_result = lister.execute(path=".")
            file_matches = file_search.execute(path=".", pattern="*.txt")
            code_matches = code_search.execute(path=".", query="jarvis")

            self.assertTrue(write_result.success)
            self.assertIn("hello jarvis", read_result.payload["content"])
            self.assertIn("note.txt", list_result.payload["entries"])
            self.assertTrue(any(match.endswith("note.txt") for match in file_matches.payload["matches"]))
            self.assertEqual(code_matches.payload["matches"][0]["line"], 1)

    def test_path_traversal_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reader = ReadFileTool(approved_directories=(root,))

            with self.assertRaises(PermissionError):
                reader.execute(path="../outside.txt")

    def test_access_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            writer = WriteFileTool(approved_directories=(root,))
            logger = logging.getLogger("jarvis.security.audit")
            with self.assertLogs(logger, level="INFO") as captured:
                writer.execute(path="log.txt", content="data")

            self.assertTrue(any("filesystem.access" in entry for entry in captured.output))


if __name__ == "__main__":
    unittest.main()