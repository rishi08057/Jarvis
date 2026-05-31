"""Simple file-backed memory store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """A single stored memory record."""

    key: str
    value: str
    metadata: dict[str, str] = field(default_factory=dict)


class MemoryStore:
    """Persist assistant memories as JSON on disk."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._path = root / "memory.json"
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[MemoryEntry]:
        if not self._path.exists():
            return []
        raw_entries = json.loads(self._path.read_text(encoding="utf-8"))
        return [MemoryEntry(**entry) for entry in raw_entries]

    def save(self, entries: list[MemoryEntry]) -> None:
        payload = [asdict(entry) for entry in entries]
        self._path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def remember(self, key: str, value: str, metadata: dict[str, str] | None = None) -> MemoryEntry:
        entry = MemoryEntry(key=key, value=value, metadata=metadata or {})
        entries = self.load()
        entries = [item for item in entries if item.key != key]
        entries.append(entry)
        self.save(entries)
        return entry
