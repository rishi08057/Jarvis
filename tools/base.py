"""Base tool contracts and metadata primitives for Jarvis tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

JsonSchema = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    """Describes a tool exposed to the assistant runtime."""

    name: str
    description: str
    version: str = "1.0.0"
    parameters_schema: JsonSchema = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Standardized tool execution response."""

    success: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Base class for assistant tools."""

    metadata: ClassVar[ToolMetadata]

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def parameter_schema(self) -> JsonSchema:
        return self.metadata.parameters_schema

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool and return a structured result."""


def build_object_schema(
    *,
    properties: dict[str, JsonSchema] | None = None,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
    description: str | None = None,
) -> JsonSchema:
    """Build a JSON-schema-like object definition for tool parameters."""

    schema: JsonSchema = {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": additional_properties,
    }
    if description:
        schema["description"] = description
    return schema
