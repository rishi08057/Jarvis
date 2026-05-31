"""Git repository tools for Jarvis."""

from __future__ import annotations

import importlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from security import safe_join
from security.risk import RiskLevel

from .base import Tool, ToolMetadata, ToolResult, build_object_schema

logger = logging.getLogger("jarvis.security.audit")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_directory(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _default_approved_directories() -> tuple[Path, ...]:
    env_value = os.getenv("JARVIS_APPROVED_DIRECTORIES", "")
    if env_value.strip():
        return tuple(_normalize_directory(part) for part in env_value.split(os.pathsep) if part.strip())
    return (_project_root(),)


def _audit(tool_name: str, action: str, repo_path: Path, outcome: str, details: dict[str, Any] | None = None) -> None:
    payload = {
        "event_type": "git.access",
        "tool_name": tool_name,
        "action": action,
        "repo_path": str(repo_path),
        "outcome": outcome,
        "details": details or {},
    }
    logger.info("%s", json.dumps(payload, ensure_ascii=False))


def _git_module() -> Any:
    try:
        return importlib.import_module("git")
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("GitPython is required for git tools.") from exc


def _repo_error_types() -> tuple[type[BaseException], ...]:
    return (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError)


@dataclass(slots=True)
class GitToolBase(Tool):
    """Base class for repo-local Git tools."""

    approved_directories: tuple[Path, ...] = field(default_factory=_default_approved_directories)

    def _resolve_repo_path(self, repo_path: str) -> Path:
        candidate = Path(repo_path).expanduser()
        resolved = candidate.resolve()

        if candidate.is_absolute():
            if any(self._is_within_approved(resolved, approved) for approved in self.approved_directories):
                return resolved
        else:
            for approved in self.approved_directories:
                try:
                    return safe_join(approved, repo_path)
                except ValueError:
                    continue

        raise PermissionError(f"Path '{resolved}' is outside the approved directories.")

    def _is_within_approved(self, path: Path, approved: Path) -> bool:
        try:
            path.relative_to(approved)
            return True
        except ValueError:
            return False

    def _open_repo(self, repo_path: str):
        git = _git_module()
        resolved = self._resolve_repo_path(repo_path)
        try:
            return git.Repo(resolved)
        except _repo_error_types() as exc:
            raise RuntimeError(f"Unable to open git repository at '{resolved}': {exc}") from exc

    def _branch_name(self, repo: Any) -> str | None:
        try:
            return repo.active_branch.name
        except (AttributeError, ValueError):
            return None


@dataclass(slots=True)
class GitStatusTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_status",
        description="Show repository status.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={"repo_path": {"type": "string"}},
            required=("repo_path",),
        ),
        tags=("git", "status"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        _audit(self.name, "status", repo_path, "attempt")
        try:
            branch = self._branch_name(repo)
            status_text = repo.git.status("--short", "--branch")
            result = {
                "repo_path": str(repo_path),
                "branch": branch,
                "status": status_text,
                "is_dirty": repo.is_dirty(untracked_files=True),
                "untracked_files": list(repo.untracked_files),
            }
        except _repo_error_types() as exc:
            _audit(self.name, "status", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "status", repo_path, "success", {"branch": branch})
        return ToolResult(success=True, payload=result)


@dataclass(slots=True)
class GitDiffTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_diff",
        description="Show repository diff.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "repo_path": {"type": "string"},
                "cached": {"type": "boolean"},
                "paths": {"type": "array"},
            },
            required=("repo_path",),
        ),
        tags=("git", "diff"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        cached = bool(kwargs.get("cached", False))
        paths = kwargs.get("paths") or []
        _audit(self.name, "diff", repo_path, "attempt", {"cached": cached, "paths": paths})
        try:
            diff_args = ["--cached"] if cached else []
            diff_args.extend(paths)
            diff_text = repo.git.diff(*diff_args)
        except _repo_error_types() as exc:
            _audit(self.name, "diff", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "diff", repo_path, "success", {"cached": cached})
        return ToolResult(success=True, payload={"repo_path": str(repo_path), "cached": cached, "diff": diff_text})


@dataclass(slots=True)
class GitLogTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_log",
        description="Show commit history.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "repo_path": {"type": "string"},
                "max_count": {"type": "integer"},
            },
            required=("repo_path",),
        ),
        tags=("git", "log"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        max_count = int(kwargs.get("max_count", 10))
        _audit(self.name, "log", repo_path, "attempt", {"max_count": max_count})
        try:
            commits = []
            for commit in repo.iter_commits(max_count=max_count):
                commits.append(
                    {
                        "hexsha": commit.hexsha,
                        "summary": commit.summary,
                        "author": getattr(commit.author, "name", ""),
                        "authored_datetime": commit.authored_datetime.isoformat(),
                    }
                )
        except _repo_error_types() as exc:
            _audit(self.name, "log", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "log", repo_path, "success", {"commit_count": len(commits)})
        return ToolResult(success=True, payload={"repo_path": str(repo_path), "commits": commits})


@dataclass(slots=True)
class GitBranchTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_branch",
        description="List or create local branches.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "repo_path": {"type": "string"},
                "branch_name": {"type": "string"},
                "create": {"type": "boolean"},
            },
            required=("repo_path",),
        ),
        tags=("git", "branch"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        branch_name = kwargs.get("branch_name")
        create = bool(kwargs.get("create", False))
        _audit(self.name, "branch", repo_path, "attempt", {"branch_name": branch_name, "create": create})
        try:
            if create and branch_name:
                repo.git.branch(branch_name)
            branches = [head.name for head in repo.branches]
            current = self._branch_name(repo)
        except _repo_error_types() as exc:
            _audit(self.name, "branch", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "branch", repo_path, "success", {"branch_count": len(branches)})
        return ToolResult(success=True, payload={"repo_path": str(repo_path), "current_branch": current, "branches": branches})


@dataclass(slots=True)
class GitCheckoutTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_checkout",
        description="Switch branches or create and switch to a new branch.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "repo_path": {"type": "string"},
                "branch_name": {"type": "string"},
                "create_new": {"type": "boolean"},
            },
            required=("repo_path", "branch_name"),
        ),
        tags=("git", "checkout"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        branch_name = kwargs["branch_name"]
        create_new = bool(kwargs.get("create_new", False))
        _audit(self.name, "checkout", repo_path, "attempt", {"branch_name": branch_name, "create_new": create_new})
        try:
            if create_new:
                repo.git.checkout("-b", branch_name)
            else:
                repo.git.checkout(branch_name)
            current = self._branch_name(repo)
        except _repo_error_types() as exc:
            _audit(self.name, "checkout", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "checkout", repo_path, "success", {"current_branch": current})
        return ToolResult(success=True, payload={"repo_path": str(repo_path), "current_branch": current})


@dataclass(slots=True)
class GitCommitTool(GitToolBase):
    metadata = ToolMetadata(
        name="git_commit",
        description="Commit staged or selected changes.",
        risk_level=RiskLevel.HIGH,
        parameters_schema=build_object_schema(
            properties={
                "repo_path": {"type": "string"},
                "message": {"type": "string"},
                "all_changes": {"type": "boolean"},
                "paths": {"type": "array"},
                "author_name": {"type": "string"},
                "author_email": {"type": "string"},
            },
            required=("repo_path", "message"),
        ),
        tags=("git", "commit"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        git = _git_module()
        repo = self._open_repo(kwargs["repo_path"])
        repo_path = Path(repo.working_tree_dir)
        message = kwargs["message"]
        all_changes = bool(kwargs.get("all_changes", True))
        paths = kwargs.get("paths") or []
        author_name = kwargs.get("author_name") or "Jarvis"
        author_email = kwargs.get("author_email") or "jarvis@example.com"
        _audit(self.name, "commit", repo_path, "attempt", {"all_changes": all_changes, "paths": paths})
        try:
            if all_changes:
                repo.git.add(A=True)
            elif paths:
                repo.git.add(*paths)

            if repo.is_dirty(untracked_files=True) or repo.index.diff("HEAD") or repo.untracked_files:
                commit = repo.index.commit(message, author=git.Actor(author_name, author_email))
            else:
                raise RuntimeError("No changes to commit.")
        except _repo_error_types() as exc:
            _audit(self.name, "commit", repo_path, "failure", {"error": str(exc)})
            return ToolResult(success=False, message=str(exc), payload={"repo_path": str(repo_path)})

        _audit(self.name, "commit", repo_path, "success", {"commit": commit.hexsha})
        return ToolResult(success=True, payload={"repo_path": str(repo_path), "commit": commit.hexsha, "message": message})


__all__ = [
    "GitBranchTool",
    "GitCheckoutTool",
    "GitCommitTool",
    "GitDiffTool",
    "GitLogTool",
    "GitStatusTool",
]