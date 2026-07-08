"""
Arabic NLU Pipeline — Layer 6 integration.

Pipeline stages:
  1. Language detection  (langdetect / heuristic)
  2. Text normalization  (hamza, alef, tashkeel, whitespace)
  3. Intent classification (LLM-based with JSON schema output)
  4. Entity extraction   (LLM NER with typed slots)
  5. Confidence gating   (clarification request if < threshold)
  6. Episodic storage    (persist to memory layer)
  7. Response generation (dialect-matched, RTL-tagged)

No external Arabic NLP libraries required — pure LLM approach.
CAMeL Tools / AraBART can be swapped in by replacing _classify_intent().
"""
from __future__ import annotations

import re
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# ── Arabic text patterns ──────────────────────────────────────────────────────

_ARABIC_RE       = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
_TASHKEEL_RE     = re.compile(r"[ً-ٰٟ]")           # diacritics
_TATWEEL_RE      = re.compile(r"ـ")                           # tatweel ـ
_ALEF_RE         = re.compile(r"[أإآا]")
_YAH_RE          = re.compile(r"[يى]$")
_HEH_RE          = re.compile(r"[ةه]$")

# Intent taxonomy (Arabic-aware)
INTENTS = [
    "question",          # سؤال استفساري
    "command",           # أمر تنفيذي
    "code_request",      # طلب كود
    "explanation",       # شرح / توضيح
    "translation",       # ترجمة
    "generation",        # توليد محتوى
    "analysis",          # تحليل
    "search",            # بحث
    "greeting",          # تحية
    "feedback",          # تغذية راجعة
    "other",             # غير محدد
]

DIALECT_LABELS = ["msa", "gulf", "egyptian", "levantine", "maghrebi", "unknown"]

# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class Entity:
    type  : str           # person | place | date | tech | product | other
    value : str
    span  : Optional[str] = None

@dataclass
class ArabicNLUResult:
    text              : str
    normalized        : str
    language          : str           # "ar" | "ar-mixed" | "other"
    dialect           : str           # msa | gulf | egyptian | ...
    intent            : str
    confidence        : float         # 0.0 – 1.0
    entities          : list[Entity]  = field(default_factory=list)
    needs_clarification: bool         = False
    clarification_prompt: Optional[str] = None
    response_language : str           = "ar"
    rtl               : bool          = True
    processing_ms     : float         = 0.0
    request_id        : str           = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "request_id"           : self.request_id,
            "intent"               : self.intent,
            "confidence"           : round(self.confidence, 3),
            "dialect"              : self.dialect,
            "language"             : self.language,
            "entities"             : [{"type": e.type, "value": e.value} for e in self.entities],
            "needs_clarification"  : self.needs_clarification,
            "clarification_prompt" : self.clarification_prompt,
            "rtl"                  : self.rtl,
            "processing_ms"        : round(self.processing_ms, 1),
        }


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalize_arabic(text: str) -> str:
    """Standard Arabic normalization pipeline."""
    text = _TASHKEEL_RE.sub("", text)          # strip diacritics
    text = _TATWEEL_RE.sub("", text)            # strip tatweel
    text = _ALEF_RE.sub("ا", text)              # unify alef forms
    text = re.sub(r"[يى](\s|$)", "ي\\1", text) # unify yah at end
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_language(text: str) -> str:
    """Heuristic Arabic language detection (no external deps)."""
    arabic_chars = len(_ARABIC_RE.findall(text))
    total_chars  = len(re.sub(r"\s", "", text))
    if total_chars == 0:
        return "other"
    ratio = arabic_chars / total_chars
    if ratio > 0.6:
        return "ar"
    if ratio > 0.2:
        return "ar-mixed"
    return "other"


# ── LLM-based classification ──────────────────────────────────────────────────

_INTENT_SYSTEM = """
أنت محلل لغوي متخصص في اللغة العربية بجميع لهجاتها.

مهمتك: تحليل نص المستخدم وإرجاع JSON صارم بالشكل التالي فقط:

{
  "intent": "<one of: question|command|code_request|explanation|translation|generation|analysis|search|greeting|feedback|other>",
  "confidence": <float 0.0-1.0>,
  "dialect": "<one of: msa|gulf|egyptian|levantine|maghrebi|unknown>",
  "entities": [{"type": "<person|place|date|tech|product|other>", "value": "<extracted text>"}],
  "response_language": "ar"
}

لا تضف أي نص خارج JSON.
""".strip()

_INTENT_SYSTEM_EN = """
You are an Arabic linguistic analyst.

Analyze the following Arabic text and return ONLY this JSON (no other text):

{
  "intent": "<question|command|code_request|explanation|translation|generation|analysis|search|greeting|feedback|other>",
  "confidence": <float 0.0-1.0>,
  "dialect": "<msa|gulf|egyptian|levantine|maghrebi|unknown>",
  "entities": [{"type": "<person|place|date|tech|product|other>", "value": "<extracted text>"}],
  "response_language": "ar"
}
""".strip()

_CLARIFY_TEMPLATES: dict[str, str] = {
    "ar" : "لم أفهم قصدك تماماً. هل يمكنك توضيح ما تقصده بـ «{text}»؟",
    "en" : "I didn't quite understand your intent. Could you clarify what you mean by «{text}»?",
}


async def _llm_classify(text: str, gateway) -> dict:
    """Call the AI Gateway to classify intent. Returns parsed dict."""
    import json as _json

    messages = [
        {"role": "user", "content": f"النص:\n{text}"}
    ]
    try:
        resp = await gateway.complete(
            messages=messages,
            system=_INTENT_SYSTEM,
            model=None,                # gateway picks best for Arabic
            max_tokens=300,
            temperature=0.0,
        )
        content = resp.get("content", "") if isinstance(resp, dict) else str(resp)
        # Extract JSON block
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            return _json.loads(m.group())
    except Exception as exc:
        log.warning("arabic_nlu llm classify failed: %s", exc)
    return {}


def _heuristic_classify(text: str) -> dict:
    """
    Fast rule-based fallback when LLM unavailable.
    Covers the most common patterns.
    """
    lower = text.lower()
    t = normalize_arabic(lower)

    # Greeting
    if any(w in t for w in ["مرحبا", "السلام", "اهلا", "هلا", "صباح", "مساء"]):
        return {"intent": "greeting", "confidence": 0.95, "dialect": "unknown"}

    # Code request
    if any(w in t for w in ["كود", "code", "برنامج", "سكريبت", "script", "دالة", "function", "كلاس", "class"]):
        return {"intent": "code_request", "confidence": 0.85, "dialect": "unknown"}

    # Question
    question_words = ["ما", "ماذا", "كيف", "لماذا", "متى", "اين", "من", "هل", "?", "؟"]
    if any(w in t for w in question_words):
        return {"intent": "question", "confidence": 0.80, "dialect": "unknown"}

    # Command
    command_indicators = ["افعل", "اعمل", "اكتب", "انشئ", "ابني", "اضف", "احذف", "عدل", "غير", "ابحث"]
    if any(w in t for w in command_indicators):
        return {"intent": "command", "confidence": 0.75, "dialect": "unknown"}

    # Translation
    if any(w in t for w in ["ترجم", "translate", "بالانجليزي", "بالعربي"]):
        return {"intent": "translation", "confidence": 0.90, "dialect": "unknown"}

    return {"intent": "other", "confidence": 0.50, "dialect": "unknown"}


# ── Main pipeline ─────────────────────────────────────────────────────────────

class ArabicNLUPipeline:
    """
    Stateless pipeline. Instantiate once, call process() per request.
    Requires an AI Gateway instance for LLM-based classification.
    Falls back to heuristic classifier if gateway unavailable.
    """

    CONFIDENCE_THRESHOLD = 0.72    # below this → ask clarification

    def __init__(self, gateway=None, memory=None) -> None:
        self._gateway = gateway   # app.ai.gateway.AIGateway
        self._memory  = memory    # app.memory.layered.LayeredMemory

    async def process(self, text: str, *, user_id: str = "anonymous",
                      session_id: str = "") -> ArabicNLUResult:
        t0 = time.perf_counter()

        # 1. Language detection
        lang = detect_language(text)

        # 2. Normalization
        normalized = normalize_arabic(text) if "ar" in lang else text

        # 3. Classification
        if self._gateway:
            raw = await _llm_classify(normalized, self._gateway)
        else:
            raw = {}

        if not raw:
            raw = _heuristic_classify(normalized)

        intent     = raw.get("intent", "other")
        confidence = float(raw.get("confidence", 0.5))
        dialect    = raw.get("dialect", "unknown")
        entities   = [
            Entity(type=e.get("type", "other"), value=e.get("value", ""))
            for e in raw.get("entities", [])
        ]

        # 4. Confidence gate
        needs_clarify = confidence < self.CONFIDENCE_THRESHOLD and lang != "other"
        clarify_msg   = None
        if needs_clarify:
            clarify_msg = _CLARIFY_TEMPLATES["ar"].format(text=text[:60])

        elapsed = (time.perf_counter() - t0) * 1000

        result = ArabicNLUResult(
            text               = text,
            normalized         = normalized,
            language           = lang,
            dialect            = dialect,
            intent             = intent,
            confidence         = confidence,
            entities           = entities,
            needs_clarification= needs_clarify,
            clarification_prompt= clarify_msg,
            response_language  = "ar" if "ar" in lang else "en",
            rtl                = "ar" in lang,
            processing_ms      = elapsed,
        )

        # 5. Store to episodic memory
        if self._memory and lang != "other":
            self._store_episode(result, user_id, session_id)

        return result

    def _store_episode(self, result: ArabicNLUResult, user_id: str,
                       session_id: str) -> None:
        try:
            from app.memory.layered import MemoryItem
            item = MemoryItem(
                id         = result.request_id,
                layer      = "short",
                kind       = "arabic_nlu",
                content    = f"intent={result.intent} text={result.text[:120]}",
                data       = result.to_dict(),
                tags       = ["arabic", "nlu", result.intent, result.dialect],
                agent      = user_id,
                success    = not result.needs_clarification,
            )
            self._memory.add(item)
        except Exception as exc:
            log.debug("arabic_nlu memory store failed: %s", exc)

    def build_arabic_system_prompt(self, dialect: str = "msa",
                                    register: str = "formal") -> str:
        """Return a system prompt that instructs the LLM to respond in Arabic."""
        dialect_note = {
            "gulf"     : "استخدم اللهجة الخليجية.",
            "egyptian" : "استخدم اللهجة المصرية.",
            "levantine": "استخدم اللهجة الشامية.",
            "maghrebi" : "استخدم اللهجة المغاربية.",
        }.get(dialect, "")

        return (
            "أجب دائماً باللغة العربية الفصحى الواضحة والمفهومة. "
            f"{dialect_note} "
            "كن دقيقاً ومختصراً في إجاباتك. "
            "استخدم الأرقام العربية (١٢٣) عند الحاجة. "
            "لا تستخدم أي لغة أخرى إلا إذا طُلب منك ذلك صراحةً."
        ).strip()


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: ArabicNLUPipeline | None = None


def get_arabic_nlu(gateway=None, memory=None) -> ArabicNLUPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ArabicNLUPipeline(gateway=gateway, memory=memory)
    elif gateway and _pipeline._gateway is None:
        _pipeline._gateway = gateway
    elif memory and _pipeline._memory is None:
        _pipeline._memory = memory
    return _pipeline
