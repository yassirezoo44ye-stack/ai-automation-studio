"""Source archives exclude runtime credentials, databases and linked files."""
from pathlib import Path

_SKIP = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.next', '.pytest_cache'}


def source_files(root: Path):
    commerce = (root / '.flow-commerce.json').is_file()
    for item in sorted(root.rglob('*')):
        rel = item.relative_to(root)
        if any(part in _SKIP for part in rel.parts) or any(parent.is_symlink() for parent in (item, *item.parents) if parent != root):
            continue
        if commerce and 'data' in rel.parts:
            continue
        if item.name == '.env' or (item.name.startswith('.env.') and item.name != '.env.example'):
            continue
        if item.suffix in ('.sqlite3', '.sqlite', '.db', '.pyc') or item.name.endswith(('-wal', '-shm')):
            continue
        if item.is_file():
            yield item
