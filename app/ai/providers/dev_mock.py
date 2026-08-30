"""
DevMockProvider — free, no-external-API provider for the owner dev account.

Generates realistic build output locally without calling any third-party
service.  Never costs money, never requires an API key, never touches
Anthropic billing.

Routing rules (enforced in app/routers/build.py):
  - ONLY routed to when the authenticated user is the dev/owner account.
  - NOT in the default provider failover chain (not in registry.default()).
  - Normal users are NEVER routed here.

This is NOT a billing bypass — it is a legitimate alternative provider
that runs entirely in-process, equivalent in principle to LocalProvider
(which runs against a local Ollama/llama.cpp server) but with no server
dependency.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from app.ai.models import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    UsageStats,
)
from app.ai.providers.base import BaseProvider

log = logging.getLogger(__name__)

# ── Build output template ─────────────────────────────────────────────────────
#
# A complete, working CRM app in the <<<FILE: path>>> / <<<ENDFILE>>> /
# <<<META>>> format that build.py's _BuildParser expects.  Written once,
# streamed in 60-char bursts so the real SSE pipeline (heartbeat, parser,
# file-write, SSE event) is exercised end-to-end.
#
# The app is intentionally production-quality (RTL, localStorage, no deps)
# so the Golden Path test confirms the workspace is genuinely usable.

_BUILD_OUTPUT = """\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>نظام إدارة علاقات العملاء</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f5f5f5;color:#1a1a1a}
.hdr{background:linear-gradient(135deg,#6e32e0,#0ea5e9);color:#fff;padding:16px 24px;display:flex;align-items:center;gap:12px}
.hdr h1{font-size:20px;font-weight:700}
.hdr .badge{font-size:10px;background:rgba(255,255,255,.2);padding:2px 8px;border-radius:99px;letter-spacing:.06em}
.wrap{max-width:1100px;margin:24px auto;padding:0 16px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}
.kpi{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.kpi .v{font-size:32px;font-weight:800;color:#6e32e0}
.kpi .l{font-size:13px;color:#888;margin-top:4px}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:16px}
.card-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-hdr h2{font-size:16px;font-weight:700}
.btn{padding:8px 16px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-p{background:#6e32e0;color:#fff}
.btn-s{background:#f0f0f0;color:#333}
table{width:100%;border-collapse:collapse}
th{text-align:right;padding:10px 12px;font-size:12px;font-weight:600;color:#888;border-bottom:1px solid #eee}
td{padding:10px 12px;font-size:13px;border-bottom:1px solid #f0f0f0}
tr:hover td{background:#fafafa}
.bdg{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}
.hot{background:#fee2e2;color:#dc2626}
.warm{background:#fef3c7;color:#d97706}
.cold{background:#e0f2fe;color:#0284c7}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal.open{display:flex}
.mbox{background:#fff;border-radius:16px;padding:24px;width:480px;max-width:90vw}
.mbox h3{margin-bottom:16px;font-size:18px;font-weight:700}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
input,select,textarea{width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none;font-family:inherit}
input:focus,select:focus{border-color:#6e32e0;box-shadow:0 0 0 3px rgba(110,50,224,.1)}
.macts{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
</style>
</head>
<body>
<div class="hdr">
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>
  <h1>نظام إدارة علاقات العملاء</h1>
  <span class="badge">CRM</span>
</div>
<div class="wrap">
  <div class="kpis">
    <div class="kpi"><div class="v" id="kTotal">0</div><div class="l">إجمالي جهات الاتصال</div></div>
    <div class="kpi"><div class="v" id="kOpen">0</div><div class="l">الصفقات المفتوحة</div></div>
    <div class="kpi"><div class="v" id="kRev">0</div><div class="l">الإيرادات المغلقة (ريال)</div></div>
  </div>
  <div class="card">
    <div class="card-hdr">
      <h2>جهات الاتصال</h2>
      <button class="btn btn-p" onclick="openC()">+ إضافة جهة اتصال</button>
    </div>
    <table>
      <thead><tr><th>الاسم</th><th>الشركة</th><th>البريد</th><th>الهاتف</th><th>الحالة</th><th></th></tr></thead>
      <tbody id="tC"></tbody>
    </table>
  </div>
  <div class="card">
    <div class="card-hdr">
      <h2>الصفقات</h2>
      <button class="btn btn-p" onclick="openD()">+ إضافة صفقة</button>
    </div>
    <table>
      <thead><tr><th>العنوان</th><th>العميل</th><th>القيمة (ريال)</th><th>المرحلة</th><th></th></tr></thead>
      <tbody id="tD"></tbody>
    </table>
  </div>
</div>
<div class="modal" id="mC">
  <div class="mbox">
    <h3>إضافة جهة اتصال</h3>
    <div class="row2">
      <input id="cN" placeholder="الاسم الكامل">
      <input id="cCo" placeholder="الشركة">
    </div>
    <div class="row2">
      <input id="cE" type="email" placeholder="البريد الإلكتروني">
      <input id="cP" placeholder="رقم الهاتف">
    </div>
    <select id="cS" style="margin-bottom:12px">
      <option value="hot">ساخن 🔥</option>
      <option value="warm">دافئ ☀️</option>
      <option value="cold">بارد ❄️</option>
    </select>
    <div class="macts">
      <button class="btn btn-s" onclick="close_('mC')">إلغاء</button>
      <button class="btn btn-p" onclick="saveC()">حفظ</button>
    </div>
  </div>
</div>
<div class="modal" id="mD">
  <div class="mbox">
    <h3>إضافة صفقة</h3>
    <input id="dT" placeholder="عنوان الصفقة" style="margin-bottom:12px">
    <input id="dCl" placeholder="اسم العميل" style="margin-bottom:12px">
    <input id="dV" type="number" placeholder="القيمة بالريال" style="margin-bottom:12px">
    <select id="dSt" style="margin-bottom:12px">
      <option>تواصل أولي</option>
      <option>عرض مقدم</option>
      <option>تفاوض</option>
      <option>مغلقة ✓</option>
    </select>
    <div class="macts">
      <button class="btn btn-s" onclick="close_('mD')">إلغاء</button>
      <button class="btn btn-p" onclick="saveD()">حفظ</button>
    </div>
  </div>
</div>
<script>
var C=JSON.parse(localStorage.getItem('crm_c')||'[]');
var D=JSON.parse(localStorage.getItem('crm_d')||'[]');
function persist(){localStorage.setItem('crm_c',JSON.stringify(C));localStorage.setItem('crm_d',JSON.stringify(D));render()}
function bdg(s){var m={hot:['hot','ساخن'],warm:['warm','دافئ'],cold:['cold','بارد']};var r=m[s]||['',''];return'<span class="bdg '+r[0]+'">'+r[1]+'</span>'}
function render(){
  document.getElementById('kTotal').textContent=C.length;
  document.getElementById('kOpen').textContent=D.filter(function(d){return d.stage!=='مغلقة ✓'}).length;
  document.getElementById('kRev').textContent=D.filter(function(d){return d.stage==='مغلقة ✓'}).reduce(function(s,d){return s+(+d.v||0)},0).toLocaleString('ar');
  var ct=document.getElementById('tC');
  ct.innerHTML=C.map(function(c,i){return'<tr><td>'+c.n+'</td><td>'+c.co+'</td><td>'+c.e+'</td><td>'+c.p+'</td><td>'+bdg(c.s)+'</td><td><button class="btn btn-s" style="font-size:11px;padding:4px 8px" onclick="delC('+i+')">حذف</button></td></tr>'}).join('')||'<tr><td colspan="6" style="text-align:center;color:#aaa;padding:32px">لا توجد جهات اتصال بعد</td></tr>';
  var dt=document.getElementById('tD');
  dt.innerHTML=D.map(function(d,i){return'<tr><td>'+d.t+'</td><td>'+d.cl+'</td><td>'+(+d.v||0).toLocaleString('ar')+'</td><td>'+d.stage+'</td><td><button class="btn btn-s" style="font-size:11px;padding:4px 8px" onclick="delD('+i+')">حذف</button></td></tr>'}).join('')||'<tr><td colspan="5" style="text-align:center;color:#aaa;padding:32px">لا توجد صفقات بعد</td></tr>';
}
function openC(){document.getElementById('mC').classList.add('open')}
function openD(){document.getElementById('mD').classList.add('open')}
function close_(id){document.getElementById(id).classList.remove('open')}
function saveC(){
  var n=document.getElementById('cN').value.trim();if(!n)return;
  C.push({n:n,co:document.getElementById('cCo').value,e:document.getElementById('cE').value,p:document.getElementById('cP').value,s:document.getElementById('cS').value});
  close_('mC');persist();
}
function saveD(){
  var t=document.getElementById('dT').value.trim();if(!t)return;
  D.push({t:t,cl:document.getElementById('dCl').value,v:document.getElementById('dV').value,stage:document.getElementById('dSt').value});
  close_('mD');persist();
}
function delC(i){C.splice(i,1);persist()}
function delD(i){D.splice(i,1);persist()}
render();
</script>
</body>
</html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# نظام إدارة علاقات العملاء (CRM)

نظام CRM بسيط وفعّال لإدارة جهات الاتصال والصفقات التجارية.

## الميزات
- **جهات الاتصال** — إضافة وتصنيف وحذف (ساخن / دافئ / بارد)
- **الصفقات** — تتبع المراحل وقيمة الإيرادات
- **إحصاءات فورية** — إجمالي جهات الاتصال والصفقات المفتوحة والإيرادات
- **تخزين محلي** — البيانات تُحفظ في المتصفح بدون خادم

## التشغيل
```
افتح index.html في أي متصفح حديث
```

## التقنيات
- HTML5 + CSS3 + JavaScript (بدون مكتبات خارجية)
- RTL واجهة عربية كاملة
- localStorage للتخزين الدائم
<<<ENDFILE>>>
<<<META>>>
{"description":"نظام CRM لإدارة جهات الاتصال والصفقات مع إحصاءات فورية","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# Characters per streaming chunk — large enough for throughput,
# small enough that the heartbeat / parser exercise the real SSE path.
_CHUNK_SIZE = 64

# Delay between chunks in seconds — 0.02 s → ~50 chunks/s.
# Total latency ≈ len(_BUILD_OUTPUT) / _CHUNK_SIZE * 0.02 ≈ 2-3 s.
_CHUNK_DELAY = 0.02


class DevMockProvider(BaseProvider):
    """
    Development mock provider — runs entirely in-process, free, no API key.

    Streams a working CRM application in the build-stream <<<FILE:>>> format
    so the real SSE pipeline (parser → file-write → SSE events) is exercised
    end-to-end without any Anthropic (or other paid) API calls.

    Intentionally NOT included in platform_registry.default()'s fallover
    order — it can only be reached by setting request.provider="dev_mock",
    which build.py does exclusively for the dev/owner account.
    """

    provider_id = "dev_mock"

    # ── BaseProvider overrides ────────────────────────────────────────────────

    def _env_key(self) -> str:
        return ""  # no env var — always available

    @property
    def is_available(self) -> bool:
        return True  # in-process; no external dependency

    def default_model(self) -> str:
        return "dev-mock-v1"

    def cost_per_token(self, model: str) -> tuple[float, float]:
        return (0.0, 0.0)  # free

    # ── Completion ────────────────────────────────────────────────────────────

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Non-streaming fallback — returns the full build output at once."""
        log.info("DevMockProvider.complete called (dev mode)")
        return CompletionResponse(
            content=_BUILD_OUTPUT,
            finish_reason="stop",
            usage=UsageStats(
                input_tokens=0,
                output_tokens=len(_BUILD_OUTPUT) // 4,
                total_tokens=len(_BUILD_OUTPUT) // 4,
                provider=self.provider_id,
                model=self.default_model(),
                cost_usd=0.0,
            ),
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream build output in small bursts to exercise the SSE pipeline."""
        log.info("DevMockProvider.stream called (dev mode)")
        text = _BUILD_OUTPUT
        out_tokens = 0

        for i in range(0, len(text), _CHUNK_SIZE):
            chunk = text[i:i + _CHUNK_SIZE]
            yield StreamChunk(type="delta", text=chunk)
            out_tokens += max(1, len(chunk) // 4)
            await asyncio.sleep(_CHUNK_DELAY)

        yield StreamChunk(
            type="usage",
            usage=UsageStats(
                input_tokens=0,
                output_tokens=out_tokens,
                total_tokens=out_tokens,
                provider=self.provider_id,
                model=self.default_model(),
                cost_usd=0.0,
            ),
        )
        yield StreamChunk(type="done")
