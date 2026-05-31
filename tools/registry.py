"""Tool registry and discovery utilities for Jarvis."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field

from .base import Tool, ToolMetadata


@dataclass(slots=True)
class ToolRegistry:
    """Register, resolve, and discover assistant tools."""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """Register a tool instance and any aliases it exposes."""

        self._tools[tool.name.lower()] = tool
        for alias in tool.metadata.aliases:
            self._tools[alias.lower()] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry if it exists."""

        self._tools.pop(name.lower(), None)

    def get(self, name: str) -> Tool:
        """Resolve a tool by name or alias."""

        try:
            return self._tools[name.lower()]
        except KeyError as exc:
            raise KeyError(f"Tool '{name}' is not registered.") from exc

    def list_tools(self) -> list[ToolMetadata]:
        """Return unique tool metadata entries sorted by tool name."""

        unique: dict[str, Tool] = {}
        for tool in self._tools.values():
            unique[tool.name.lower()] = tool
        return [unique[name].metadata for name in sorted(unique)]

    def discover(self, package_name: str) -> None:
        """Import all modules inside a package and register tool subclasses."""

        package = importlib.import_module(package_name)
        for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
            module = importlib.import_module(module_info.name)
            self._register_tools_from_module(module)

    def _register_tools_from_module(self, module: object) -> None:
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate is Tool or not issubclass(candidate, Tool):
                continue
            if inspect.isabstract(candidate):
                continue
            if hasattr(candidate, "metadata"):
                self.register(candidate())