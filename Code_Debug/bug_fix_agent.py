"""Production-oriented static analysis and test orchestration for source code.

The agent is intentionally dependency-free. Python receives AST-backed checks and
safe auto-fixes; SQL and Java are supported through pluggable adapters and test
commands so their language-specific tooling can be added without changing the
orchestration contract.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str
    line: int = 0
    column: int = 0
    fixable: bool = False
    fixed: bool = False


@dataclass
class TestResult:
    command: list[str]
    passed: bool
    exit_code: int | None
    output: str


@dataclass
class AnalysisReport:
    language: str
    files: list[str]
    findings: list[Finding] = field(default_factory=list)
    tests: list[TestResult] = field(default_factory=list)
    import_errors: list[str] = field(default_factory=list)
    applied_fixes: int = 0

    @property
    def production_ready(self) -> bool:
        blocking = any(
            (item.severity == "error" and not item.fixed) or item.rule == "tooling-required"
            for item in self.findings
        )
        tests_ok = bool(self.tests) and all(item.passed for item in self.tests)
        return not blocking and not self.import_errors and tests_ok


class LanguageAdapter:
    name = "unknown"

    def analyze(self, path: Path) -> list[Finding]:
        raise NotImplementedError

    def apply_safe_fixes(self, path: Path, findings: list[Finding]) -> int:
        return 0


class PythonAdapter(LanguageAdapter):
    name = "python"

    def analyze(self, path: Path) -> list[Finding]:
        findings: list[Finding] = []
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return [Finding("syntax-error", "error", str(exc), str(path), exc.lineno or 0, exc.offset or 0)]
        except OSError as exc:
            return [Finding("read-error", "error", str(exc), str(path))]

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defaults = [*node.args.defaults, *(item for item in node.args.kw_defaults if item)]
                for default in defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        findings.append(Finding(
                            "mutable-default", "error",
                            "Mutable default argument persists between calls.",
                            str(path), node.lineno, node.col_offset, False,
                        ))
            elif isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append(Finding(
                    "bare-except", "warning", "Bare except catches system-exiting exceptions; catch a specific exception.",
                    str(path), node.lineno, node.col_offset,
                ))
            elif isinstance(node, ast.Assert):
                findings.append(Finding(
                    "assert-for-validation", "warning", "Assertions can be disabled with -O; do not use them for runtime validation.",
                    str(path), node.lineno, node.col_offset,
                ))
            elif isinstance(node, ast.Compare):
                for operator, comparator in zip(node.ops, node.comparators):
                    if isinstance(operator, (ast.Is, ast.IsNot)) and isinstance(comparator, ast.Constant) and comparator.value is not None:
                        findings.append(Finding(
                            "identity-comparison", "error",
                            "Use == or != for value comparison; `is` checks object identity.",
                            str(path), node.lineno, node.col_offset, True,
                        ))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval":
                findings.append(Finding(
                    "dynamic-eval", "error", "eval executes dynamic code and is unsafe for production inputs.",
                    str(path), node.lineno, node.col_offset,
                ))
        return findings

    def apply_safe_fixes(self, path: Path, findings: list[Finding]) -> int:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        changed = 0
        for finding in findings:
            if finding.rule != "identity-comparison" or not finding.fixable:
                continue
            index = finding.line - 1
            if index < 0 or index >= len(lines):
                continue
            updated = re.sub(r"(?<![=!<>])\bis\s+not\b(?!\s+None\b)", "!=", lines[index])
            updated = re.sub(r"(?<![=!<>])\bis\b(?!\s+None\b)", "==", updated)
            if updated != lines[index]:
                lines[index] = updated
                finding.fixed = True
                changed += 1
        if changed:
            path.write_text("".join(lines), encoding="utf-8")
        return changed


class CommandAdapter(LanguageAdapter):
    """Fallback adapter for SQL/Java; language tools are configured by command."""

    def __init__(self, language: str) -> None:
        self.name = language

    def analyze(self, path: Path) -> list[Finding]:
        return [Finding(
            "tooling-required", "warning",
            f"{self.name} analysis requires a configured linter/compiler; test execution is still supported.",
            str(path),
        )]


ADAPTERS = {"python": PythonAdapter(), "sql": CommandAdapter("sql"), "java": CommandAdapter("java")}


def detect_language(path: Path) -> str:
    return {".py": "python", ".sql": "sql", ".java": "java"}.get(path.suffix.lower(), "unknown")


def collect_files(target: Path, language: str) -> list[Path]:
    candidates = [target] if target.is_file() else [item for item in target.rglob("*") if item.is_file()]
    return sorted(item for item in candidates if language == "unknown" or detect_language(item) == language)


def run_command(command: Sequence[str], cwd: Path, timeout: int) -> TestResult:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        output = (completed.stdout + completed.stderr).strip()
        return TestResult(list(command), completed.returncode == 0, completed.returncode, output[-12000:])
    except subprocess.TimeoutExpired as exc:
        return TestResult(list(command), False, None, f"Timed out after {timeout}s\n{exc}")
    except OSError as exc:
        return TestResult(list(command), False, None, str(exc))


def import_python_files(files: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    for path in files:
        module_name = f"bug_fix_agent_target_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                errors.append(f"{path}: could not create import spec")
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - report every target import failure
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return errors


def analyze(target: str, language: str | None = None, apply: bool = False, test_command: Sequence[str] | None = None, timeout: int = 120) -> AnalysisReport:
    root = Path(target).resolve()
    selected_language = language or (detect_language(root) if root.is_file() else "python")
    if selected_language not in ADAPTERS:
        raise ValueError(f"Unsupported language: {selected_language}. Choose python, sql, or java.")
    files = collect_files(root, selected_language)
    adapter = ADAPTERS[selected_language]
    report = AnalysisReport(selected_language, [str(path) for path in files])
    for path in files:
        findings = adapter.analyze(path)
        report.findings.extend(findings)
        if apply:
            report.applied_fixes += adapter.apply_safe_fixes(path, findings)
    if selected_language == "python":
        report.import_errors = import_python_files(files)
    command = list(test_command) if test_command else ([sys.executable, "-m", "unittest", "discover"] if selected_language == "python" else None)
    if command:
        report.tests.append(run_command(command, root if root.is_dir() else root.parent, timeout))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze code, apply safe fixes, and qualify it with tests.")
    parser.add_argument("target", nargs="?", default=".", help="A source file or project directory (default: current directory)")
    parser.add_argument("--language", choices=sorted(ADAPTERS), help="Override language detection")
    parser.add_argument("--apply", action="store_true", help="Apply only explicitly safe fixes")
    parser.add_argument("--test-command", nargs="+", help="Test command, for example pytest -q")
    parser.add_argument("--timeout", type=int, default=120, help="Test timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.target, args.language, args.apply, args.test_command, args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    payload = asdict(report)
    payload["production_ready"] = report.production_ready
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Language: {report.language} | Files: {len(report.files)} | Production-ready: {report.production_ready}")
        for finding in report.findings:
            status = " fixed" if finding.fixed else ""
            print(f"{finding.severity.upper():7} {finding.file}:{finding.line} [{finding.rule}] {finding.message}{status}")
        for error in report.import_errors:
            print(f"IMPORT ERROR {error}")
        for result in report.tests:
            print(f"TEST {'PASS' if result.passed else 'FAIL'}: {' '.join(result.command)}")
            if not result.passed and result.output:
                print(result.output)
        print(f"Safe fixes applied: {report.applied_fixes}")
    return 0 if report.production_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
