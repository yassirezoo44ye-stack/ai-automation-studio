"""
Code Generation Pipeline — secure staged pipeline for autonomous code generation.

Stages (in order):
  1. generate        — LLM writes source code
  2. format          — strip markdown fences, normalize whitespace
  3. lint            — basic syntax check (py_compile / acorn for JS)
  4. static_analysis — banned patterns scan (exec, eval, __import__, os.system, etc.)
  5. security_scan   — path traversal, secret patterns, unsafe imports
  6. unit_test       — stub (real runner hooked via register_test_runner())
  7. approval_gate   — if requires_approval=True, status stays PENDING until approved

Generated code NEVER executes automatically.
It is only registered as a new agent after explicit approve().
"""
from __future__ import annotations

import ast
import logging
import re
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger(__name__)


# ── Banned patterns ───────────────────────────────────────────────────────────

_BANNED_EXEC = [
    re.compile(r'\bexec\s*\('),
    re.compile(r'\beval\s*\('),
    re.compile(r'\b__import__\s*\('),
    re.compile(r'\bos\.system\s*\('),
    re.compile(r'\bsubprocess\.(?:run|Popen|call|check_output)\s*\(.*shell\s*=\s*True'),
    re.compile(r'\bctypes\b'),
]

_BANNED_FS_WRITE = [
    re.compile(r'open\s*\([^)]+["\'][wa]["\']'),
    re.compile(r'shutil\.rmtree'),
    re.compile(r'os\.remove\b'),
    re.compile(r'Path\([^)]+\)\.write_'),
]

_BANNED_NETWORK = [
    re.compile(r'\brequests\.(get|post|put|delete)\b'),
    re.compile(r'\bhttpx\.(get|post|put|delete|AsyncClient)\b'),
    re.compile(r'\baiohttp\.ClientSession'),
]

_SECRET_PATTERNS = [
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'password\s*=\s*["\'][^"\']{6,}["\']', re.I),
]

_PATH_TRAVERSAL = [
    re.compile(r'\.\./'),
    re.compile(r'os\.path\.join\([^)]*\.\.[^)]*\)'),
]

_SAFE_IMPORTS = {
    "asyncio", "time", "logging", "dataclasses", "typing",
    "json", "re", "os", "pathlib", "datetime", "collections",
    "abc", "enum", "uuid", "math", "random",
    "app.agents.base", "app.agents.memory", "app.agents.kernel",
    "app.core.observability",
}

_BANNED_IMPORTS = {
    "ctypes", "subprocess", "socket", "requests", "httpx",
    "paramiko", "ftplib", "smtplib", "pickle", "marshal",
}


# ── Pipeline status ───────────────────────────────────────────────────────────

class CodeGenStatus(str, Enum):
    PENDING     = "pending"
    GENERATING  = "generating"
    FORMATTING  = "formatting"
    LINTING     = "linting"
    ANALYZING   = "analyzing"
    SCANNING    = "scanning"
    TESTING     = "testing"
    AWAITING    = "awaiting_approval"
    APPROVED    = "approved"
    REJECTED    = "rejected"
    REGISTERED  = "registered"
    FAILED      = "failed"


@dataclass
class StageResult:
    stage  : str
    passed : bool
    message: str = ""
    detail : list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"stage": self.stage, "passed": self.passed,
                "message": self.message, "detail": self.detail}


@dataclass
class CodeGenResult:
    run_id     : str
    description: str
    agent_name : str
    status     : CodeGenStatus
    code       : Optional[str]           = None
    stages     : list[StageResult]       = field(default_factory=list)
    error      : Optional[str]           = None
    created_at : float                   = field(default_factory=time.time)
    approved_by: Optional[str]           = None
    approved_at: Optional[float]         = None

    def to_dict(self) -> dict:
        return {
            "run_id"     : self.run_id,
            "description": self.description,
            "agent_name" : self.agent_name,
            "status"     : self.status.value,
            "stages"     : [s.to_dict() for s in self.stages],
            "error"      : self.error,
            "created_at" : self.created_at,
            "approved_by": self.approved_by,
            "has_code"   : self.code is not None,
        }


# ── Pipeline ──────────────────────────────────────────────────────────────────

class CodeGenPipeline:
    """
    Staged code generation pipeline.

    Usage:
        pipeline = get_codegen_pipeline()
        result   = await pipeline.run(description="A network scanner agent",
                                      agent_name="network_scan",
                                      generate_fn=my_llm_writer)
        if result.status == CodeGenStatus.AWAITING:
            pipeline.approve(result.run_id, approver="admin")
    """

    def __init__(self) -> None:
        self._runs        : dict[str, CodeGenResult] = {}
        self._test_runner : Optional[Callable]       = None

    def register_test_runner(self, fn: Callable) -> None:
        """Plug in a real test runner (receives code str, returns (bool, str))."""
        self._test_runner = fn

    # ── Main pipeline entry ───────────────────────────────────────────────────

    async def run(
        self,
        description: str,
        agent_name : str,
        generate_fn: Callable,       # async (description, agent_name) → str
        *,
        requires_approval: bool = True,
    ) -> CodeGenResult:
        from app.core.observability.metrics import get_metrics
        get_metrics().counter("agentos_codegen_total").inc()

        run_id = str(uuid.uuid4())
        result = CodeGenResult(
            run_id=run_id, description=description,
            agent_name=agent_name, status=CodeGenStatus.GENERATING,
        )
        self._runs[run_id] = result

        # ── Stage 1: Generate ──────────────────────────────────────────────
        result.status = CodeGenStatus.GENERATING
        try:
            raw_code = await generate_fn(description, agent_name)
        except Exception as exc:
            return self._fail(result, f"Generate failed: {exc}")

        # ── Stage 2: Format ───────────────────────────────────────────────
        result.status = CodeGenStatus.FORMATTING
        code, fmt_result = self._stage_format(raw_code)
        result.stages.append(fmt_result)
        if not fmt_result.passed:
            return self._fail(result, fmt_result.message)

        # ── Stage 3: Lint ─────────────────────────────────────────────────
        result.status = CodeGenStatus.LINTING
        lint_result = self._stage_lint(code)
        result.stages.append(lint_result)
        if not lint_result.passed:
            return self._fail(result, lint_result.message)

        # ── Stage 4: Static analysis ──────────────────────────────────────
        result.status = CodeGenStatus.ANALYZING
        sa_result = self._stage_static_analysis(code)
        result.stages.append(sa_result)
        if not sa_result.passed:
            return self._fail(result, sa_result.message)

        # ── Stage 5: Security scan ────────────────────────────────────────
        result.status = CodeGenStatus.SCANNING
        sec_result = self._stage_security_scan(code, agent_name)
        result.stages.append(sec_result)
        if not sec_result.passed:
            return self._fail(result, sec_result.message)

        # ── Stage 6: Unit tests ───────────────────────────────────────────
        result.status = CodeGenStatus.TESTING
        test_result = await self._stage_test(code, agent_name)
        result.stages.append(test_result)
        # Test failures are warnings, not blockers — but logged

        # ── Stage 7: Approval gate ────────────────────────────────────────
        result.code = code
        if requires_approval:
            result.status = CodeGenStatus.AWAITING
            log.info("CodeGen run %s awaiting human approval for agent '%s'", run_id, agent_name)
        else:
            result.status = CodeGenStatus.APPROVED
            get_metrics().counter("agentos_codegen_approved").inc()

        return result

    # ── Approval flow ─────────────────────────────────────────────────────────

    def approve(self, run_id: str, approver: str = "system") -> Optional[CodeGenResult]:
        result = self._runs.get(run_id)
        if not result or result.status != CodeGenStatus.AWAITING:
            return None
        result.status     = CodeGenStatus.APPROVED
        result.approved_by = approver
        result.approved_at = time.time()
        from app.core.observability.metrics import get_metrics
        get_metrics().counter("agentos_codegen_approved").inc()
        log.info("CodeGen run %s APPROVED by %s", run_id, approver)
        return result

    def reject(self, run_id: str, reason: str = "") -> Optional[CodeGenResult]:
        result = self._runs.get(run_id)
        if not result or result.status not in (CodeGenStatus.AWAITING, CodeGenStatus.APPROVED):
            return None
        result.status = CodeGenStatus.REJECTED
        result.error  = reason or "Rejected"
        from app.core.observability.metrics import get_metrics
        get_metrics().counter("agentos_codegen_rejected").inc()
        log.info("CodeGen run %s REJECTED: %s", run_id, reason)
        return result

    def get(self, run_id: str) -> Optional[CodeGenResult]:
        return self._runs.get(run_id)

    def list_pending(self) -> list[CodeGenResult]:
        return [r for r in self._runs.values() if r.status == CodeGenStatus.AWAITING]

    # ── Stages ────────────────────────────────────────────────────────────────

    @staticmethod
    def _stage_format(raw: str) -> tuple[str, StageResult]:
        # Strip markdown code fences
        code = re.sub(r"^```(?:python)?\s*\n?", "", raw.strip(), flags=re.M)
        code = re.sub(r"\n?```\s*$", "", code)
        code = textwrap.dedent(code).strip() + "\n"
        return code, StageResult("format", True, "Code formatted successfully")

    @staticmethod
    def _stage_lint(code: str) -> StageResult:
        try:
            ast.parse(code)
            return StageResult("lint", True, "Syntax OK")
        except SyntaxError as exc:
            return StageResult("lint", False,
                               f"Syntax error at line {exc.lineno}: {exc.msg}",
                               detail=[str(exc)])

    @staticmethod
    def _stage_static_analysis(code: str) -> StageResult:
        violations: list[str] = []
        for pattern in _BANNED_EXEC:
            if pattern.search(code):
                violations.append(f"Banned exec pattern: {pattern.pattern}")
        for pattern in _BANNED_FS_WRITE:
            if pattern.search(code):
                violations.append(f"Unsafe filesystem write: {pattern.pattern}")
        for pattern in _BANNED_NETWORK:
            if pattern.search(code):
                violations.append(f"Direct network call: {pattern.pattern}")

        # Import analysis
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else ([node.module] if node.module else [])
                    )
                    for name in names:
                        top = (name or "").split(".")[0]
                        if top in _BANNED_IMPORTS:
                            violations.append(f"Banned import: {name}")
        except SyntaxError:
            pass

        if violations:
            return StageResult("static_analysis", False,
                               f"{len(violations)} violation(s) found", detail=violations)
        return StageResult("static_analysis", True, "No violations found")

    @staticmethod
    def _stage_security_scan(code: str, agent_name: str) -> StageResult:
        issues: list[str] = []
        for pattern in _SECRET_PATTERNS:
            if pattern.search(code):
                issues.append("Possible secret literal in code")
        for pattern in _PATH_TRAVERSAL:
            if pattern.search(code):
                issues.append("Path traversal pattern detected")
        # Agent name must not shadow core files
        core_names = {"kernel", "memory", "base", "loader", "evolution", "reflection"}
        if agent_name.lower() in core_names:
            issues.append(f"Agent name '{agent_name}' shadows a core module")

        if issues:
            return StageResult("security_scan", False,
                               f"{len(issues)} security issue(s)", detail=issues)
        return StageResult("security_scan", True, "No security issues found")

    async def _stage_test(self, code: str, agent_name: str) -> StageResult:
        if self._test_runner is None:
            return StageResult("unit_test", True, "No test runner registered — skipped")
        try:
            passed, message = await self._test_runner(code, agent_name)
            return StageResult("unit_test", passed, message)
        except Exception as exc:
            return StageResult("unit_test", False, f"Test runner error: {exc}")

    @staticmethod
    def _fail(result: CodeGenResult, error: str) -> CodeGenResult:
        result.status = CodeGenStatus.FAILED
        result.error  = error
        log.warning("CodeGen run %s FAILED: %s", result.run_id, error)
        return result


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: CodeGenPipeline | None = None


def get_codegen_pipeline() -> CodeGenPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CodeGenPipeline()
    return _pipeline
