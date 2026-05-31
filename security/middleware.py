"""Security middleware that gates tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLogger, LoggingAuditSink
from .permissions import PermissionManager
from .risk import ApprovalDecision, RiskLevel, SecurityContext


@dataclass(slots=True)
class SecurityMiddleware:
    """Coordinate permission checks, approval, and audit logging."""

    permission_manager: PermissionManager
    audit_logger: AuditLogger = field(default_factory=lambda: AuditLogger((LoggingAuditSink(),)))

    def authorize(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        context: SecurityContext,
        parameters: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        """Run the permission workflow and persist audit events."""

        self.audit_logger.record_request(tool_name, context, risk_level.value, {"parameters": sorted((parameters or {}).keys())})
        decision = self.permission_manager.authorize(
            tool_name=tool_name,
            risk_level=risk_level,
            context=context,
            parameters=parameters,
        )
        self.audit_logger.record_approval(tool_name, context, decision, risk_level.value)
        return decision

    def record_execution(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        context: SecurityContext,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record execution outcomes after the tool runs."""

        self.audit_logger.record_execution(tool_name, context, risk_level.value, outcome, details)
