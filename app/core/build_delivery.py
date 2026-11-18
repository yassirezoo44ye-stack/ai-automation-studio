"""Structural delivery gate. Passing this gate is not runtime verification."""
import json
import re
from pathlib import PurePosixPath

from fastapi import HTTPException


def validate_delivery(prompt: str, plan: dict | None, files: dict[str, str], run_command: str) -> dict:
    if not files or not run_command.strip():
        raise HTTPException(422, 'Build incomplete: files and a startup command are required.')
    for name, content in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or not content.strip():
            raise HTTPException(422, 'Build incomplete: invalid or empty output file.')
    plan = plan or {}
    stack = plan.get('tech_stack') or {}
    backend = str(stack.get('backend', '')).strip().lower()
    transactional = bool(plan.get('database_tables')) or backend not in ('', 'none', 'n/a', 'static', 'no backend') or bool(re.search(
        r'متجر|مخزون|طلبات|حسابات|عملاء|حجوزات|e[- ]?commerce|checkout|inventory|crm|booking|authentication|user accounts', prompt, re.I))
    if transactional:
        sources = {name: text for name, text in files.items() if PurePosixPath(name).suffix in ('.py', '.js', '.ts', '.mjs', '.cjs', '.go', '.rb', '.php', '.cs', '.java')}
        server = '\n'.join(sources.values())
        if not re.search(r'FastAPI|Flask|express\s*\(|createServer\s*\(|NextResponse|export\s+(?:async\s+)?function\s+(?:GET|POST)|net/http|Rails|Laravel|WebApplication|SpringBoot', server):
            raise HTTPException(422, 'Build incomplete: this application requires a backend, not only interface files.')
        if not re.search(r'sqlite3|sqlalchemy|asyncpg|psycopg|prisma|mongoose|drizzle|pg\b|mysql|supabase|firebase|ActiveRecord|EntityFramework|JdbcTemplate', server, re.I):
            raise HTTPException(422, 'Build incomplete: no database implementation was delivered.')
        if not any(PurePosixPath(name).name in ('requirements.txt', 'pyproject.toml', 'package.json', 'go.mod', 'Gemfile', 'composer.json', 'pom.xml') or name.endswith('.csproj') for name in files):
            raise HTTPException(422, 'Build incomplete: backend dependency configuration is missing.')
    for name, content in files.items():
        if PurePosixPath(name).name == 'package.json':
            try:
                if not isinstance(json.loads(content), dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(422, 'Build incomplete: invalid package.json.') from None
    return {'status': 'generated', 'structure_checked': True, 'runtime_verified': False,
            'deployed': False, 'requires_backend': transactional, 'file_count': len(files)}
