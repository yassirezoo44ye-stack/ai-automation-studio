from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
