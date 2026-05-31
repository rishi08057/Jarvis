"""Tool execution and validation manager for Jarvis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from security import SecurityContext, SecurityMiddleware

from .base import Tool, ToolResult
from .registry import ToolRegistry


class ToolValidationError(ValueError):
    """Raised when tool input fails validation."""


@dataclass(slots=True)
class ToolManager:
    """Coordinate tool registration, discovery, validation, and execution."""

    registry: ToolRegistry = field(default_factory=ToolRegistry)
    security_middleware: SecurityMiddleware | None = None

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""

        self.registry.register(tool)

    def discover(self, package_name: str = "tools") -> None:
        """Discover tools from a package without changing this class."""

        self.registry.discover(package_name)

    def get(self, name: str) -> Tool:
        """Return a registered tool by name or alias."""

        return self.registry.get(name)

    def list_tools(self) -> list[str]:
        """Return the registered tool names."""

        return [metadata.name for metadata in self.registry.list_tools()]

    def execute(
        self,
        tool_name: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        context: SecurityContext | None = None,
    ) -> ToolResult:
        """Validate parameters and execute the selected tool."""

        tool = self.get(tool_name)
        validated_parameters = self._validate_parameters(tool.parameter_schema, dict(parameters or {}))
        security_context = context or SecurityContext()
        middleware = self._resolve_security_middleware()
        decision = middleware.authorize(
            tool_name=tool.name,
            risk_level=tool.metadata.risk_level,
            context=security_context,
            parameters=validated_parameters,
        )

        try:
            result = tool.execute(**validated_parameters)
        except Exception as exc:
            middleware.record_execution(
                tool_name=tool.name,
                risk_level=tool.metadata.risk_level,
                context=security_context,
                outcome="failure",
                details={"error": str(exc)},
            )
            raise

        middleware.record_execution(
            tool_name=tool.name,
            risk_level=tool.metadata.risk_level,
            context=security_context,
            outcome="success",
            details={"approved": decision.approved, "approver": decision.approver},
        )
        return result

    def _resolve_security_middleware(self) -> SecurityMiddleware:
        if self.security_middleware is None:
            from security import AuditLogger, LoggingAuditSink, PermissionManager

            self.security_middleware = SecurityMiddleware(
                permission_manager=PermissionManager(),
                audit_logger=AuditLogger((LoggingAuditSink(),)),
            )
        return self.security_middleware

    def _validate_parameters(self, schema: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        """Validate a JSON-schema-like parameter object."""

        if schema.get("type") not in {None, "object"}:
            raise ToolValidationError("Tool parameter schema must describe an object.")

        required = set(schema.get("required", []))
        missing = sorted(required - parameters.keys())
        if missing:
            raise ToolValidationError(f"Missing required parameters: {', '.join(missing)}")

        properties = schema.get("properties", {})
        additional_allowed = bool(schema.get("additionalProperties", False))
        if not additional_allowed:
            unexpected = sorted(set(parameters) - set(properties))
            if unexpected:
                raise ToolValidationError(f"Unexpected parameters: {', '.join(unexpected)}")

        for name, value in parameters.items():
            property_schema = properties.get(name)
            if property_schema is not None:
                self._validate_value(name, value, property_schema)

        return parameters

    def _validate_value(self, name: str, value: Any, schema: dict[str, Any]) -> None:
        expected_type = schema.get("type")
        if expected_type == "string" and not isinstance(value, str):
            raise ToolValidationError(f"Parameter '{name}' must be a string.")
        if expected_type == "integer" and not isinstance(value, int):
            raise ToolValidationError(f"Parameter '{name}' must be an integer.")
        if expected_type == "number" and not isinstance(value, (int, float)):
            raise ToolValidationError(f"Parameter '{name}' must be a number.")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise ToolValidationError(f"Parameter '{name}' must be a boolean.")
        if expected_type == "array" and not isinstance(value, list):
            raise ToolValidationError(f"Parameter '{name}' must be an array.")
        if expected_type == "object" and not isinstance(value, dict):
            raise ToolValidationError(f"Parameter '{name}' must be an object.")

        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise ToolValidationError(f"Parameter '{name}' must be one of: {', '.join(map(str, enum_values))}")