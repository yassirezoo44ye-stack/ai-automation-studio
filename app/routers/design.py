import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.ai.models import CompletionRequest, Message
from app.core.ai.inference.engine import InferenceEngine
from app.core.auth import owner_user_id
from app.core.db import get_pool
from app.core.helpers import resolve_project_id
from app.core.reliability import get_bulkhead
from app.core.org_quota import check_org_quota, record_org_tokens
from app.core.security import ai_rate_limit

router = APIRouter(tags=["design"])

DESIGN_SIZES = {
    "Instagram Post":  (1080, 1080),
    "Instagram Story": (1080, 1920),
    "Facebook Cover":  (820, 312),
    "Facebook Post":   (1200, 630),
    "YouTube Thumb":   (1280, 720),
    "A4 Portrait":     (794, 1123),
    "Presentation":    (1920, 1080),
}


# ── Request / response models ─────────────────────────────────────────────────

class DesignAIRequest(BaseModel):
    prompt:   str
    template: Optional[str] = "Instagram Post"


class DesignSaveRequest(BaseModel):
    project_id:  Optional[str] = None
    design_id:   Optional[str] = None
    name:        str           = "Untitled Design"
    canvas_json: dict
    thumbnail:   Optional[str] = None
    width:       int           = 1080
    height:      int           = 1080


# ── AI generation ─────────────────────────────────────────────────────────────

@router.post("/api/design/ai-generate")
async def design_ai_generate(req: DesignAIRequest, request: Request):
    ai_rate_limit(request)
    org_id = await check_org_quota(request)

    w, h = DESIGN_SIZES.get(req.template or "", (1080, 1080))

    system = f"""You are a graphic design AI. Given a design brief, output ONLY a valid JSON object representing a Fabric.js canvas.

Canvas size: {w}x{h}

JSON format:
{{
  "version": "6.0.0",
  "objects": [
    {{
      "type": "Rect", "left": 0, "top": 0, "width": {w}, "height": {h},
      "fill": "gradient_or_hex", "selectable": false
    }},
    {{
      "type": "IText", "text": "MAIN TITLE", "left": {w//2}, "top": {h//3},
      "fontSize": 80, "fontFamily": "Cairo", "fill": "#ffffff",
      "fontWeight": "bold", "textAlign": "center", "originX": "center", "originY": "center"
    }}
  ],
  "background": "#hex_or_gradient_string"
}}

Rules:
- Use Arabic-friendly fonts (Cairo, Tajawal, Almarai) for Arabic text
- Choose beautiful, trendy color combinations
- Include 2-5 text elements and 2-4 decorative shapes
- Make it visually striking and professional
- Return ONLY the JSON, no explanation
"""

    request_obj = CompletionRequest(
        messages=[Message(role="user", content=f"Design brief: {req.prompt}\nTemplate: {req.template}")],
        model="claude-sonnet-4-6",
        max_tokens=3000,
        temperature=1.0,  # match Anthropic's own API default (see chat.py's migration)
        system=system,
        conversation_id=None,
        prompt_id=None,
        memory_enabled=False,
        tools=None,
        stream=False,
    )
    engine = InferenceEngine(pool=get_pool())
    async with get_bulkhead("design", 8).acquire():
        try:
            resp = await engine.complete(request_obj, user_id=None, org_id=None, auto_tools=False)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except Exception as e:
            raise HTTPException(502, str(e))

    try:
        await record_org_tokens(org_id, resp.usage.total_tokens, None, ref_type="design")
    except Exception:
        pass  # metering must never turn a successful reply into an error
    try:
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
        canvas_json = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, "Claude returned invalid JSON for the design.")
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"canvas_json": canvas_json}


# ── Canvas persistence ────────────────────────────────────────────────────────

@router.post("/api/design/canvases", status_code=201)
async def save_canvas(req: DesignSaveRequest, request: Request):
    """Create or upsert a design canvas. Returns the design_id."""
    pool = get_pool()

    async with pool.acquire() as conn:
        uid = await owner_user_id(conn, request)
        pid = await resolve_project_id(conn, req.project_id, uid)
        if req.design_id:
            row = await conn.fetchrow(
                """UPDATE design_canvases
                   SET name=($1), canvas_json=($2)::jsonb, thumbnail=($3),
                       width=($4), height=($5), updated_at=now()
                   WHERE id=($6)::uuid
                   RETURNING id""",
                req.name, json.dumps(req.canvas_json), req.thumbnail,
                req.width, req.height, req.design_id,
            )
            if row:
                return {"id": str(row["id"]), "project_id": str(pid)}
        # insert new
        row = await conn.fetchrow(
            """INSERT INTO design_canvases (project_id, name, canvas_json, thumbnail, width, height)
               VALUES (($1)::uuid, $2, ($3)::jsonb, $4, $5, $6)
               RETURNING id""",
            str(pid), req.name, json.dumps(req.canvas_json),
            req.thumbnail, req.width, req.height,
        )
    return {"id": str(row["id"]), "project_id": str(pid)}


@router.get("/api/design/canvases")
async def list_canvases(request: Request, project_id: Optional[str] = None, limit: int = 50):
    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await owner_user_id(conn, request)
        pid = await resolve_project_id(conn, project_id, uid)
        rows = await conn.fetch(
            """SELECT id, name, thumbnail, width, height, updated_at
               FROM design_canvases WHERE project_id=($1)::uuid
               ORDER BY updated_at DESC LIMIT $2""",
            str(pid), limit,
        )
    return [
        {
            "id":         str(r["id"]),
            "name":       r["name"],
            "thumbnail":  r["thumbnail"],
            "width":      r["width"],
            "height":     r["height"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.get("/api/design/canvases/{design_id}")
async def get_canvas(design_id: str, request: Request):
    """design_canvases has no direct user_id column — ownership is via its
    project_id, so the check JOINs projects the same way resolve_project_id
    verifies a caller-supplied project_id. Without this, any authenticated
    user who learned another user's design_id (a UUID, but one that travels
    through URLs/logs/screenshots) could read that design's full canvas_json."""
    try:
        uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(404, "Design not found")
    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await owner_user_id(conn, request)
        row = await conn.fetchrow(
            """SELECT dc.* FROM design_canvases dc
               JOIN projects p ON p.id = dc.project_id
               WHERE dc.id=($1)::uuid AND p.user_id=$2""",
            design_id, uid,
        )
    if not row:
        raise HTTPException(404, "Design not found")
    # asyncpg has no jsonb codec registered on this pool, so a jsonb column
    # comes back as its raw text — decode it or the client receives a JSON
    # string instead of an object (breaks any round-trip: load then save).
    canvas_json = row["canvas_json"]
    if isinstance(canvas_json, str):
        canvas_json = json.loads(canvas_json)
    return {
        "id":          str(row["id"]),
        "project_id":  str(row["project_id"]),
        "name":        row["name"],
        "canvas_json": canvas_json,
        "thumbnail":   row["thumbnail"],
        "width":       row["width"],
        "height":      row["height"],
        "updated_at":  row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.delete("/api/design/canvases/{design_id}", status_code=204)
async def delete_canvas(design_id: str, request: Request):
    """Same ownership gap as get_canvas above, but destructive: previously
    any authenticated user could delete any other user's design with zero
    ownership check and no recovery path."""
    try:
        uuid.UUID(design_id)
    except ValueError:
        raise HTTPException(404, "Design not found")
    pool = get_pool()
    async with pool.acquire() as conn:
        uid = await owner_user_id(conn, request)
        result = await conn.execute(
            """DELETE FROM design_canvases dc
               USING projects p
               WHERE dc.id=($1)::uuid AND dc.project_id=p.id AND p.user_id=$2""",
            design_id, uid,
        )
    if result == "DELETE 0":
        raise HTTPException(404, "Design not found")


# ── AI design intelligence (Claude-powered, no image API required) ────────────

class PaletteRequest(BaseModel):
    prompt: str
    count:  int  = 5
    mode:   str  = "complementary"


class FontRequest(BaseModel):
    style: str = "modern"
    usage: str = "ui"


class SuggestionsRequest(BaseModel):
    canvas: dict = {}


class AssistantRequest(BaseModel):
    messages:       list[dict]
    canvas_context: dict = {}


async def _call_claude(
    system: str, user: str, max_tokens: int = 1200, *, org_id: Optional[str] = None,
) -> str:
    """Callers (ai_palette/ai_fonts/ai_suggestions below) each wrap this in a
    broad try/except that falls back to a hardcoded default response on ANY
    failure — including a circuit-open RuntimeError, exactly as a raised
    HTTPException from the old manual circuit-breaker precheck (removed by
    this migration) was already caught by that same broad except before.
    No new error handling needed here; re-raising unchanged preserves that
    fallback behavior."""
    request_obj = CompletionRequest(
        messages=[Message(role="user", content=user)],
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        temperature=1.0,  # match Anthropic's own API default (see chat.py's migration)
        system=system,
        conversation_id=None,
        prompt_id=None,
        memory_enabled=False,
        tools=None,
        stream=False,
    )
    engine = InferenceEngine(pool=get_pool())
    async with get_bulkhead("design", 8).acquire():
        resp = await engine.complete(request_obj, user_id=None, org_id=None, auto_tools=False)
    try:
        await record_org_tokens(org_id, resp.usage.total_tokens, None, ref_type="design")
    except Exception:
        pass  # metering must never turn a successful reply into an error
    raw = resp.content.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
    return raw


@router.post("/api/ai/design/palette")
async def ai_palette(req: PaletteRequest, request: Request):
    """Claude generates a design color palette as JSON."""
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    system = (
        'You are a professional color designer. Return ONLY a JSON object: '
        '{"colors":[{"name":"Primary","hex":"#4f46e5","role":"primary"},...]}'
        f' with exactly {req.count} colors optimized for {req.mode} harmony.'
        ' No markdown, no explanation.'
    )
    try:
        raw = await _call_claude(system, f"Design theme: {req.prompt}", org_id=org_id)
        data = json.loads(raw)
        return data
    except (json.JSONDecodeError, Exception):
        return {
            "colors": [
                {"name": "Primary",   "hex": "#4f46e5", "role": "primary"},
                {"name": "Secondary", "hex": "#06b6d4", "role": "secondary"},
                {"name": "Accent",    "hex": "#f59e0b", "role": "accent"},
                {"name": "Dark",      "hex": "#111827", "role": "dark"},
                {"name": "Light",     "hex": "#f9fafb", "role": "light"},
            ]
        }


@router.post("/api/ai/design/fonts")
async def ai_fonts(req: FontRequest, request: Request):
    """Claude suggests font pairings for the given style."""
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    system = (
        'You are a typography expert. Return ONLY a JSON object: '
        '{"pairs":[{"label":"Modern","heading":{"family":"Inter","weight":700},'
        '"body":{"family":"Inter","weight":400}},...]}'
        ' with 3 pairs for the requested style. Only use Google Fonts. No markdown.'
    )
    try:
        raw = await _call_claude(system, f"Style: {req.style}, Usage: {req.usage}", org_id=org_id)
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return {
            "pairs": [
                {"label": "Modern",   "heading": {"family": "Inter", "weight": 700},          "body": {"family": "Inter", "weight": 400}},
                {"label": "Classic",  "heading": {"family": "Playfair Display", "weight": 700}, "body": {"family": "Lato", "weight": 400}},
                {"label": "Friendly", "heading": {"family": "Poppins", "weight": 600},         "body": {"family": "Poppins", "weight": 400}},
            ]
        }


@router.post("/api/ai/design/suggestions")
async def ai_suggestions(req: SuggestionsRequest, request: Request):
    """Claude analyzes the canvas and suggests design improvements."""
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    obj_count = len(req.canvas.get("objects", []))
    system = (
        'You are a senior graphic designer reviewing a Fabric.js canvas. '
        'Return ONLY a JSON object: {"suggestions":[{"type":"color","title":"...", '
        '"summary":"...","action":{"type":"set_background","payload":{"fill":"#fff"}}},...]} '
        'with 3-5 actionable suggestions. Types: color, layout, typography, spacing. No markdown.'
    )
    try:
        raw = await _call_claude(system,
                           f"Canvas has {obj_count} objects. JSON: {json.dumps(req.canvas)[:800]}",
                           org_id=org_id)
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return {"suggestions": []}


@router.post("/api/ai/design/assistant")
async def ai_assistant(req: AssistantRequest, request: Request):
    """Claude as a conversational design assistant."""
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    system = (
        "You are an expert graphic designer and Fabric.js specialist. "
        "Help the user improve their design. Be concise and actionable. "
        "When suggesting canvas changes, include JSON action objects in your response."
    )
    engine = InferenceEngine(pool=get_pool())
    async with get_bulkhead("design", 8).acquire():
        try:
            # Message(role=...) construction happens inside this try — a
            # caller-supplied role outside {"system","user","assistant","tool"}
            # now fails pydantic validation locally instead of reaching
            # Anthropic's API and coming back as a BadRequestError, but the
            # client-visible outcome is unchanged: still a 502.
            request_obj = CompletionRequest(
                messages=[Message(role=m["role"], content=m["content"]) for m in req.messages],
                model="claude-sonnet-4-6",
                max_tokens=1000,
                temperature=1.0,  # match Anthropic's own API default
                system=system,
                conversation_id=None,
                prompt_id=None,
                memory_enabled=False,
                tools=None,
                stream=False,
            )
            resp = await engine.complete(request_obj, user_id=None, org_id=None, auto_tools=False)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except Exception as e:
            raise HTTPException(502, str(e))

    try:
        await record_org_tokens(org_id, resp.usage.total_tokens, None, ref_type="design")
    except Exception:
        pass  # metering must never turn a successful reply into an error
    return {"message": resp.content, "actions": []}
