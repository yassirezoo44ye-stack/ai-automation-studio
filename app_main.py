"""
New lean entry point — imports app from app.factory.
Run with:  uvicorn app_main:app --host 0.0.0.0 --port 8000
"""
import os
from pathlib import Path

# Load .env BEFORE create_app() runs — app.factory/app.core.config read env vars
# (e.g. DATABASE_URL) at import time, so this must happen first regardless of
# whether the module is executed directly or imported by uvicorn/a test runner.
# setdefault() means real environment variables (Docker, CI) always win.
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
