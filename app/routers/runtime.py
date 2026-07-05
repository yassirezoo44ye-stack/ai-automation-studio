"""
Runtime diagnostics endpoint.

GET /api/runtime/health  — full health report (tools, versions, capabilities, suggestions)
GET /api/runtime/capabilities — just the capability flags
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.runtime import registry, capabilities, diagnostics
from app.runtime.control_plane import runtime

router = APIRouter(tags=["runtime"])


@router.get("/api/runtime/health")
async def runtime_health():
    """Full diagnostic report: all tools, versions, paths, capabilities, and suggestions."""
    return diagnostics.generate().to_dict()


@router.get("/api/runtime/capabilities")
async def runtime_capabilities():
    """Derived capability flags — canRunPython, canBuildAPK, etc."""
    return capabilities.get().to_dict()


@router.get("/api/runtime/registry")
async def runtime_registry_endpoint():
    """Raw tool registry — same data as /api/package/runtimes, unified location."""
    return registry.to_dict()


@router.get("/api/runtime/can/{tool}")
async def runtime_can(tool: str):
    """Check whether a single tool is available on this machine."""
    available = runtime.can(tool)
    return JSONResponse({
        "tool":       tool,
        "available":  available,
        "fix":        runtime.fix_hints(tool) if not available else [],
        "info":       runtime.info(tool).__dict__ if runtime.info(tool) else None,
    })


@router.get("/api/runtime/preflight/{strategy}")
async def runtime_preflight(strategy: str):
    """Run preflight checks for a run strategy (script, server, flask, node, npm)."""
    from app.runtime.preflight import run_preflight_for_strategy
    result = run_preflight_for_strategy(strategy)
    return result.to_unified()
