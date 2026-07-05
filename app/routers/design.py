import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.db import get_pool
from app.core.helpers import get_ai_client, resolve_project_id
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
    ai = get_ai_client()

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

    try:
        msg = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": f"Design brief: {req.prompt}\nTemplate: {req.template}"}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
        canvas_json = json.loads(raw)
        return {"canvas_json": canvas_json}
    except json.JSONDecodeError:
        raise HTTPException(502, "Claude returned invalid JSON for the design.")
    except Exception as e:
        raise HTTPException(502, str(e))


# ── Canvas persistence ────────────────────────────────────────────────────────

@router.post("/api/design/canvases", status_code=201)
async def save_canvas(req: DesignSaveRequest):
    """Create or upsert a design canvas. Returns the design_id."""
    pool = get_pool()
    pid  = resolve_project_id(req.project_id)

    async with pool.acquire() as conn:
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
async def list_canvases(project_id: Optional[str] = None, limit: int = 50):
    pool = get_pool()
    pid  = resolve_project_id(project_id)
    async with pool.acquire() as conn:
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
async def get_canvas(design_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM design_canvases WHERE id=($1)::uuid", design_id,
        )
    if not row:
        raise HTTPException(404, "Design not found")
    return {
        "id":          str(row["id"]),
        "project_id":  str(row["project_id"]),
        "name":        row["name"],
        "canvas_json": row["canvas_json"],
        "thumbnail":   row["thumbnail"],
        "width":       row["width"],
        "height":      row["height"],
        "updated_at":  row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.delete("/api/design/canvases/{design_id}", status_code=204)
async def delete_canvas(design_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM design_canvases WHERE id=($1)::uuid", design_id,
        )


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


def _call_claude(ai, system: str, user: str, max_tokens: int = 1200) -> str:
    msg = ai.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
    return raw


@router.post("/api/ai/design/palette")
async def ai_palette(req: PaletteRequest, request: Request):
    """Claude generates a design color palette as JSON."""
    ai_rate_limit(request)
    ai = get_ai_client()
    system = (
        'You are a professional color designer. Return ONLY a JSON object: '
        '{"colors":[{"name":"Primary","hex":"#4f46e5","role":"primary"},...]}'
        f' with exactly {req.count} colors optimized for {req.mode} harmony.'
        ' No markdown, no explanation.'
    )
    try:
        raw = _call_claude(ai, system, f"Design theme: {req.prompt}")
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
    ai = get_ai_client()
    system = (
        'You are a typography expert. Return ONLY a JSON object: '
        '{"pairs":[{"label":"Modern","heading":{"family":"Inter","weight":700},'
        '"body":{"family":"Inter","weight":400}},...]}'
        ' with 3 pairs for the requested style. Only use Google Fonts. No markdown.'
    )
    try:
        raw = _call_claude(ai, system, f"Style: {req.style}, Usage: {req.usage}")
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
    ai = get_ai_client()
    obj_count = len(req.canvas.get("objects", []))
    system = (
        'You are a senior graphic designer reviewing a Fabric.js canvas. '
        'Return ONLY a JSON object: {"suggestions":[{"type":"color","title":"...", '
        '"summary":"...","action":{"type":"set_background","payload":{"fill":"#fff"}}},...]} '
        'with 3-5 actionable suggestions. Types: color, layout, typography, spacing. No markdown.'
    )
    try:
        raw = _call_claude(ai, system,
                           f"Canvas has {obj_count} objects. JSON: {json.dumps(req.canvas)[:800]}")
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return {"suggestions": []}


@router.post("/api/ai/design/assistant")
async def ai_assistant(req: AssistantRequest, request: Request):
    """Claude as a conversational design assistant."""
    ai_rate_limit(request)
    ai = get_ai_client()
    system = (
        "You are an expert graphic designer and Fabric.js specialist. "
        "Help the user improve their design. Be concise and actionable. "
        "When suggesting canvas changes, include JSON action objects in your response."
    )
    try:
        msg = ai.messages.create(
            model="claude-sonnet-4-6", max_tokens=1000,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in req.messages],
        )
        return {"message": msg.content[0].text, "actions": []}
    except Exception as e:
        raise HTTPException(502, str(e))
