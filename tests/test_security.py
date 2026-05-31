from __future__ import annotations

import unittest

from security import (
    ApprovalDecision,
    ApprovalWorkflow,
    AuditEvent,
    AuditLogger,
    PermissionDeniedError,
    PermissionManager,
    PermissionRule,
    RiskLevel,
    SecurityContext,
    SecurityMiddleware,
)
from tools import Tool, ToolManager, ToolMetadata, ToolResult, build_object_schema


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class AllowHighRiskWorkflow(ApprovalWorkflow):
    def request_approval(self, request: object) -> ApprovalDecision:
        return ApprovalDecision(approved=True, approver="security-team", reason="Approved for test.")


class SecurityLayerTests(unittest.TestCase):
    def test_permission_manager_denies_unauthorized_role(self) -> None:
        manager = PermissionManager()
        manager.register_rule(PermissionRule(tool_name="admin-tool", allowed_roles=("admin",), minimum_risk=RiskLevel.MEDIUM))

        with self.assertRaises(PermissionDeniedError):
            manager.authorize(
                tool_name="admin-tool",
                risk_level=RiskLevel.MEDIUM,
                context=SecurityContext(actor_id="user-1", roles=("user",)),
                parameters={},
            )

    def test_tool_execution_requires_permission_validation(self) -> None:
        class HighRiskTool(Tool):
            metadata = ToolMetadata(
                name="high-risk",
                description="High risk action.",
                risk_level=RiskLevel.HIGH,
                parameters_schema=build_object_schema(),
            )

            def execute(self, **kwargs: object) -> ToolResult:
                return ToolResult(success=True, payload={"status": "ok"})

        sink = InMemoryAuditSink()
        middleware = SecurityMiddleware(
            permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow()),
            audit_logger=AuditLogger((sink,)),
        )
        manager = ToolManager(security_middleware=middleware)
        manager.register(HighRiskTool())

        result = manager.execute("high-risk", context=SecurityContext(actor_id="admin-1", roles=("admin",)))

        self.assertTrue(result.success)
        self.assertEqual([event.event_type for event in sink.events], ["tool.request", "tool.approval", "tool.execution"])

    def test_high_risk_execution_is_denied_without_approval(self) -> None:
        class HighRiskTool(Tool):
            metadata = ToolMetadata(
                name="high-risk",
                description="High risk action.",
                risk_level=RiskLevel.HIGH,
                parameters_schema=build_object_schema(),
            )

            def execute(self, **kwargs: object) -> ToolResult:
                return ToolResult(success=True)

        manager = ToolManager(security_middleware=SecurityMiddleware(permission_manager=PermissionManager()))
        manager.register(HighRiskTool())

        with self.assertRaises(PermissionDeniedError):
            manager.execute("high-risk", context=SecurityContext(actor_id="user-1", roles=("user",)))


if __name__ == "__main__":
    unittest.main()