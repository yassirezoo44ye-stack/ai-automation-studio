"""Bounded, read-only project inspection; never runs user code or follows symlinks."""
import asyncio
import json
import os
import stat
import uuid

from app.agents.base import AgentContext, AgentPermissions, AgentResult, EvolvableAgent, AgentCapability, CapabilityKind
from app.core.config import WORKSPACES
from app.core.db import get_pool


class InspectProjectAgent(EvolvableAgent):
    name = 'inspect_project'
    description = 'Inspect owned project files and manifests without executing code'
    group = 'verification'

    @property
    def permissions(self):
        return AgentPermissions(can_read_filesystem=True, can_call_llm=False, can_access_memory=False)

    @property
    def capabilities(self):
        return [AgentCapability(CapabilityKind.READ, 'Bounded owned-project inspection')]

    async def execute(self, ctx: AgentContext):
        try:
            pid, uid = uuid.UUID(ctx.project_id or ''), uuid.UUID(ctx.user_id or '')
        except ValueError:
            return AgentResult.fail(self.name, 'Verified user and project are required')
        async with get_pool().acquire() as conn:
            owned = await conn.fetchval('SELECT 1 FROM projects WHERE id=$1 AND user_id=$2', pid, uid)
        if not owned:
            return AgentResult.fail(self.name, 'Project not found')
        await ctx.step('Inspecting owned project without executing code', 'info')
        try:
            report = await asyncio.to_thread(inspect_workspace, str(pid))
        except (OSError, ValueError):
            return AgentResult.fail(self.name, 'Project files are absent or unsafe to inspect. Generate or upload files first.')
        if not report['source_files']:
            return AgentResult.fail(self.name, 'No recognized source files. Generate or upload project files first.', data=report)
        return AgentResult.ok(self.name, json.dumps(report, ensure_ascii=False, indent=2), data=report)


def inspect_workspace(project_id):
    project_id = str(uuid.UUID(project_id))
    # dir_fd + O_NOFOLLOW protects every traversed directory and the opened file,
    # including a manifest swapped after enumeration. No source contents are returned.
    root = os.open(WORKSPACES.resolve(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        project = os.open(project_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    finally:
        os.close(root)
    report = {'source_files': 0, 'languages': {}, 'manifests': [], 'package_scripts': [],
              'truncated': False, 'code_executed': False, 'acceptance_verified': False}
    skipped = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__'}
    extensions = {'.py': 'python', '.js': 'javascript', '.jsx': 'javascript', '.ts': 'typescript',
                  '.tsx': 'typescript', '.html': 'html', '.css': 'css'}
    seen = 0

    def scan(fd, depth):
        nonlocal seen
        with os.scandir(fd) as entries:
            for entry in entries:
                seen += 1
                if seen > 5000:
                    report['truncated'] = True
                    return
                if entry.name.startswith('.') or entry.name in skipped or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth >= 8:
                        report['truncated'] = True
                        continue
                    try:
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    except OSError:
                        continue
                    try:
                        scan(child, depth + 1)
                    finally:
                        os.close(child)
                elif entry.is_file(follow_symlinks=False):
                    suffix = os.path.splitext(entry.name)[1].lower()
                    language = extensions.get(suffix)
                    if language:
                        report['source_files'] += 1
                        report['languages'][language] = report['languages'].get(language, 0) + 1

    try:
        scan(project, 0)
        for name in ('package.json', 'pyproject.toml', 'requirements.txt', 'Dockerfile', 'index.html'):
            try:
                info = os.stat(name, dir_fd=project, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
                report['manifests'].append(name)
                if name == 'package.json':
                    manifest = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=project)
                    with os.fdopen(manifest, 'rb') as source:
                        info = os.fstat(source.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 128_000:
                            raise ValueError('Invalid manifest')
                        parsed = json.loads(source.read(128_001))
                    scripts = parsed.get('scripts', {}) if isinstance(parsed, dict) else {}
                    report['package_scripts'] = [key for key in ('build', 'test', 'start', 'dev') if isinstance(scripts, dict) and key in scripts]
            except FileNotFoundError:
                continue
    finally:
        os.close(project)
    return report


agent = InspectProjectAgent()
