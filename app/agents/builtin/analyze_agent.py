"""
Analyze agent — deep inspection of a project or agent performance.

Sub-commands (first arg after 'analyze'):
  <path>         — file/project structure analysis
  agents         — agent performance report from memory
  performance    — full timing + success breakdown
  code <file>    — LLM-powered code review of a specific file
"""
from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path

from app.agents.base import AgentContext, AgentResult, EvolvableAgent

log = logging.getLogger(__name__)

_MAX_FILE_SIZE = 50_000   # bytes — skip files larger than this in tree scan


class AnalyzeAgent(EvolvableAgent):
    name        = "analyze"
    description = "Inspect a project, agent performance, or code quality"
    group       = "analysis"

    async def execute(self, ctx: AgentContext) -> AgentResult:
        parts = shlex.split(ctx.args) if ctx.args else []
        sub   = parts[0].lower() if parts else ""

        if sub == "agents":
            return self._agent_stats(ctx)
        if sub == "performance":
            return self._performance_report(ctx)
        if sub == "code" and len(parts) > 1:
            return await self._code_review(parts[1], ctx)
        if sub:
            return self._project_analysis(sub, ctx)

        return AgentResult.fail(
            self.name,
            "Specify what to analyze: analyze <path> | analyze agents | "
            "analyze performance | analyze code <file>",
        )

    # ── Sub-handlers ─────────────────────────────────────────────────────────

    def _project_analysis(self, workspace: str, ctx: AgentContext) -> AgentResult:
        ws = Path(workspace).expanduser().resolve()
        if not ws.exists():
            return AgentResult.fail(self.name, f"Path not found: {workspace}")

        tree  = _scan_tree(ws, max_depth=3)
        langs = _detect_languages(ws)
        size  = sum(f.stat().st_size for f in ws.rglob("*")
                    if f.is_file() and not _is_ignored(f))

        return AgentResult.ok(
            self.name,
            f"Project analysis: {ws.name} ({len(tree)} files, {size / 1024:.1f} KB)",
            data={
                "workspace"  : str(ws),
                "file_count" : len(tree),
                "total_kb"   : round(size / 1024, 1),
                "languages"  : langs,
                "structure"  : tree[:50],    # first 50 entries
            },
        )

    def _agent_stats(self, ctx: AgentContext) -> AgentResult:
        stats = ctx.memory.global_stats()
        lines = []
        for s in stats:
            bar   = "█" * int(s.success_rate * 10) + "░" * (10 - int(s.success_rate * 10))

            lines.append(
                f"{s.name:<15} {bar} {s.success_rate:.0%}  "
                f"{s.call_count} calls  {s.avg_ms:.0f}ms avg"
            )
        summary = "\n".join(lines) if lines else "No execution history yet."
        return AgentResult.ok(
            self.name, summary,
            data={"stats": [s.to_dict() for s in stats]},
        )

    def _performance_report(self, ctx: AgentContext) -> AgentResult:
        stats        = ctx.memory.global_stats()
        underperform = ctx.memory.underperformers()
        total        = ctx.memory.total_count()
        success      = sum(s.success_count for s in stats)
        fail         = sum(s.fail_count    for s in stats)

        return AgentResult.ok(
            self.name,
            f"Performance: {total} total executions, "
            f"{success} success / {fail} fail, "
            f"{len(underperform)} agents underperforming",
            data={
                "total_executions"     : total,
                "total_success"        : success,
                "total_fail"           : fail,
                "underperforming_agents": [s.name for s in underperform],
                "agent_stats"          : [s.to_dict() for s in stats],
            },
        )

    async def _code_review(self, file: str, ctx: AgentContext) -> AgentResult:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return AgentResult.fail(
                self.name, "ANTHROPIC_API_KEY not set — LLM code review unavailable"
            )

        path = Path(file).expanduser().resolve()
        if not path.exists():
            return AgentResult.fail(self.name, f"File not found: {file}")
        if path.stat().st_size > _MAX_FILE_SIZE:
            return AgentResult.fail(
                self.name, f"File too large for review (>{_MAX_FILE_SIZE // 1000}KB): {file}"
            )

        source = path.read_text(encoding="utf-8", errors="replace")

        from app.core.org_quota import check_org_quota_id, record_org_tokens
        if not await check_org_quota_id(ctx.organization_id):
            return AgentResult.fail(self.name, "Organization AI quota exceeded — code review unavailable")

        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Review this code for bugs, security issues, and improvement opportunities.\n"
                        f"Be concise. File: {file}\n\n```\n{source[:8000]}\n```"
                    ),
                }],
            )
            try:
                total_tokens = msg.usage.input_tokens + msg.usage.output_tokens
                await record_org_tokens(ctx.organization_id, total_tokens, None, ref_type="agent_analyze")
            except Exception:
                pass  # metering must never turn a successful reply into an error
            review = msg.content[0].text.strip()
            return AgentResult.ok(
                self.name, f"Code review for {path.name}",
                data={"file": file, "review": review, "source_lines": len(source.splitlines())},
            )
        except Exception as exc:
            return AgentResult.fail(self.name, f"LLM review failed: {exc}")

    def performance_hint(self) -> dict:
        return {"complexity": "low", "llm_needed": False}


# ── Helpers ───────────────────────────────────────────────────────────────────

_IGNORE = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", ".next"}

def _is_ignored(p: Path) -> bool:
    return any(part in _IGNORE for part in p.parts)

def _scan_tree(root: Path, max_depth: int = 3) -> list[str]:
    result = []
    def _walk(p: Path, depth: int) -> None:
        if depth > max_depth or _is_ignored(p):
            return
        prefix = "  " * depth
        result.append(f"{prefix}{p.name}{'/' if p.is_dir() else ''}")
        if p.is_dir():
            for child in sorted(p.iterdir()):
                _walk(child, depth + 1)
    _walk(root, 0)
    return result

def _detect_languages(root: Path) -> dict[str, int]:
    exts: dict[str, int] = {}
    for f in root.rglob("*"):
        if f.is_file() and not _is_ignored(f) and f.suffix:
            exts[f.suffix] = exts.get(f.suffix, 0) + 1
    return dict(sorted(exts.items(), key=lambda x: x[1], reverse=True)[:10])


agent = AnalyzeAgent()
