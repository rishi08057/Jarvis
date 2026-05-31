"""Compatibility wrapper for the SQLite-backed memory system."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .manager import MemoryManager


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """A single stored memory record."""

    key: str
    value: str
    metadata: dict[str, str] = field(default_factory=dict)


class MemoryStore:
    """Persist assistant memories using SQLite preferences."""

    def __init__(self, root: Path) -> None:
        self._manager = MemoryManager(root)

    @property
    def path(self) -> Path:
        return self._manager.db_path

    def load(self) -> list[MemoryEntry]:
        return [
            MemoryEntry(key=entry.preference_key, value=entry.preference_value, metadata={str(key): str(value) for key, value in entry.metadata.items()})
            for entry in self._manager.list_preferences()
        ]

    def save(self, entries: list[MemoryEntry]) -> None:
        for entry in entries:
            self._manager.set_preference(entry.key, entry.value, metadata=entry.metadata)

    def remember(self, key: str, value: str, metadata: dict[str, str] | None = None) -> MemoryEntry:
        entry = self._manager.set_preference(key, value, metadata=metadata)
        return MemoryEntry(key=entry.preference_key, value=entry.preference_value, metadata={str(k): str(v) for k, v in entry.metadata.items()})
