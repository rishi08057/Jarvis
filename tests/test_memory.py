from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import MemoryManager


class MemoryManagerTests(unittest.TestCase):
    def test_schema_is_created_and_preferences_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with MemoryManager(Path(temp_dir)) as manager:
                self.assertTrue(manager.db_path.exists())

                entry = manager.set_preference("theme", "terminal")
                self.assertEqual(entry.preference_key, "theme")
                self.assertEqual(manager.get_preference("theme"), "terminal")

    def test_conversations_are_stored_and_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with MemoryManager(Path(temp_dir)) as manager:
                conversation = manager.conversations.create(title="Daily chat")
                manager.conversations.append(conversation.conversation_id, "user", "Remember the deployment note", metadata={"tag": "ops"})
                manager.conversations.append(conversation.conversation_id, "assistant", "Deployment note stored", metadata={"tag": "ops"})

                messages = manager.conversations.list_messages(conversation.conversation_id)
                results = manager.search("deployment")

                self.assertEqual(len(messages), 2)
                self.assertEqual(messages[0].role, "user")
                self.assertEqual(results[0].source_type, "conversation_message")

    def test_project_context_is_upserted_and_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with MemoryManager(Path(temp_dir)) as manager:
                context = manager.projects.upsert("D:/jarvis", "Jarvis local workspace", title="Jarvis", metadata={"branch": "main"})

                results = manager.projects.search("workspace")

                self.assertEqual(context.project_path, "D:/jarvis")
                self.assertEqual(results[0].source_type, "project_context")
                self.assertIn("workspace", results[0].body)

    def test_search_spans_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with MemoryManager(Path(temp_dir)) as manager:
                manager.set_preference("assistant_name", "Jarvis")

                results = manager.search("Jarvis")

                self.assertEqual(results[0].source_type, "preference")
                self.assertEqual(results[0].source_id, "assistant_name")


if __name__ == "__main__":
    unittest.main()