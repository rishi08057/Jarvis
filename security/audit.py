"""Audit logging for Jarvis security decisions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .risk import ApprovalDecision, SecurityContext


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Structured security audit event."""

    event_type: str
    tool_name: str
    actor_id: str
    outcome: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    risk_level: str = "LOW"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "actor_id": self.actor_id,
            "outcome": self.outcome,
            "timestamp": self.timestamp,
            "risk_level": self.risk_level,
            "details": self.details,
        }


class AuditSink(Protocol):
    """Destination for audit events."""

    def write(self, event: AuditEvent) -> None:
        """Persist an audit event."""


@dataclass(slots=True)
class JsonLinesAuditSink:
    """Write audit events to a JSONL file."""

    path: Path

    def write(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")


@dataclass(slots=True)
class LoggingAuditSink:
    """Send audit events to the application logger."""

    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("jarvis.security.audit"))

    def write(self, event: AuditEvent) -> None:
        self.logger.info("%s", json.dumps(event.to_dict(), ensure_ascii=False))


@dataclass(slots=True)
class AuditLogger:
    """Fan out audit events to one or more sinks."""

    sinks: tuple[AuditSink, ...] = ()

    def record(
        self,
        event_type: str,
        *,
        tool_name: str,
        context: SecurityContext,
        outcome: str,
        risk_level: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            tool_name=tool_name,
            actor_id=context.actor_id,
            outcome=outcome,
            risk_level=risk_level,
            details=details or {},
        )
        for sink in self.sinks:
            sink.write(event)
        return event

    def record_request(self, tool_name: str, context: SecurityContext, risk_level: str, details: dict[str, Any] | None = None) -> AuditEvent:
        return self.record("tool.request", tool_name=tool_name, context=context, outcome="requested", risk_level=risk_level, details=details)

    def record_approval(self, tool_name: str, context: SecurityContext, decision: ApprovalDecision, risk_level: str) -> AuditEvent:
        outcome = "approved" if decision.approved else "denied"
        details = {"approver": decision.approver, "reason": decision.reason}
        return self.record("tool.approval", tool_name=tool_name, context=context, outcome=outcome, risk_level=risk_level, details=details)

    def record_execution(self, tool_name: str, context: SecurityContext, risk_level: str, outcome: str, details: dict[str, Any] | None = None) -> AuditEvent:
        return self.record("tool.execution", tool_name=tool_name, context=context, outcome=outcome, risk_level=risk_level, details=details)
