from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools import Tool, ToolManager, ToolMetadata, ToolRegistry, ToolResult, build_object_schema
from tools.repository_analysis import RepositoryAnalysisTool


class ToolFrameworkTests(unittest.TestCase):
    def test_registry_registers_aliases_and_executes(self) -> None:
        class EchoTool(Tool):
            metadata = ToolMetadata(
                name="echo",
                description="Echo a message.",
                parameters_schema=build_object_schema(
                    properties={"message": {"type": "string"}},
                    required=("message",),
                ),
                aliases=("say",),
            )

            def execute(self, **kwargs: object) -> ToolResult:
                return ToolResult(success=True, payload={"echo": kwargs["message"]})

        manager = ToolManager()
        manager.register(EchoTool())

        result = manager.execute("say", {"message": "hello"})

        self.assertTrue(result.success)
        self.assertEqual(result.payload["echo"], "hello")

    def test_schema_validation_rejects_invalid_input(self) -> None:
        class EchoTool(Tool):
            metadata = ToolMetadata(
                name="echo",
                description="Echo a message.",
                parameters_schema=build_object_schema(
                    properties={"message": {"type": "string"}},
                    required=("message",),
                ),
            )

            def execute(self, **kwargs: object) -> ToolResult:
                return ToolResult(success=True)

        manager = ToolManager()
        manager.register(EchoTool())

        with self.assertRaises(Exception):
            manager.execute("echo", {"message": 123})

    def test_discovery_loads_tools_from_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "sample_tools"
            package_root.mkdir()
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "sample.py").write_text(
                textwrap.dedent(
                    '''
                    from tools import Tool, ToolMetadata, ToolResult, build_object_schema


                    class PingTool(Tool):
                        metadata = ToolMetadata(
                            name="ping",
                            description="Return pong.",
                            parameters_schema=build_object_schema(),
                        )

                        def execute(self, **kwargs: object) -> ToolResult:
                            return ToolResult(success=True, payload={"response": "pong"})
                    '''
                ),
                encoding="utf-8",
            )

            sys.path.insert(0, temp_dir)
            try:
                registry = ToolRegistry()
                registry.discover("sample_tools")

                self.assertEqual(registry.get("ping").execute().payload["response"], "pong")
            finally:
                sys.path.remove(temp_dir)

    def test_repository_analysis_reports_project_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app").mkdir()
            (root / "app" / "main.py").write_text(
                """
# TODO: add CLI command support
from fastapi import FastAPI

app = FastAPI()
""".strip(),
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("fastapi>=0.115\nrich>=13.7.1\n", encoding="utf-8")
            (root / "README.md").write_text("Project notes\n", encoding="utf-8")

            tool = RepositoryAnalysisTool(approved_directories=(root,))
            result = tool.execute(path=".")

            self.assertTrue(result.success)
            self.assertIn("Repository analysis for", result.message)
            self.assertTrue(any(item["name"] == "Python" for item in result.payload["languages"]))
            self.assertTrue(any(item["name"] == "FastAPI" for item in result.payload["frameworks"]))
            self.assertEqual(result.payload["summary"]["todo_count"], 1)
            self.assertTrue(any(dependency["name"] == "fastapi" for dependency in result.payload["dependencies"]))


if __name__ == "__main__":
    unittest.main()