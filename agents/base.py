"""Base agent contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Input context passed to an agent."""

    message: str
    metadata: dict[str, str] = field(default_factory=dict)


class Agent(ABC):
    """Base class for assistant agents."""

    name: str
    description: str

    @abstractmethod
    def handle(self, context: AgentContext) -> str:
        """Process a request and return a response."""


