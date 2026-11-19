"""Structural delivery gate. Passing this gate is not runtime verification."""
import ast
import json
import re
import shlex
from pathlib import PurePosixPath

from fastapi import HTTPException

_PYTHON_BACKENDS = {
    'fastapi.FastAPI', 'fastapi.applications.FastAPI', 'flask.Flask', 'flask.app.Flask',
    'django.core.wsgi.get_wsgi_application', 'django.core.asgi.get_asgi_application',
}
_PYTHON_DATABASES = {
    'sqlite3.connect', 'sqlalchemy.create_engine', 'sqlalchemy.engine.create_engine',
    'sqlalchemy.engine.create.create_engine', 'sqlalchemy.ext.asyncio.create_async_engine',
    'sqlmodel.create_engine', 'asyncpg.connect', 'asyncpg.create_pool', 'psycopg.connect',
    'psycopg2.connect', 'psycopg_pool.ConnectionPool', 'psycopg_pool.AsyncConnectionPool',
    'django.db.models.Model', 'peewee.SqliteDatabase', 'peewee.PostgresqlDatabase',
    'supabase.create_client', 'supabase.client.create_client', 'pymongo.MongoClient',
    'pymongo.AsyncMongoClient', 'motor.motor_asyncio.AsyncIOMotorClient',
    'firebase_admin.firestore.client', 'mysql.connector.connect',
}


def _application_source(name: str) -> bool:
    path = PurePosixPath(name)
    return not (set(path.parts) & {'tests', 'test', '__tests__', 'fixtures'}
                or path.name.startswith('test_') or re.search(r'\.(test|spec)\.', path.name))


def _python_calls(files: dict[str, str]) -> set[str]:
    calls: set[str] = set()
    for name, text in files.items():
        if not name.endswith('.py'):
            continue
        try:
            tree = ast.parse(text, filename=name)
        except (SyntaxError, ValueError):
            raise HTTPException(422, f'Build incomplete: invalid Python syntax in {name}.') from None
        if not _application_source(name):
            continue
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update({a.asname or a.name.split('.')[0]: a.name if a.asname else a.name.split('.')[0] for a in node.names})
            elif isinstance(node, ast.ImportFrom) and node.module:
                aliases.update({a.asname or a.name: f'{node.module}.{a.name}' for a in node.names})

        def qualified(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return f'{qualified(node.value)}.{node.attr}'
            return ''

        calls.update(qualified(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call))
        # Django persists declared models without an explicit connection call.
        calls.update(qualified(base) for node in ast.walk(tree) if isinstance(node, ast.ClassDef) for base in node.bases)
    return calls


def _startup_entry(files: dict[str, str], command: str) -> None:
    try:
        args = shlex.split(command)
    except ValueError:
        raise HTTPException(422, 'Build incomplete: invalid startup command.') from None
    if not args:
        raise HTTPException(422, 'Build incomplete: startup command is empty.')
    executable = PurePosixPath(args[0]).name
    entry = None
    if executable in ('python', 'python3', 'python3.11', 'node', 'nodejs', 'tsx', 'ts-node', 'bun', 'deno'):
        entry = next((arg for arg in args[1:] if not arg.startswith('-') and PurePosixPath(arg).suffix in ('.py', '.js', '.ts', '.mjs', '.cjs')), None)
    elif executable == 'uvicorn':
        module = next((arg.split(':')[0] for arg in args[1:] if ':' in arg and not arg.startswith('-')), None)
        if module:
            entry = module.replace('.', '/') + '.py'
    if entry and str(PurePosixPath(entry)) not in files:
        raise HTTPException(422, 'Build incomplete: the startup entry file was not delivered.')
    if executable == 'npm' and len(args) > 1 and args[1] in ('run', 'start'):
        if args[1] == 'run' and len(args) < 3:
            raise HTTPException(422, 'Build incomplete: the npm startup command must name a script.')
        script = args[2] if args[1] == 'run' and len(args) > 2 else 'start'
        try:
            scripts = json.loads(files.get('package.json', '{}')).get('scripts', {})
        except (ValueError, AttributeError):
            scripts = {}
        if not isinstance(scripts, dict) or not isinstance(scripts.get(script), str) or not scripts[script].strip():
            raise HTTPException(422, 'Build incomplete: the npm startup script was not delivered.')


def validate_delivery(prompt: str, plan: dict | None, files: dict[str, str], run_command: str) -> dict:
    if not files or not run_command.strip():
        raise HTTPException(422, 'Build incomplete: files and a startup command are required.')
    for name, content in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or not content.strip():
            raise HTTPException(422, 'Build incomplete: invalid or empty output file.')
    python_calls = _python_calls(files)
    plan = plan or {}
    stack = plan.get('tech_stack') or {}
    backend = str(stack.get('backend', '')).strip().lower()
    transactional = bool(plan.get('database_tables')) or backend not in ('', 'none', 'n/a', 'static', 'no backend') or bool(re.search(
        r'متجر|مخزون|طلبات|حسابات|عملاء|حجوزات|e[- ]?commerce|checkout|inventory|crm|booking|authentication|user accounts', prompt, re.I))
    requires_frontend = transactional and not (
        not plan.get('pages') and (
            str(stack.get('frontend', '')).strip().lower() in ('none', 'n/a', 'no frontend', 'api only')
            or re.search(r'\b(?:backend|api)[ -]only\b|(?:خلفية|خلفيه|واجهة برمجية) فقط', prompt, re.I)))
    if transactional:
        sources = {name: text for name, text in files.items() if _application_source(name) and PurePosixPath(name).suffix in ('.js', '.ts', '.mjs', '.cjs', '.go', '.rb', '.php', '.cs', '.java')}
        server = '\n'.join(sources.values())
        python_backend = bool(python_calls & _PYTHON_BACKENDS)
        if not python_backend and not re.search(r'express\s*\(|createServer\s*\(|NextResponse|export\s+(?:async\s+)?function\s+(?:GET|POST)|net/http|Rails|Laravel|WebApplication|SpringBoot', server):
            raise HTTPException(422, 'Build incomplete: this application requires a backend, not only interface files.')
        python_database = bool(python_calls & _PYTHON_DATABASES)
        if not python_database and not re.search(r'prisma|mongoose|drizzle|pg\b|mysql|supabase|firebase|ActiveRecord|EntityFramework|JdbcTemplate', server, re.I):
            raise HTTPException(422, 'Build incomplete: no database implementation was delivered.')
        if not any(PurePosixPath(name).name in ('requirements.txt', 'pyproject.toml', 'package.json', 'go.mod', 'Gemfile', 'composer.json', 'pom.xml') or name.endswith('.csproj') for name in files):
            raise HTTPException(422, 'Build incomplete: backend dependency configuration is missing.')
        if requires_frontend and not any(_application_source(name) and PurePosixPath(name).suffix in ('.html', '.htm', '.jsx', '.tsx', '.vue', '.svelte', '.cshtml', '.erb', '.ejs', '.jinja', '.jinja2') for name in files):
            raise HTTPException(422, 'Build incomplete: the application interface was not delivered. Request an API-only backend explicitly if that is the intended scope.')
    for name, content in files.items():
        if PurePosixPath(name).name == 'package.json':
            try:
                if not isinstance(json.loads(content), dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise HTTPException(422, 'Build incomplete: invalid package.json.') from None
    _startup_entry(files, run_command)
    return {'status': 'generated', 'structure_checked': True, 'runtime_verified': False,
            'deployed': False, 'requires_backend': transactional,
            'requires_frontend': requires_frontend, 'file_count': len(files)}
