from __future__ import annotations

import tempfile
import types
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from security import ApprovalDecision, ApprovalWorkflow, AuditEvent, AuditLogger, PermissionManager, SecurityContext, SecurityMiddleware
from tools import ToolManager, ToolRegistry


@dataclass
class FakeCommit:
    hexsha: str = "abc123"
    summary: str = "Initial commit"
    authored_datetime: datetime = datetime(2026, 6, 1, tzinfo=timezone.utc)

    @property
    def author(self):
        return types.SimpleNamespace(name="Jarvis")


class FakeActor:
    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email


class FakeGit:
    def __init__(self, repo: "FakeRepo") -> None:
        self.repo = repo

    def status(self, *_args):
        return "## main\n M changed.py\n?? new.txt"

    def diff(self, *_args):
        return "diff --git a/changed.py b/changed.py"

    def checkout(self, *args):
        if args[:1] == ("-b",):
            self.repo.current_branch = args[1]
        else:
            self.repo.current_branch = args[0]

    def branch(self, branch_name: str):
        if branch_name not in self.repo.branch_names:
            self.repo.branch_names.append(branch_name)

    def add(self, *_args, **_kwargs):
        self.repo.add_called = True


class FakeIndex:
    def __init__(self, repo: "FakeRepo") -> None:
        self.repo = repo

    def commit(self, message: str, author: FakeActor):
        self.repo.commits.append((message, author))
        return FakeCommit(hexsha="deadbeef", summary=message)

    def diff(self, _ref: str):
        return ["changed"] if self.repo.has_changes else []


class FakeRepo:
    def __init__(self, path: Path) -> None:
        self.working_tree_dir = str(path)
        self.current_branch = "main"
        self.branch_names = ["main"]
        self.untracked_files = ["new.txt"]
        self.has_changes = True
        self.add_called = False
        self.commits: list[tuple[str, FakeActor]] = []
        self.git = FakeGit(self)
        self.index = FakeIndex(self)

    def is_dirty(self, _untracked_files: bool = False, **_kwargs) -> bool:
        return self.has_changes

    def iter_commits(self, _max_count: int = 10, **_kwargs):
        return [FakeCommit()]

    @property
    def active_branch(self):
        return types.SimpleNamespace(name=self.current_branch)

    @property
    def branches(self):
        return [types.SimpleNamespace(name=name) for name in self.branch_names]


class AllowHighRiskWorkflow(ApprovalWorkflow):
    def request_approval(self, request: object) -> ApprovalDecision:
        return ApprovalDecision(approved=True, approver="security-team", reason="Approved for test.")


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class GitToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self.fake_git_module = types.SimpleNamespace(Repo=lambda path: FakeRepo(Path(path)), Actor=FakeActor)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_registry_discovers_git_tools(self) -> None:
        registry = ToolRegistry()
        registry.discover("tools")

        self.assertIsNotNone(registry.get("git_status"))
        self.assertIsNotNone(registry.get("git_commit"))

    def test_git_tools_require_approval_and_report_results(self) -> None:
        from tools.git_tools import GitCommitTool, GitStatusTool

        sink = RecordingSink()
        manager = ToolManager(
            security_middleware=SecurityMiddleware(
                permission_manager=PermissionManager(approval_workflow=AllowHighRiskWorkflow()),
                audit_logger=AuditLogger((sink,)),
            )
        )
        manager.register(GitStatusTool(approved_directories=(self.repo_path,)))
        manager.register(GitCommitTool(approved_directories=(self.repo_path,)))

        with patch("tools.git_tools._git_module", return_value=self.fake_git_module):
            status = manager.execute("git_status", {"repo_path": str(self.repo_path)}, context=SecurityContext(actor_id="admin-1", roles=("admin",)))
            commit = manager.execute(
                "git_commit",
                {"repo_path": str(self.repo_path), "message": "Test commit"},
                context=SecurityContext(actor_id="admin-1", roles=("admin",)),
            )

        self.assertTrue(status.success)
        self.assertTrue(commit.success)
        self.assertEqual([event.event_type for event in sink.events[:3]], ["tool.request", "tool.approval", "tool.execution"])

    def test_checkout_diff_log_and_branch(self) -> None:
        from tools.git_tools import GitBranchTool, GitCheckoutTool, GitDiffTool, GitLogTool

        workflow = AllowHighRiskWorkflow()
        permissions = PermissionManager(approval_workflow=workflow)
        security = SecurityMiddleware(permission_manager=permissions)

        with patch("tools.git_tools._git_module", return_value=self.fake_git_module):
            branch_manager = ToolManager(security_middleware=security)
            branch_manager.register(GitBranchTool(approved_directories=(self.repo_path,)))
            branch_result = branch_manager.execute("git_branch", {"repo_path": str(self.repo_path)}, context=SecurityContext(actor_id="admin-1", roles=("admin",)))

            diff_manager = ToolManager(security_middleware=security)
            diff_manager.register(GitDiffTool(approved_directories=(self.repo_path,)))
            diff_result = diff_manager.execute("git_diff", {"repo_path": str(self.repo_path)}, context=SecurityContext(actor_id="admin-1", roles=("admin",)))

            log_manager = ToolManager(security_middleware=security)
            log_manager.register(GitLogTool(approved_directories=(self.repo_path,)))
            log_result = log_manager.execute("git_log", {"repo_path": str(self.repo_path), "max_count": 1}, context=SecurityContext(actor_id="admin-1", roles=("admin",)))

            checkout_manager = ToolManager(security_middleware=security)
            checkout_manager.register(GitCheckoutTool(approved_directories=(self.repo_path,)))
            checkout_result = checkout_manager.execute(
                "git_checkout",
                {"repo_path": str(self.repo_path), "branch_name": "feature/test", "create_new": True},
                context=SecurityContext(actor_id="admin-1", roles=("admin",)),
            )

        self.assertTrue(branch_result.success)
        self.assertTrue(diff_result.success)
        self.assertEqual(log_result.payload["commits"][0]["summary"], "Initial commit")
        self.assertTrue(checkout_result.success)

    def test_git_tools_block_paths_outside_approved_directory(self) -> None:
        from tools.git_tools import GitStatusTool

        tool = GitStatusTool(approved_directories=(self.repo_path,))
        with patch("tools.git_tools._git_module", return_value=self.fake_git_module):
            with self.assertRaises(PermissionError):
                tool.execute(repo_path=str(self.repo_path.parent / "outside"))


if __name__ == "__main__":
    unittest.main()