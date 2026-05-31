"""Permission validation and approval workflows for Jarvis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .risk import ApprovalDecision, ApprovalRequest, RiskLevel, SecurityContext


class PermissionDeniedError(PermissionError):
    """Raised when a tool execution is denied by policy."""


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """Permission rule associated with a tool or tool family."""

    tool_name: str
    allowed_roles: tuple[str, ...] = ()
    minimum_risk: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False


class ApprovalWorkflow(ABC):
    """Approval workflow abstraction for elevated tool execution."""

    @abstractmethod
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Return the approval decision for a request."""


@dataclass(slots=True)
class DefaultApprovalWorkflow(ApprovalWorkflow):
    """Simple policy-driven approval workflow."""

    approver_name: str = "system"
    auto_approve_roles: tuple[str, ...] = ("admin", "operator")

    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        if request.risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
            return ApprovalDecision(approved=True, approver=self.approver_name, reason="Automatically approved by policy.")

        if set(request.roles).intersection(self.auto_approve_roles):
            return ApprovalDecision(approved=True, approver=self.approver_name, reason="Approved for elevated role.")

        return ApprovalDecision(approved=False, approver=None, reason="High-risk actions require explicit approval.")


@dataclass(slots=True)
class PermissionManager:
    """Validate tool execution against risk and role-based rules."""

    rules: dict[str, PermissionRule] = field(default_factory=dict)
    approval_workflow: ApprovalWorkflow = field(default_factory=DefaultApprovalWorkflow)

    def register_rule(self, rule: PermissionRule) -> None:
        """Register a permission rule for a specific tool."""

        self.rules[rule.tool_name.lower()] = rule

    def authorize(
        self,
        *,
        tool_name: str,
        risk_level: RiskLevel,
        context: SecurityContext,
        parameters: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        """Validate a tool execution and return the approval decision."""

        rule = self.rules.get(tool_name.lower())
        if rule is not None:
            self._validate_rule(rule, risk_level=risk_level, context=context)

        if risk_level is RiskLevel.HIGH:
            request = ApprovalRequest(
                tool_name=tool_name,
                risk_level=risk_level,
                actor_id=context.actor_id,
                roles=context.roles,
                reason="High-risk tool execution requires approval.",
                parameters_summary=self._summarize_parameters(parameters or {}),
            )
            decision = self.approval_workflow.request_approval(request)
            if not decision.approved:
                raise PermissionDeniedError(decision.reason or "Tool execution denied.")
            return decision

        if rule is not None and rule.requires_approval:
            request = ApprovalRequest(
                tool_name=tool_name,
                risk_level=risk_level,
                actor_id=context.actor_id,
                roles=context.roles,
                reason="Policy requires approval.",
                parameters_summary=self._summarize_parameters(parameters or {}),
            )
            decision = self.approval_workflow.request_approval(request)
            if not decision.approved:
                raise PermissionDeniedError(decision.reason or "Tool execution denied.")
            return decision

        return ApprovalDecision(approved=True, approver=self._approver_name(), reason="Policy approved.")

    def _validate_rule(self, rule: PermissionRule, *, risk_level: RiskLevel, context: SecurityContext) -> None:
        if self._risk_rank(risk_level) < self._risk_rank(rule.minimum_risk):
            raise PermissionDeniedError(f"{rule.tool_name} does not permit risk level {risk_level.value}.")

        if rule.allowed_roles and not set(context.roles).intersection(rule.allowed_roles):
            raise PermissionDeniedError(f"{rule.tool_name} requires one of these roles: {', '.join(rule.allowed_roles)}")

    def _summarize_parameters(self, parameters: dict[str, Any]) -> str:
        summary = ", ".join(sorted(parameters))
        return summary[:200]

    def _approver_name(self) -> str:
        return getattr(self.approval_workflow, "approver_name", "system")

    def _risk_rank(self, risk_level: RiskLevel) -> int:
        ranks = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        return ranks[risk_level]
