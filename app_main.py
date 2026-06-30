"""
New lean entry point — imports app from app.factory.
Run with:  uvicorn app_main:app --host 0.0.0.0 --port 8000
"""
from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    import os
    import uvicorn
    from pathlib import Path

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
