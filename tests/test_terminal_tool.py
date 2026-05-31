from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from security import ApprovalDecision, ApprovalWorkflow, AuditEvent, AuditLogger, PermissionManager, SecurityContext, SecurityMiddleware
from tools import ToolManager, ToolRegistry
from tools.terminal import TerminalExecutionTool


class AllowHighRiskWorkflow(ApprovalWorkflow):
    def request_approval(self, request: object) -> ApprovalDecision:
        return ApprovalDecision(approved=True, approver="security-team", reason="Approved for test.")


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class TerminalExecutionToolTests(unittest.TestCase):
    def test_registry_discovers_terminal_tool(self) -> None:
        registry = ToolRegistry()
        registry.discover("tools")

        self.assertIsNotNone(registry.get("terminal_execute"))

    def test_allowed_python_command_runs_with_approval(self) -> None:
        sink = RecordingSink()
        manager = ToolManager(
            security_middleware=SecurityMiddleware(
                permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow()),
                audit_logger=AuditLogger((sink,)),
            )
        )
        manager.register(TerminalExecutionTool())

        result = manager.execute(
            "terminal_execute",
            {"command": "python", "args": ["-c", "print('hello from jarvis')"], "timeout_seconds": 10},
            context=SecurityContext(actor_id="admin-1", roles=("admin",)),
        )

        self.assertTrue(result.success)
        self.assertIn("hello from jarvis", result.payload["stdout"])
        self.assertEqual(result.payload["exit_code"], 0)
        self.assertGreaterEqual(len(sink.events), 3)

    def test_blocked_commands_are_rejected(self) -> None:
        manager = ToolManager(security_middleware=SecurityMiddleware(permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow())))
        manager.register(TerminalExecutionTool())

        with self.assertRaises(PermissionError):
            manager.execute(
                "terminal_execute",
                {"command": "rm", "args": ["-rf", "."]},
                context=SecurityContext(actor_id="admin-1", roles=("admin",)),
            )

    def test_git_push_is_explicitly_blocked(self) -> None:
        manager = ToolManager(security_middleware=SecurityMiddleware(permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow())))
        manager.register(TerminalExecutionTool())

        with self.assertRaises(PermissionError):
            manager.execute(
                "terminal_execute",
                {"command": "git", "args": ["push", "origin", "main"]},
                context=SecurityContext(actor_id="admin-1", roles=("admin",)),
            )

    def test_timeout_terminates_process(self) -> None:
        manager = ToolManager(security_middleware=SecurityMiddleware(permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow())))
        manager.register(TerminalExecutionTool())

        result = manager.execute(
            "terminal_execute",
            {"command": "python", "args": ["-c", "import time; time.sleep(2)"], "timeout_seconds": 0.2},
            context=SecurityContext(actor_id="admin-1", roles=("admin",)),
        )

        self.assertFalse(result.success)
        self.assertTrue(result.payload["timed_out"])
        self.assertNotEqual(result.payload["exit_code"], 0)

    def test_cwd_must_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            approved = Path(temp_dir)
            tool = TerminalExecutionTool(approved_directories=(approved,))

            with self.assertRaises(PermissionError):
                tool.execute(command="python", args=["-c", "print('x')"], cwd=str(approved.parent))


if __name__ == "__main__":
    unittest.main()