"""Security risk levels and execution context models for Jarvis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """Risk classification for tool execution."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Represents the caller and environment for a tool execution."""

    actor_id: str = "anonymous"
    roles: tuple[str, ...] = ()
    session_id: str | None = None
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Security approval request for an elevated action."""

    tool_name: str
    risk_level: RiskLevel
    actor_id: str
    reason: str
    roles: tuple[str, ...] = ()
    parameters_summary: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Result of evaluating an approval request."""

    approved: bool
    approver: str | None = None
    reason: str = ""
