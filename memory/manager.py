"""SQLite-backed local memory system for Jarvis."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


def _escape_like(query: str) -> str:
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: str
    title: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class ProjectContext:
    project_path: str
    title: str | None
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class PreferenceEntry:
    preference_key: str
    preference_value: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    source_type: str
    source_id: str
    title: str | None
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


class MemoryManager:
    """Coordinate SQLite storage, migrations, and cross-memory search."""

    def __init__(self, memory_dir: Path, database_name: str = "jarvis.sqlite3") -> None:
        self._memory_dir = memory_dir
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._memory_dir / database_name
        self._connection = sqlite3.connect(self._db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        self._apply_migrations()
        self.conversations = ConversationStore(self)
        self.projects = ProjectStore(self)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MemoryManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def set_preference(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> PreferenceEntry:
        now = _now()
        self._connection.execute(
            """
            INSERT INTO preferences (preference_key, preference_value, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, COALESCE((SELECT created_at FROM preferences WHERE preference_key = ?), ?), ?)
            ON CONFLICT(preference_key) DO UPDATE SET
                preference_value = excluded.preference_value,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (key, value, _json_dump(metadata), key, now, now),
        )
        self._upsert_search_index(
            source_type="preference",
            source_id=key,
            title=key,
            body=f"{key}: {value}",
            metadata=metadata or {},
            updated_at=now,
        )
        self._connection.commit()
        return self.get_preference_entry(key)

    def get_preference(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT preference_value FROM preferences WHERE preference_key = ?",
            (key,),
        ).fetchone()
        return None if row is None else row["preference_value"]

    def get_preference_entry(self, key: str) -> PreferenceEntry:
        row = self._connection.execute(
            "SELECT preference_key, preference_value, metadata_json, created_at, updated_at FROM preferences WHERE preference_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise KeyError(key)
        return PreferenceEntry(
            preference_key=row["preference_key"],
            preference_value=row["preference_value"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_preferences(self) -> list[PreferenceEntry]:
        rows = self._connection.execute(
            "SELECT preference_key, preference_value, metadata_json, created_at, updated_at FROM preferences ORDER BY preference_key",
        ).fetchall()
        return [
            PreferenceEntry(
                preference_key=row["preference_key"],
                preference_value=row["preference_value"],
                metadata=_json_load(row["metadata_json"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def search(self, query: str, *, limit: int = 10, source_types: Iterable[str] | None = None) -> list[MemorySearchResult]:
        pattern = f"%{_escape_like(query.lower())}%"
        sql = """
            SELECT source_type, source_id, title, body, metadata_json, updated_at
            FROM memory_search_index
            WHERE (
                lower(title) LIKE ? ESCAPE '\\'
                OR lower(body) LIKE ? ESCAPE '\\'
                OR lower(metadata_json) LIKE ? ESCAPE '\\'
            )
        """
        parameters: list[Any] = [pattern, pattern, pattern]
        if source_types:
            types = tuple(source_types)
            placeholders = ", ".join("?" for _ in types)
            sql += f" AND source_type IN ({placeholders})"
            parameters.extend(types)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        rows = self._connection.execute(sql, parameters).fetchall()
        return [
            MemorySearchResult(
                source_type=row["source_type"],
                source_id=row["source_id"],
                title=row["title"],
                body=row["body"],
                metadata=_json_load(row["metadata_json"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def upsert_search_index(
        self,
        *,
        source_type: str,
        source_id: str,
        title: str | None,
        body: str,
        metadata: dict[str, Any],
        updated_at: str,
    ) -> None:
        self._upsert_search_index(
            source_type=source_type,
            source_id=source_id,
            title=title,
            body=body,
            metadata=metadata,
            updated_at=updated_at,
        )

    def remember(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> PreferenceEntry:
        """Compatibility helper used by the existing CLI."""

        return self.set_preference(key, value, metadata)

    def _apply_migrations(self) -> None:
        migrations_dir = Path(__file__).with_name("migrations")
        applied_versions = {
            row["version"]
            for row in self._connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            version = int(migration_file.stem.split("_", 1)[0])
            if version in applied_versions:
                continue
            self._connection.executescript(migration_file.read_text(encoding="utf-8"))
            self._connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, migration_file.name, _now()),
            )
            self._connection.commit()

    def _upsert_search_index(
        self,
        *,
        source_type: str,
        source_id: str,
        title: str | None,
        body: str,
        metadata: dict[str, Any],
        updated_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_search_index (source_type, source_id, title, body, metadata_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_id) DO UPDATE SET
                title = excluded.title,
                body = excluded.body,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (source_type, source_id, title, body, _json_dump(metadata), updated_at),
        )


class ConversationStore:
    """Store and retrieve conversation threads and messages."""

    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager

    def create(self, title: str | None = None, metadata: dict[str, Any] | None = None) -> ConversationRecord:
        conversation_id = uuid4().hex
        now = _now()
        self._manager.connection.execute(
            """
            INSERT INTO conversations (conversation_id, title, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, title, _json_dump(metadata), now, now),
        )
        self._manager.connection.commit()
        return ConversationRecord(conversation_id=conversation_id, title=title, metadata=metadata or {}, created_at=now, updated_at=now)

    def append(self, conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> ConversationMessage:
        message_id = uuid4().hex
        now = _now()
        self._manager.connection.execute(
            """
            INSERT INTO conversation_messages (message_id, conversation_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content, _json_dump(metadata), now),
        )
        self._manager.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )
        self._manager.upsert_search_index(
            source_type="conversation_message",
            source_id=message_id,
            title=role,
            body=content,
            metadata={"conversation_id": conversation_id, "role": role, **(metadata or {})},
            updated_at=now,
        )
        self._manager.connection.commit()
        return ConversationMessage(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=now,
        )

    def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        rows = self._manager.connection.execute(
            """
            SELECT message_id, conversation_id, role, content, metadata_json, created_at
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY created_at, message_id
            """,
            (conversation_id,),
        ).fetchall()
        return [
            ConversationMessage(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"],
                metadata=_json_load(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get(self, conversation_id: str) -> ConversationRecord | None:
        row = self._manager.connection.execute(
            "SELECT conversation_id, title, metadata_json, created_at, updated_at FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversationRecord(
            conversation_id=row["conversation_id"],
            title=row["title"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def search(self, query: str, *, limit: int = 10) -> list[MemorySearchResult]:
        return self._manager.search(query, limit=limit, source_types=("conversation_message",))


class ProjectStore:
    """Store and retrieve project-level context snapshots."""

    def __init__(self, manager: MemoryManager) -> None:
        self._manager = manager

    def upsert(
        self,
        project_path: str,
        summary: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectContext:
        now = _now()
        self._manager.connection.execute(
            """
            INSERT INTO project_context (project_path, title, summary, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM project_context WHERE project_path = ?), ?), ?)
            ON CONFLICT(project_path) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (project_path, title, summary, _json_dump(metadata), project_path, now, now),
        )
        self._manager.upsert_search_index(
            source_type="project_context",
            source_id=project_path,
            title=title,
            body=summary,
            metadata={"project_path": project_path, **(metadata or {})},
            updated_at=now,
        )
        self._manager.connection.commit()
        return self.get(project_path) or ProjectContext(project_path=project_path, title=title, summary=summary, metadata=metadata or {}, created_at=now, updated_at=now)

    def get(self, project_path: str) -> ProjectContext | None:
        row = self._manager.connection.execute(
            "SELECT project_path, title, summary, metadata_json, created_at, updated_at FROM project_context WHERE project_path = ?",
            (project_path,),
        ).fetchone()
        if row is None:
            return None
        return ProjectContext(
            project_path=row["project_path"],
            title=row["title"],
            summary=row["summary"],
            metadata=_json_load(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def search(self, query: str, *, limit: int = 10) -> list[MemorySearchResult]:
        return self._manager.search(query, limit=limit, source_types=("project_context",))


__all__ = [
    "ConversationMessage",
    "ConversationRecord",
    "ConversationStore",
    "MemoryManager",
    "MemorySearchResult",
    "PreferenceEntry",
    "ProjectContext",
    "ProjectStore",
]