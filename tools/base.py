"""Base tool contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Standardized tool execution response."""

    success: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Base class for assistant tools."""

    name: str
    description: str

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool and return a structured result."""
