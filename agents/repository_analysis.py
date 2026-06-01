"""Repository analysis agent for Jarvis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import Agent, AgentContext
from tools import ToolManager


@dataclass(slots=True)
class RepositoryAnalysisAgent(Agent):
    """Run the repository analysis tool and return a readable report."""

    name: str = "repository_analysis"
    description: str = "Analyze a repository and summarize languages, frameworks, TODOs, dependencies, and structure."
    tool_manager: ToolManager = field(default_factory=ToolManager, repr=False)

    def handle(self, context: AgentContext) -> str:
        path = context.metadata.get("path") or context.message.strip()
        if not path:
            return "Repository analysis requires a repository path."

        result = self.tool_manager.execute("repository_analysis", {"path": path})
        if not result.success:
            return result.message or "Repository analysis failed."

        return "\n\n".join(
            [
                result.message,
                json.dumps(result.payload, indent=2, ensure_ascii=False, default=str),
            ],
        )


__all__ = ["RepositoryAnalysisAgent"]