import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.helpers import get_ai_client
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


class DesignAIRequest(BaseModel):
    prompt: str
    template: Optional[str] = "Instagram Post"


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
