import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.helpers import get_ai_client
from app.core.org_quota import check_org_quota, record_org_tokens
from app.core.security import ai_rate_limit

router = APIRouter(tags=["social"])

SOCIAL_SYSTEM = """You are an expert social media content creator specializing in Arabic and English content.
Create highly engaging, platform-optimized content. Follow these rules:
- Match the tone perfectly
- Use platform best practices (Facebook: longer narrative; Instagram: visual-focused; Twitter: punchy)
- Arabic content should feel natural, not translated
- Return ONLY a JSON array of variation objects: [{"text": "...", "hashtags": [...], "tip": "..."}]
- No markdown fences, just raw JSON array
"""


class SocialRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    platform: str = "facebook"
    content_type: str = "post"
    tone: str = "engaging"
    language: str = "arabic"
    include_hashtags: bool = True
    include_emoji: bool = True
    variations: int = 3


@router.post("/api/social/generate/stream")
async def social_generate_stream(req: SocialRequest, request: Request):
    ai_rate_limit(request)
    org_id = await check_org_quota(request)
    ai = get_ai_client()

    lang_instruction = {
        "arabic":  "Write ONLY in Arabic (العربية).",
        "english": "Write ONLY in English.",
        "both":    "Write a bilingual version: Arabic first, then English translation.",
    }.get(req.language, "Write in Arabic.")

    platform_tips = {
        "facebook":  "Facebook posts: 150-300 words, storytelling format, call to action at end",
        "instagram": "Instagram: 3-5 punchy lines + strong call to action, visual description hint",
        "twitter":   "Twitter/X: under 280 chars each, punchy and direct",
        "linkedin":  "LinkedIn: professional, value-driven, thought leadership style",
    }.get(req.platform, "")

    user_msg = (
        f"Platform: {req.platform.upper()}\n"
        f"Content type: {req.content_type}\n"
        f"Tone: {req.tone}\n"
        f"Language: {lang_instruction}\n"
        f"Include hashtags: {req.include_hashtags}\n"
        f"Include emojis: {req.include_emoji}\n"
        f"Tip: {platform_tips}\n\n"
        f"Topic/Product/Brief:\n{req.topic}\n\n"
        f"Generate {req.variations} unique variations."
    )

    async def event_stream():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Generating content…'})}\n\n"
            chunks: list[str] = []
            with ai.messages.stream(
                model="claude-sonnet-4-6", max_tokens=3000,
                system=SOCIAL_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                try:
                    final = stream.get_final_message()
                    total_tokens = final.usage.input_tokens + final.usage.output_tokens
                    await record_org_tokens(org_id, total_tokens, None, ref_type="social")
                except Exception:
                    pass  # metering must never turn a successful reply into an error
            raw = "".join(chunks).strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            variations = json.loads(raw)
            for i, v in enumerate(variations):
                yield f"data: {json.dumps({'type': 'variation', 'index': i, 'data': v})}\n\n"
                await asyncio.sleep(0.05)
            yield f"data: {json.dumps({'type': 'done', 'count': len(variations)})}\n\n"
        except json.JSONDecodeError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Could not parse response. Try again.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
