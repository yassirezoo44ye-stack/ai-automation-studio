# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for asyncpg/argon2-cffi wheels + healthcheck curl.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
