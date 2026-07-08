"""
build — package a project as a downloadable ZIP.

Usage:
    build <workspace>
    build --workspace=./project --output=./dist

Wraps the existing package-build pipeline.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from app.commands.context import CommandContext
from app.commands.result import CommandResult


async def build_handler(ctx: CommandContext) -> CommandResult:
    ws = ctx.resolved_workspace()
    if ws is None or not ws.exists():
        return CommandResult.fail(
            "build",
            f"Workspace not found: {ctx.first_arg()}",
            "WORKSPACE_NOT_FOUND",
            suggestions=["Usage: build <path-to-project>"],
        )

    output_flag = ctx.flag("output", ctx.flag("o"))
    output_dir  = Path(output_flag) if output_flag else ws.parent / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_name = f"{ws.name}-{int(time.time())}.zip"
    zip_path = output_dir / zip_name

    try:
        # Zip the workspace, skipping heavy build artifacts
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next"}
        tmp_base = Path(tempfile.mkdtemp())
        copy_root = tmp_base / ws.name
        copy_root.mkdir()

        for item in ws.rglob("*"):
            rel = item.relative_to(ws)
            if any(part in skip for part in rel.parts):
                continue
            target = copy_root / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(item, target)
                except Exception:
                    pass

        archive = shutil.make_archive(str(zip_path.with_suffix("")), "zip", tmp_base, ws.name)
        shutil.rmtree(tmp_base, ignore_errors=True)

        size_mb = round(Path(archive).stat().st_size / 1024 / 1024, 2)
        return CommandResult.ok(
            "build",
            output=f"✓ Built {zip_name} ({size_mb} MB) → {archive}",
            data={"zip_path": archive, "size_mb": size_mb, "workspace": str(ws)},
        )
    except Exception as exc:
        return CommandResult.fail("build", f"Build failed: {exc}", "BUILD_FAILED")


def register(registry) -> None:
    registry.register(
        "build",
        build_handler,
        description="Package a project as a ZIP archive",
        aliases=["package", "zip"],
        group="execution",
        usage="build <workspace> [--output=<dir>]",
    )
