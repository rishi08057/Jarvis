"""Agent registry for modular routing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import Agent


@dataclass(slots=True)
class AgentRegistry:
    """Register and resolve assistant agents by name."""

    _agents: dict[str, Agent] = field(default_factory=dict)

    def register(self, agent: Agent) -> None:
        self._agents[agent.name.lower()] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name.lower()]
        except KeyError as exc:
            raise KeyError(f"Agent '{name}' is not registered.") from exc

    def list_agents(self) -> list[str]:
        return sorted(self._agents)
