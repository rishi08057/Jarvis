from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from agents import AgentController
from security import ApprovalDecision, ApprovalWorkflow, PermissionManager, RiskLevel
from tools import Tool, ToolMetadata, ToolRegistry, ToolResult, build_object_schema
from tools.filesystem import ListDirectoryTool
from tools.repository_analysis import RepositoryAnalysisTool
from ui import ChatResponse, ChatSession


class FakeLLMManager:
    def __init__(self, *, stream_chunks: list[str] | None = None) -> None:
        self.stream_chunks = list(stream_chunks or [])
        self.prompts: list[str] = []
        self.last_error: str | None = None

    def stream_generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        _ = (system, model, options, timeout)
        self.prompts.append(prompt)
        for chunk in self.stream_chunks:
            yield chunk

    def generate(self, prompt: str, *, system: str | None = None, model: str | None = None, options=None, timeout=None):
        _ = (system, model, options, timeout)
        self.prompts.append(prompt)
        return "".join(self.stream_chunks)


class EchoTool(Tool):
    metadata = ToolMetadata(
        name="echo_demo",
        description="Echo a message.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={"message": {"type": "string"}},
            required=("message",),
        ),
    )

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(success=True, payload={"echo": kwargs["message"]})


class AllowHighRiskWorkflow(ApprovalWorkflow):
    def request_approval(self, request: object) -> ApprovalDecision:
        return ApprovalDecision(approved=True, approver="security-team", reason="Approved for test.")


class FakeController:
    def __init__(self) -> None:
        self.session = ChatSession(llm=FakeLLMManager())
        self.calls: list[str] = []

    def handle(self, message: str, *, on_chunk=None, timeout=None):
        _ = timeout
        self.calls.append(message)
        if on_chunk is not None:
            on_chunk("controller-response")
        return ChatResponse(message="controller-response", elapsed_seconds=0.01, success=True)

    def clear_history(self) -> None:
        self.session.clear()


class AgentControllerTests(unittest.TestCase):
    def test_available_tools_command_lists_registered_tools(self) -> None:
        llm = FakeLLMManager(stream_chunks=["unused"])
        registry = ToolRegistry()
        registry.discover("tools")
        controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry)

        response = controller.handle("What tools are available?")

        self.assertTrue(response.success)
        self.assertIn("git_status", response.message or "")
        self.assertIn("terminal_execute", response.message or "")
        self.assertEqual(llm.prompts, [])

    def test_tool_request_routes_through_registry_and_summarizes(self) -> None:
        llm = FakeLLMManager(stream_chunks=["The tool ran successfully."])
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register(tool)
        controller = AgentController(
            session=ChatSession(llm=llm),
            llm=llm,
            tool_registry=registry,
            permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow()),
        )

        response = controller.handle("echo_demo message=hello")

        self.assertTrue(response.success)
        self.assertEqual(response.message, "The tool ran successfully.")
        self.assertEqual(tool.calls[0]["message"], "hello")
        self.assertGreaterEqual(len(llm.prompts), 1)

    def test_list_directory_returns_direct_result_without_llm(self) -> None:
        llm = FakeLLMManager(stream_chunks=["unused"])
        registry = ToolRegistry()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("hello jarvis", encoding="utf-8")
            registry.register(ListDirectoryTool(approved_directories=(root,)))
            controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry, default_workspace=root)

            response = controller.handle("list directory")

        self.assertTrue(response.success)
        self.assertEqual(llm.prompts, [])
        self.assertIn("notes.txt", response.message or "")

    def test_explicit_summary_request_invokes_llm_for_direct_tool(self) -> None:
        llm = FakeLLMManager(stream_chunks=["Summarized listing."])
        registry = ToolRegistry()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("hello jarvis", encoding="utf-8")
            registry.register(ListDirectoryTool(approved_directories=(root,)))
            controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry, default_workspace=root)

            response = controller.handle("summarize the directory listing")

        self.assertTrue(response.success)
        self.assertEqual(response.message, "Summarized listing.")
        self.assertGreaterEqual(len(llm.prompts), 1)

    def test_tool_request_reports_elapsed_time_for_entire_request(self) -> None:
        llm = FakeLLMManager(stream_chunks=["The tool ran successfully."])
        registry = ToolRegistry()
        registry.register(EchoTool())
        controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry)

        with patch("agents.controller.perf_counter", side_effect=[5.0, 5.42]):
            response = controller.handle("echo_demo message=hello")

        self.assertTrue(response.success)
        self.assertAlmostEqual(response.elapsed_seconds, 0.42, places=2)

    def test_llm_request_reports_elapsed_time_for_each_message(self) -> None:
        llm = FakeLLMManager(stream_chunks=["Fallback answer."])
        registry = ToolRegistry()
        controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry)

        with patch("agents.controller.perf_counter", side_effect=[9.0, 9.33]):
            response = controller.handle("Tell me something unrelated.")

        self.assertTrue(response.success)
        self.assertAlmostEqual(response.elapsed_seconds, 0.33, places=2)

    def test_repository_analysis_request_routes_to_tool(self) -> None:
        llm = FakeLLMManager(stream_chunks=["Repository summary."])
        registry = ToolRegistry()
        tool = RepositoryAnalysisTool()
        registry.register(tool)
        controller = AgentController(
            session=ChatSession(llm=llm),
            llm=llm,
            tool_registry=registry,
        )

        response = controller.handle("analyze repository path=d:/jarvis")

        self.assertTrue(response.success)
        self.assertEqual(response.message, "Repository summary.")
        self.assertGreaterEqual(len(llm.prompts), 1)

    def test_fallback_to_llm_when_no_tool_matches(self) -> None:
        llm = FakeLLMManager(stream_chunks=["Fallback answer."])
        registry = ToolRegistry()
        controller = AgentController(session=ChatSession(llm=llm), llm=llm, tool_registry=registry)

        response = controller.handle("Tell me something unrelated.")

        self.assertTrue(response.success)
        self.assertEqual(response.message, "Fallback answer.")
        self.assertIn("Tell me something unrelated.", llm.prompts[0])

    def test_terminal_chat_app_uses_controller_path(self) -> None:
        from ui import TerminalChatApp

        controller = FakeController()

        class Console:
            def __init__(self) -> None:
                self.inputs = ["What tools are available?", "exit"]
                self.printed: list[str] = []
                self.cleared = 0

            def input(self, prompt: str) -> str:
                _ = prompt
                return self.inputs.pop(0)

            def print(self, *values, **kwargs) -> None:
                _ = kwargs
                self.printed.append(" ".join(str(value) for value in values))

            def clear(self) -> None:
                self.cleared += 1

        app = TerminalChatApp(session=controller.session, controller=cast(AgentController, controller), console=Console())

        exit_code = app.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(controller.calls, ["What tools are available?"])


if __name__ == "__main__":
    unittest.main()