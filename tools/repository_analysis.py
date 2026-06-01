"""Repository analysis tool for Jarvis."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from security.risk import RiskLevel

from .base import ToolMetadata, ToolResult, build_object_schema
from .filesystem import FilesystemToolBase

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "node_modules",
    "dist",
    "build",
    "target",
}

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
}

FILENAME_LANGUAGE_HINTS: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "requirements.txt": "Python dependency file",
    "pyproject.toml": "Python dependency file",
    "package.json": "Node.js dependency file",
    "pom.xml": "Maven build file",
    "build.gradle": "Gradle build file",
    "build.gradle.kts": "Gradle build file",
}

FRAMEWORK_HINTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "FastAPI": ("fastapi", ("requirements.txt", "pyproject.toml"), "fastapi"),
    "Flask": ("flask", ("requirements.txt", "pyproject.toml"), "flask"),
    "Django": ("django", ("requirements.txt", "pyproject.toml"), "django"),
    "pytest": ("pytest", ("requirements.txt", "pyproject.toml"), "pytest"),
    "Rich": ("rich", ("requirements.txt", "pyproject.toml"), "rich"),
    "GitPython": ("gitpython", ("requirements.txt", "pyproject.toml"), "gitpython"),
    "Express": ("express", ("package.json",), "express"),
    "React": ("react", ("package.json",), "react"),
    "Next.js": ("next", ("package.json",), "next"),
    "Vite": ("vite", ("package.json",), "vite"),
    "Spring Boot": ("spring-boot", ("pom.xml",), "spring-boot"),
    "Maven": ("pom.xml", ("pom.xml",), "pom.xml"),
    "Gradle": ("build.gradle", ("build.gradle", "build.gradle.kts"), "build.gradle"),
}

TODO_PATTERN = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b[:\- ]*(.*)", re.IGNORECASE)
DEPENDENCY_LINE_PATTERN = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)(?:\s*(==|~=|>=|<=|!=|>|<|===)\s*([^;#\s]+))?")


@dataclass(slots=True)
class RepositoryAnalysisTool(FilesystemToolBase):
    metadata = ToolMetadata(
        name="repository_analysis",
        description="Analyze a repository for languages, frameworks, TODO comments, dependencies, and structure.",
        risk_level=RiskLevel.LOW,
        parameters_schema=build_object_schema(
            properties={
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            required=("path",),
        ),
        tags=("analysis", "repository", "report"),
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        root = self._resolve_path(kwargs["path"])
        max_depth = kwargs.get("max_depth") or 3

        if not root.exists():
            return ToolResult(success=False, message=f"Path '{root}' does not exist.", payload={"path": str(root)})
        if not root.is_dir():
            return ToolResult(success=False, message=f"Path '{root}' is not a directory.", payload={"path": str(root)})

        analysis = self._analyze_repository(root, max_depth=max_depth)
        return ToolResult(success=True, message=self._format_human_report(analysis), payload=analysis)

    def _analyze_repository(self, root: Path, *, max_depth: int) -> dict[str, Any]:
        files = list(self._iter_files(root))
        languages = self._detect_languages(files)
        frameworks = self._detect_frameworks(root, files)
        todos = self._detect_todos(files)
        dependencies = self._analyze_dependencies(root)
        structure = self._summarize_structure(root, max_depth=max_depth)

        return {
            "path": str(root),
            "summary": {
                "file_count": len(files),
                "language_count": len(languages),
                "framework_count": len(frameworks),
                "todo_count": len(todos),
                "dependency_count": len(dependencies),
            },
            "languages": languages,
            "frameworks": frameworks,
            "todos": todos,
            "dependencies": dependencies,
            "structure": structure,
        }

    def _iter_files(self, root: Path):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
                continue
            yield path

    def _detect_languages(self, files: list[Path]) -> list[dict[str, Any]]:
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for path in files:
            language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
            if language is None:
                language = FILENAME_LANGUAGE_HINTS.get(path.name.lower())
            if language is None:
                continue
            counts[language][path.suffix.lower() or path.name.lower()] += 1

        results = []
        for language in sorted(counts):
            hints = counts[language]
            results.append({"name": language, "file_count": sum(hints.values()), "evidence": sorted(hints)})
        return results

    def _detect_frameworks(self, root: Path, files: list[Path]) -> list[dict[str, Any]]:
        present_files = {path.name.lower() for path in files}
        frameworks: list[dict[str, Any]] = []

        for name, (needle, trigger_files, evidence_hint) in FRAMEWORK_HINTS.items():
            matched = False
            for trigger_file in trigger_files:
                candidate = root / trigger_file
                if not candidate.exists():
                    continue
                try:
                    text = candidate.read_text(encoding="utf-8").lower()
                except OSError:
                    text = ""
                if needle in text:
                    frameworks.append({"name": name, "evidence": [trigger_file, evidence_hint]})
                    matched = True
                    break
            if not matched and needle in present_files:
                frameworks.append({"name": name, "evidence": [evidence_hint]})

        seen: set[str] = set()
        unique_frameworks: list[dict[str, Any]] = []
        for framework in frameworks:
            if framework["name"] in seen:
                continue
            seen.add(framework["name"])
            unique_frameworks.append(framework)
        return sorted(unique_frameworks, key=lambda item: item["name"].lower())

    def _detect_todos(self, files: list[Path]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in files:
            if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".cs", ".php", ".sh", ".yaml", ".yml", ".toml", ".md"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if TODO_PATTERN.search(line) is None:
                    continue
                results.append({"path": str(path), "line": line_number, "text": line.strip()})
        return results

    def _analyze_dependencies(self, root: Path) -> list[dict[str, Any]]:
        dependencies: list[dict[str, Any]] = []
        requirements = root / "requirements.txt"
        if requirements.exists():
            dependencies.extend(self._parse_requirements(requirements))

        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            dependencies.extend(self._parse_pyproject(pyproject))

        package_json = root / "package.json"
        if package_json.exists():
            dependencies.extend(self._parse_package_json(package_json))

        pom_xml = root / "pom.xml"
        if pom_xml.exists():
            dependencies.append({"name": "pom.xml", "version": None, "source_file": str(pom_xml), "kind": "build"})

        build_gradle = root / "build.gradle"
        if build_gradle.exists():
            dependencies.append({"name": "build.gradle", "version": None, "source_file": str(build_gradle), "kind": "build"})

        build_gradle_kts = root / "build.gradle.kts"
        if build_gradle_kts.exists():
            dependencies.append({"name": "build.gradle.kts", "version": None, "source_file": str(build_gradle_kts), "kind": "build"})

        seen: set[tuple[str, str | None, str]] = set()
        unique: list[dict[str, Any]] = []
        for dependency in dependencies:
            identity = (dependency.get("name", ""), dependency.get("version"), dependency.get("source_file", ""))
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(dependency)
        return unique

    def _parse_requirements(self, path: Path) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return results

        for line in lines:
            candidate = line.strip()
            if not candidate or candidate.startswith(("#", "-r", "--")):
                continue
            match = DEPENDENCY_LINE_PATTERN.match(candidate)
            if match is None:
                continue
            name, _, version = match.groups()
            results.append({"name": name, "version": version, "source_file": str(path), "kind": "python"})
        return results

    def _parse_pyproject(self, path: Path) -> list[dict[str, Any]]:
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python 3.11 fallback
            return []

        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return []

        results: list[dict[str, Any]] = []
        project = data.get("project", {})
        for dependency in project.get("dependencies", []):
            match = DEPENDENCY_LINE_PATTERN.match(dependency.strip())
            if match is None:
                results.append({"name": dependency, "version": None, "source_file": str(path), "kind": "python"})
                continue
            name, _, version = match.groups()
            results.append({"name": name, "version": version, "source_file": str(path), "kind": "python"})

        for group_name, group_dependencies in project.get("optional-dependencies", {}).items():
            for dependency in group_dependencies:
                results.append({"name": dependency, "version": None, "source_file": str(path), "kind": f"python:{group_name}"})
        return results

    def _parse_package_json(self, path: Path) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        results: list[dict[str, Any]] = []
        for group in ("dependencies", "devDependencies", "peerDependencies"):
            for name, version in data.get(group, {}).items():
                results.append({"name": name, "version": version, "source_file": str(path), "kind": group})
        return results

    def _summarize_structure(self, root: Path, *, max_depth: int) -> dict[str, Any]:
        entries = []
        for path in sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if path.name in IGNORED_DIRECTORY_NAMES:
                continue
            entries.append(self._summarize_tree(path, depth=1, max_depth=max_depth))
        return {"root_entries": entries}

    def _summarize_tree(self, path: Path, *, depth: int, max_depth: int) -> dict[str, Any]:
        item: dict[str, Any] = {"name": path.name, "type": "directory" if path.is_dir() else "file"}
        if path.is_file():
            item["extension"] = path.suffix.lower()
            return item

        if depth >= max_depth:
            return item

        children = []
        try:
            for child in sorted(path.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower())):
                if child.name in IGNORED_DIRECTORY_NAMES:
                    continue
                children.append(self._summarize_tree(child, depth=depth + 1, max_depth=max_depth))
        except OSError:
            children = []

        if children:
            item["children"] = children
        return item

    def _format_human_report(self, analysis: dict[str, Any]) -> str:
        summary = analysis["summary"]
        lines = [
            f"Repository analysis for {analysis['path']}",
            f"Files scanned: {summary['file_count']}",
            f"Languages detected: {self._format_items(analysis['languages'])}",
            f"Frameworks detected: {self._format_items(analysis['frameworks'])}",
            f"TODO comments found: {summary['todo_count']}",
            f"Dependencies found: {summary['dependency_count']}",
        ]

        if analysis["todos"]:
            lines.append("Top TODOs:")
            for todo in analysis["todos"][:5]:
                lines.append(f"- {todo['path']}:{todo['line']} {todo['text']}")

        if analysis["dependencies"]:
            lines.append("Dependencies:")
            for dependency in analysis["dependencies"][:8]:
                version = f" {dependency['version']}" if dependency.get("version") else ""
                lines.append(f"- {dependency['name']}{version} ({dependency['kind']})")

        return "\n".join(lines)

    def _format_items(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return "none"
        return ", ".join(f"{item['name']} ({item.get('file_count', len(item.get('evidence', [])))})" for item in items)


__all__ = ["RepositoryAnalysisTool"]