"""
Arabic NLU REST API — Layer 6 surface.

POST /arabic/analyze          run the full NLU pipeline
POST /arabic/normalize        normalize Arabic text only
GET  /arabic/intents          return supported intent taxonomy
GET  /arabic/dialects         return supported dialects
POST /arabic/detect-language  detect if text is Arabic / mixed / other
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ai.arabic_nlu import (
    ArabicNLUResult, INTENTS, DIALECT_LABELS,
    detect_language, normalize_arabic, get_arabic_nlu,
)

router = APIRouter(prefix="/arabic", tags=["arabic-nlu"])


# ── Request schemas ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    text       : str = Field(..., min_length=1, max_length=8000)
    user_id    : str = "anonymous"
    session_id : str = ""


class NormalizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class DetectRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze(body: AnalyzeRequest):
    """
    Full Arabic NLU pipeline.
    Returns intent, dialect, entities, confidence, and clarification hint.
    """
    pipeline = get_arabic_nlu()
    result: ArabicNLUResult = await pipeline.process(
        body.text,
        user_id    = body.user_id,
        session_id = body.session_id,
    )
    return result.to_dict()


@router.post("/normalize")
def normalize(body: NormalizeRequest):
    """Return normalized Arabic text (strip diacritics, unify alef/yah/heh)."""
    return {
        "original"  : body.text,
        "normalized": normalize_arabic(body.text),
    }


@router.get("/intents")
def list_intents():
    """Return the full intent taxonomy."""
    return {"intents": INTENTS}


@router.get("/dialects")
def list_dialects():
    """Return supported Arabic dialect labels."""
    return {"dialects": DIALECT_LABELS}


@router.post("/detect-language")
def detect_lang(body: DetectRequest):
    """Quick language detection — no LLM needed."""
    lang = detect_language(body.text)
    return {
        "text"    : body.text[:80],
        "language": lang,
        "is_arabic": "ar" in lang,
    }
