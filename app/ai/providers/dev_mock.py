"""
DevMockProvider — free, no-external-API provider for the owner/dev account.

Generates realistic, prompt-aware build output locally without calling any
third-party service.  Never costs money, never requires an API key.

Routing rules (enforced in app/routers/build.py):
  - ONLY routed to when the authenticated user is the dev/owner account.
  - NOT in the default provider failover chain.
  - Normal users are NEVER routed here.

Template selection:
  _select_template() reads the user prompt (Arabic + English keyword matching)
  and picks the best-fit template from the library below.  When no keyword
  matches, the generic business-dashboard template is used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import AsyncGenerator

from app.ai.models import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    UsageStats,
)
from app.ai.providers.base import BaseProvider

log = logging.getLogger(__name__)

# ── Characters per streaming chunk / delay ────────────────────────────────────
_CHUNK_SIZE = 64
_CHUNK_DELAY = 0.02   # ~50 chunks/s  → ~2-3 s total


# ═══════════════════════════════════════════════════════════════════════════════
#  Templates
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. CRM ────────────────────────────────────────────────────────────────────
_TEMPLATE_CRM = """\
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
.hdr h1{font-size:20px;font-weight:700}.hdr .badge{font-size:10px;background:rgba(255,255,255,.2);padding:2px 8px;border-radius:99px}
.wrap{max-width:1100px;margin:24px auto;padding:0 16px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}
.kpi{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.kpi .v{font-size:32px;font-weight:800;color:#6e32e0}.kpi .l{font-size:13px;color:#888;margin-top:4px}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:16px}
.card-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-hdr h2{font-size:16px;font-weight:700}
.btn{padding:8px 16px;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;transition:opacity .15s}.btn:hover{opacity:.85}
.btn-p{background:#6e32e0;color:#fff}.btn-s{background:#f0f0f0;color:#333}
table{width:100%;border-collapse:collapse}
th{text-align:right;padding:10px 12px;font-size:12px;font-weight:600;color:#888;border-bottom:1px solid #eee}
td{padding:10px 12px;font-size:13px;border-bottom:1px solid #f0f0f0}
.bdg{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}
.hot{background:#fee2e2;color:#dc2626}.warm{background:#fef3c7;color:#d97706}.cold{background:#e0f2fe;color:#0284c7}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal.open{display:flex}.mbox{background:#fff;border-radius:16px;padding:24px;width:480px;max-width:90vw}
.mbox h3{margin-bottom:16px;font-size:18px;font-weight:700}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
input,select{width:100%;padding:8px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;font-family:inherit}
input:focus,select:focus{border-color:#6e32e0;outline:none}
.macts{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
</style>
</head>
<body>
<div class="hdr">
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
  <h1>نظام إدارة علاقات العملاء</h1><span class="badge">CRM</span>
</div>
<div class="wrap">
  <div class="kpis">
    <div class="kpi"><div class="v" id="kT">0</div><div class="l">إجمالي جهات الاتصال</div></div>
    <div class="kpi"><div class="v" id="kO">0</div><div class="l">الصفقات المفتوحة</div></div>
    <div class="kpi"><div class="v" id="kR">0</div><div class="l">الإيرادات (ر.س)</div></div>
  </div>
  <div class="card">
    <div class="card-hdr"><h2>جهات الاتصال</h2><button class="btn btn-p" onclick="openC()">+ إضافة</button></div>
    <table><thead><tr><th>الاسم</th><th>الشركة</th><th>البريد</th><th>الحالة</th><th></th></tr></thead><tbody id="tC"></tbody></table>
  </div>
  <div class="card">
    <div class="card-hdr"><h2>الصفقات</h2><button class="btn btn-p" onclick="openD()">+ إضافة</button></div>
    <table><thead><tr><th>العنوان</th><th>العميل</th><th>القيمة</th><th>المرحلة</th><th></th></tr></thead><tbody id="tD"></tbody></table>
  </div>
</div>
<div class="modal" id="mC"><div class="mbox"><h3>إضافة جهة اتصال</h3>
  <div class="row2"><input id="cN" placeholder="الاسم"><input id="cCo" placeholder="الشركة"></div>
  <div class="row2"><input id="cE" type="email" placeholder="البريد"><input id="cP" placeholder="الهاتف"></div>
  <select id="cS" style="margin-bottom:12px"><option value="hot">ساخن 🔥</option><option value="warm">دافئ ☀️</option><option value="cold">بارد ❄️</option></select>
  <div class="macts"><button class="btn btn-s" onclick="cl('mC')">إلغاء</button><button class="btn btn-p" onclick="saveC()">حفظ</button></div>
</div></div>
<div class="modal" id="mD"><div class="mbox"><h3>إضافة صفقة</h3>
  <input id="dT" placeholder="عنوان الصفقة" style="margin-bottom:12px">
  <input id="dCl" placeholder="اسم العميل" style="margin-bottom:12px">
  <input id="dV" type="number" placeholder="القيمة" style="margin-bottom:12px">
  <select id="dSt" style="margin-bottom:12px"><option>تواصل أولي</option><option>عرض مقدم</option><option>تفاوض</option><option>مغلقة ✓</option></select>
  <div class="macts"><button class="btn btn-s" onclick="cl('mD')">إلغاء</button><button class="btn btn-p" onclick="saveD()">حفظ</button></div>
</div></div>
<script>
var C=JSON.parse(localStorage.getItem('crm_c')||'[]'),D=JSON.parse(localStorage.getItem('crm_d')||'[]');
function save(){localStorage.setItem('crm_c',JSON.stringify(C));localStorage.setItem('crm_d',JSON.stringify(D));render()}
function bdg(s){var m={hot:['hot','ساخن'],warm:['warm','دافئ'],cold:['cold','بارد']};var r=m[s]||['',''];return'<span class="bdg '+r[0]+'">'+r[1]+'</span>'}
function render(){
  document.getElementById('kT').textContent=C.length;
  document.getElementById('kO').textContent=D.filter(function(d){return d.s!=='مغلقة ✓'}).length;
  document.getElementById('kR').textContent=D.filter(function(d){return d.s==='مغلقة ✓'}).reduce(function(a,d){return a+(+d.v||0)},0).toLocaleString('ar');
  document.getElementById('tC').innerHTML=C.map(function(c,i){return'<tr><td>'+c.n+'</td><td>'+c.co+'</td><td>'+c.e+'</td><td>'+bdg(c.st)+'</td><td><button class="btn btn-s" style="padding:4px 8px;font-size:11px" onclick="delC('+i+')">حذف</button></td></tr>'}).join('')||'<tr><td colspan="5" style="text-align:center;color:#aaa;padding:32px">لا توجد جهات اتصال</td></tr>';
  document.getElementById('tD').innerHTML=D.map(function(d,i){return'<tr><td>'+d.t+'</td><td>'+d.cl+'</td><td>'+(+d.v||0).toLocaleString('ar')+'</td><td>'+d.s+'</td><td><button class="btn btn-s" style="padding:4px 8px;font-size:11px" onclick="delD('+i+')">حذف</button></td></tr>'}).join('')||'<tr><td colspan="5" style="text-align:center;color:#aaa;padding:32px">لا توجد صفقات</td></tr>';}
function openC(){document.getElementById('mC').classList.add('open')}
function openD(){document.getElementById('mD').classList.add('open')}
function cl(id){document.getElementById(id).classList.remove('open')}
function saveC(){var n=document.getElementById('cN').value.trim();if(!n)return;C.push({n:n,co:document.getElementById('cCo').value,e:document.getElementById('cE').value,p:document.getElementById('cP').value,st:document.getElementById('cS').value});cl('mC');save()}
function saveD(){var t=document.getElementById('dT').value.trim();if(!t)return;D.push({t:t,cl:document.getElementById('dCl').value,v:document.getElementById('dV').value,s:document.getElementById('dSt').value});cl('mD');save()}
function delC(i){C.splice(i,1);save()} function delD(i){D.splice(i,1);save()}
render();
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# نظام CRM
إدارة جهات الاتصال والصفقات — افتح index.html في متصفح حديث.
<<<ENDFILE>>>
<<<META>>>
{"description":"نظام CRM لإدارة العملاء والصفقات","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# ── 2. متجر إلكتروني ──────────────────────────────────────────────────────────
_TEMPLATE_ECOMMERCE = """\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>متجري الإلكتروني</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f8fafc;color:#1e293b}
.hdr{background:#0f172a;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between}
.hdr h1{font-size:20px;font-weight:700;display:flex;align-items:center;gap:8px}
.cart-btn{background:#f59e0b;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-weight:600;font-size:14px;display:flex;align-items:center;gap:6px}
.wrap{max-width:1100px;margin:24px auto;padding:0 16px}
.filters{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.filter-btn{padding:6px 14px;border:1px solid #e2e8f0;border-radius:99px;background:#fff;cursor:pointer;font-size:13px;font-family:inherit}
.filter-btn.active{background:#0f172a;color:#fff;border-color:#0f172a}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}
.card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);transition:transform .2s}
.card:hover{transform:translateY(-2px)}
.card-img{height:160px;display:flex;align-items:center;justify-content:center;font-size:56px}
.card-body{padding:16px}
.card-name{font-weight:600;font-size:15px;margin-bottom:4px}
.card-cat{font-size:11px;color:#94a3b8;margin-bottom:8px}
.card-price{font-size:18px;font-weight:800;color:#0f172a;margin-bottom:12px}
.add-btn{width:100%;background:#f59e0b;color:#fff;border:none;padding:10px;border-radius:8px;cursor:pointer;font-weight:600;font-size:14px;font-family:inherit}
.add-btn:hover{background:#d97706}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:flex-start;justify-content:flex-end}
.modal.open{display:flex}
.cart-panel{background:#fff;width:380px;height:100%;padding:24px;overflow-y:auto}
.cart-panel h2{font-size:18px;font-weight:700;margin-bottom:16px;display:flex;justify-content:space-between}
.ci{display:flex;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid #f0f0f0}
.ci-em{font-size:32px}.ci-info{flex:1}
.ci-name{font-size:14px;font-weight:600}.ci-price{font-size:13px;color:#64748b}
.ci-del{background:none;border:none;color:#ef4444;cursor:pointer;font-size:18px}
.cart-total{margin-top:16px;font-size:16px;font-weight:700;text-align:center}
.checkout-btn{width:100%;background:#0f172a;color:#fff;border:none;padding:14px;border-radius:10px;cursor:pointer;font-weight:700;font-size:15px;margin-top:12px;font-family:inherit}
</style>
</head>
<body>
<div class="hdr">
  <h1>🛍️ متجري</h1>
  <button class="cart-btn" onclick="openCart()">🛒 السلة <span id="cartCount">0</span></button>
</div>
<div class="wrap">
  <div class="filters">
    <button class="filter-btn active" onclick="filter('all',this)">الكل</button>
    <button class="filter-btn" onclick="filter('الكترونيات',this)">الكترونيات</button>
    <button class="filter-btn" onclick="filter('ملابس',this)">ملابس</button>
    <button class="filter-btn" onclick="filter('منزل',this)">منزل</button>
  </div>
  <div class="grid" id="grid"></div>
</div>
<div class="modal" id="cartModal">
  <div class="cart-panel">
    <h2>سلة التسوق <button style="background:none;border:none;cursor:pointer;font-size:20px" onclick="closeCart()">✕</button></h2>
    <div id="cartItems"></div>
    <div class="cart-total" id="cartTotal"></div>
    <button class="checkout-btn" onclick="checkout()">إتمام الشراء ✓</button>
  </div>
</div>
<script>
var products=[
  {id:1,name:'سماعات لاسلكية',cat:'الكترونيات',price:199,em:'🎧'},
  {id:2,name:'ساعة ذكية',cat:'الكترونيات',price:349,em:'⌚'},
  {id:3,name:'لابتوب خفيف',cat:'الكترونيات',price:1899,em:'💻'},
  {id:4,name:'قميص قطني',cat:'ملابس',price:79,em:'👕'},
  {id:5,name:'حذاء رياضي',cat:'ملابس',price:149,em:'👟'},
  {id:6,name:'وسادة ذكية',cat:'منزل',price:99,em:'🛋️'},
  {id:7,name:'مصباح LED',cat:'منزل',price:59,em:'💡'},
  {id:8,name:'كتاب تطوير الذات',cat:'منزل',price:39,em:'📚'},
];
var cart=[];
var currentFilter='all';
function filter(cat,btn){
  currentFilter=cat;
  document.querySelectorAll('.filter-btn').forEach(function(b){b.classList.remove('active')});
  btn.classList.add('active');
  render();
}
function render(){
  var list=currentFilter==='all'?products:products.filter(function(p){return p.cat===currentFilter});
  document.getElementById('grid').innerHTML=list.map(function(p){
    return'<div class="card"><div class="card-img">'+p.em+'</div><div class="card-body"><div class="card-name">'+p.name+'</div><div class="card-cat">'+p.cat+'</div><div class="card-price">'+p.price+' ر.س</div><button class="add-btn" onclick="addCart('+p.id+')">أضف للسلة</button></div></div>';
  }).join('');
}
function addCart(id){
  var p=products.find(function(x){return x.id===id});
  var ex=cart.find(function(x){return x.id===id});
  if(ex)ex.qty++;else cart.push({...p,qty:1});
  updateCart();
  var btn=event.target;btn.textContent='✓ أُضيف';setTimeout(function(){btn.textContent='أضف للسلة'},1000);
}
function updateCart(){
  document.getElementById('cartCount').textContent=cart.reduce(function(a,x){return a+x.qty},0);
  document.getElementById('cartItems').innerHTML=cart.map(function(x,i){
    return'<div class="ci"><div class="ci-em">'+x.em+'</div><div class="ci-info"><div class="ci-name">'+x.name+' ×'+x.qty+'</div><div class="ci-price">'+(x.price*x.qty)+' ر.س</div></div><button class="ci-del" onclick="removeCart('+i+')">✕</button></div>';
  }).join('')||'<p style="color:#94a3b8;text-align:center;padding:32px">السلة فارغة</p>';
  var total=cart.reduce(function(a,x){return a+x.price*x.qty},0);
  document.getElementById('cartTotal').textContent=total?'المجموع: '+total+' ر.س':'';
}
function removeCart(i){cart.splice(i,1);updateCart()}
function openCart(){document.getElementById('cartModal').classList.add('open')}
function closeCart(){document.getElementById('cartModal').classList.remove('open')}
function checkout(){if(!cart.length)return;alert('✅ تم استلام طلبك! سيتم التواصل معك قريباً.');cart=[];updateCart();closeCart();}
render();
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# متجر إلكتروني
متجر عربي RTL مع سلة تسوق — افتح index.html في متصفح حديث.
<<<ENDFILE>>>
<<<META>>>
{"description":"متجر إلكتروني عربي مع سلة تسوق وتصفية","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# ── 3. مدير المهام ────────────────────────────────────────────────────────────
_TEMPLATE_TASKS = """\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>مدير المهام</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.hdr{padding:24px 32px;border-bottom:1px solid #1e293b;display:flex;align-items:center;justify-content:space-between}
.hdr h1{font-size:22px;font-weight:700;display:flex;align-items:center;gap:10px}
.stats{display:flex;gap:16px}
.stat{text-align:center}.stat .v{font-size:22px;font-weight:800;color:#818cf8}.stat .l{font-size:11px;color:#64748b}
.main{max-width:900px;margin:0 auto;padding:24px 16px}
.add-form{display:flex;gap:10px;margin-bottom:24px}
.add-form input{flex:1;background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px 16px;color:#e2e8f0;font-size:14px;font-family:inherit}
.add-form input:focus{outline:none;border-color:#818cf8}
.add-form select{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px;color:#e2e8f0;font-family:inherit}
.add-btn{background:#818cf8;color:#fff;border:none;border-radius:10px;padding:12px 20px;cursor:pointer;font-weight:600;font-family:inherit}
.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.col{background:#1e293b;border-radius:12px;padding:16px}
.col-hdr{font-size:14px;font-weight:600;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center}
.col-hdr .badge{font-size:11px;background:#0f172a;padding:2px 8px;border-radius:99px}
.task{background:#0f172a;border-radius:8px;padding:12px;margin-bottom:8px;cursor:grab;border-right:3px solid transparent}
.task.pri-high{border-color:#ef4444}.task.pri-med{border-color:#f59e0b}.task.pri-low{border-color:#22c55e}
.task-text{font-size:13px;margin-bottom:6px}
.task-meta{display:flex;justify-content:space-between;align-items:center}
.pri-badge{font-size:10px;padding:1px 6px;border-radius:99px;font-weight:600}
.pri-high .pri-badge{background:#fee2e2;color:#dc2626}
.pri-med .pri-badge{background:#fef3c7;color:#d97706}
.pri-low .pri-badge{background:#dcfce7;color:#16a34a}
.del-btn{background:none;border:none;color:#64748b;cursor:pointer;font-size:14px;padding:2px 6px}
.del-btn:hover{color:#ef4444}
.move-btn{background:#334155;border:none;color:#94a3b8;cursor:pointer;font-size:11px;padding:2px 8px;border-radius:4px;margin-left:4px}
</style>
</head>
<body>
<div class="hdr">
  <h1>✅ مدير المهام</h1>
  <div class="stats">
    <div class="stat"><div class="v" id="sTot">0</div><div class="l">المجموع</div></div>
    <div class="stat"><div class="v" id="sDone">0</div><div class="l">منجزة</div></div>
  </div>
</div>
<div class="main">
  <div class="add-form">
    <input id="inp" placeholder="أضف مهمة جديدة…" onkeydown="if(event.key==='Enter')add()">
    <select id="pri"><option value="high">عالية 🔴</option><option value="med" selected>متوسطة 🟡</option><option value="low">منخفضة 🟢</option></select>
    <button class="add-btn" onclick="add()">+ إضافة</button>
  </div>
  <div class="cols">
    <div class="col"><div class="col-hdr">📋 قيد الانتظار <span class="badge" id="c0">0</span></div><div id="col0"></div></div>
    <div class="col"><div class="col-hdr">⚡ قيد التنفيذ <span class="badge" id="c1">0</span></div><div id="col1"></div></div>
    <div class="col"><div class="col-hdr">✅ مكتملة <span class="badge" id="c2">0</span></div><div id="col2"></div></div>
  </div>
</div>
<script>
var tasks=JSON.parse(localStorage.getItem('tasks_v2')||'[]');
var priLabel={high:'عالية',med:'متوسطة',low:'منخفضة'};
function save(){localStorage.setItem('tasks_v2',JSON.stringify(tasks));render()}
function add(){var t=document.getElementById('inp').value.trim();if(!t)return;tasks.push({id:Date.now(),text:t,pri:document.getElementById('pri').value,col:0});document.getElementById('inp').value='';save()}
function del(id){tasks=tasks.filter(function(t){return t.id!==id});save()}
function move(id,dir){var t=tasks.find(function(x){return x.id===id});if(t){t.col=Math.max(0,Math.min(2,t.col+dir));save()}}
function render(){
  var cols=[[],[],[]];
  tasks.forEach(function(t){cols[t.col].push(t)});
  [0,1,2].forEach(function(i){
    document.getElementById('col'+i).innerHTML=cols[i].map(function(t){
      return'<div class="task pri-'+t.pri+'"><div class="task-text">'+t.text+'</div><div class="task-meta"><span class="pri-badge">'+priLabel[t.pri]+'</span><div>'+(i>0?'<button class="move-btn" onclick="move('+t.id+',-1)">←</button>':'')+(i<2?'<button class="move-btn" onclick="move('+t.id+',1)">→</button>':'')+'<button class="del-btn" onclick="del('+t.id+')">✕</button></div></div></div>';
    }).join('');
    document.getElementById('c'+i).textContent=cols[i].length;
  });
  document.getElementById('sTot').textContent=tasks.length;
  document.getElementById('sDone').textContent=cols[2].length;
}
render();
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# مدير المهام
لوحة كانبان ثلاثية الأعمدة — افتح index.html في متصفح حديث.
<<<ENDFILE>>>
<<<META>>>
{"description":"مدير مهام بنظام كانبان (انتظار → تنفيذ → مكتمل)","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# ── 4. صفحة هبوط / منتج رقمي ─────────────────────────────────────────────────
_TEMPLATE_LANDING = """\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>منتجي الرقمي</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;color:#1a1a2e;background:#fff}
/* Nav */
nav{background:#fff;padding:16px 32px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;box-shadow:0 1px 8px rgba(0,0,0,.06);z-index:10}
.logo{font-size:20px;font-weight:800;color:#7c3aed}
.nav-cta{background:#7c3aed;color:#fff;border:none;padding:10px 22px;border-radius:8px;cursor:pointer;font-weight:600;font-size:14px;font-family:inherit}
/* Hero */
.hero{background:linear-gradient(135deg,#7c3aed 0%,#a855f7 50%,#ec4899 100%);color:#fff;padding:80px 24px;text-align:center}
.hero .eyebrow{font-size:13px;font-weight:600;letter-spacing:.08em;opacity:.85;margin-bottom:16px;text-transform:uppercase}
.hero h1{font-size:clamp(28px,5vw,52px);font-weight:900;line-height:1.15;margin-bottom:20px}
.hero .sub{font-size:18px;opacity:.9;max-width:540px;margin:0 auto 32px;line-height:1.6}
.hero-btns{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.btn-primary{background:#fff;color:#7c3aed;border:none;padding:14px 32px;border-radius:10px;font-weight:700;font-size:16px;cursor:pointer;font-family:inherit;transition:transform .15s}
.btn-primary:hover{transform:scale(1.03)}
.btn-secondary{background:transparent;color:#fff;border:2px solid rgba(255,255,255,.6);padding:14px 32px;border-radius:10px;font-weight:600;font-size:16px;cursor:pointer;font-family:inherit}
/* Social proof */
.proof{background:#f8f4ff;padding:20px;text-align:center;font-size:14px;color:#6b21a8;font-weight:500}
/* Features */
.features{padding:64px 24px;max-width:960px;margin:0 auto}
.features h2{text-align:center;font-size:30px;font-weight:800;margin-bottom:8px}
.features .sub{text-align:center;color:#64748b;margin-bottom:40px}
.feat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px}
.feat-card{background:#f8f4ff;border-radius:14px;padding:24px}
.feat-icon{font-size:32px;margin-bottom:12px}
.feat-card h3{font-size:17px;font-weight:700;margin-bottom:8px}
.feat-card p{font-size:14px;color:#64748b;line-height:1.6}
/* Pricing */
.pricing{background:#0f0f1a;color:#fff;padding:64px 24px}
.pricing h2{text-align:center;font-size:30px;font-weight:800;margin-bottom:8px}
.pricing .sub{text-align:center;color:#94a3b8;margin-bottom:40px}
.price-box{max-width:400px;margin:0 auto;background:linear-gradient(135deg,#7c3aed,#a855f7);border-radius:20px;padding:40px;text-align:center}
.price-box .amount{font-size:56px;font-weight:900;margin:16px 0}
.price-box .orig{font-size:18px;text-decoration:line-through;opacity:.6;margin-bottom:4px}
.price-box ul{list-style:none;margin:24px 0;text-align:right}
.price-box li{padding:8px 0;font-size:15px;border-bottom:1px solid rgba(255,255,255,.1)}
.price-box li::before{content:"✓ ";font-weight:700}
.price-box .cta{background:#fff;color:#7c3aed;border:none;width:100%;padding:16px;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;margin-top:24px;font-family:inherit}
/* Testimonials */
.testi{padding:64px 24px;max-width:960px;margin:0 auto}
.testi h2{text-align:center;font-size:28px;font-weight:800;margin-bottom:40px}
.testi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}
.testi-card{background:#f8f4ff;border-radius:14px;padding:24px}
.stars{color:#f59e0b;font-size:16px;margin-bottom:8px}
.testi-text{font-size:14px;color:#374151;line-height:1.6;margin-bottom:12px}
.testi-author{font-size:13px;font-weight:600;color:#7c3aed}
/* Footer */
footer{background:#0f0f1a;color:#64748b;text-align:center;padding:24px;font-size:13px}
/* Modal */
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}
.modal.open{display:flex}
.mbox{background:#fff;border-radius:20px;padding:36px;width:440px;max-width:92vw;text-align:center}
.mbox h3{font-size:22px;font-weight:800;margin-bottom:8px}
.mbox p{color:#64748b;margin-bottom:24px;font-size:14px}
.mbox input{width:100%;padding:12px 16px;border:1px solid #e2e8f0;border-radius:10px;font-size:14px;font-family:inherit;margin-bottom:12px}
.mbox input:focus{outline:none;border-color:#7c3aed}
.mbox .submit{width:100%;background:#7c3aed;color:#fff;border:none;padding:14px;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
.mbox .cl{background:none;border:none;color:#94a3b8;cursor:pointer;margin-top:12px;font-size:13px}
</style>
</head>
<body>
<nav>
  <div class="logo">✦ منتجي</div>
  <button class="nav-cta" onclick="openModal()">احصل عليه الآن</button>
</nav>
<div class="hero">
  <div class="eyebrow">🔥 العرض محدود</div>
  <h1>المنتج الرقمي الذي<br>يغير حياتك المهنية</h1>
  <div class="sub">دليل شامل + قوالب جاهزة + خطة عمل واضحة — كل ما تحتاجه في ملف واحد</div>
  <div class="hero-btns">
    <button class="btn-primary" onclick="openModal()">احصل عليه الآن 🚀</button>
    <button class="btn-secondary" onclick="document.querySelector('.features').scrollIntoView({behavior:'smooth'})">اعرف أكثر</button>
  </div>
</div>
<div class="proof">⭐ أكثر من 500 شخص استفادوا من هذا الدليل — انضم إليهم اليوم</div>
<div class="features">
  <h2>ماذا ستحصل عليه؟</h2>
  <p class="sub">كل شيء تحتاجه في مكان واحد</p>
  <div class="feat-grid">
    <div class="feat-card"><div class="feat-icon">📘</div><h3>دليل شامل</h3><p>خطوات واضحة ومفصّلة يمكن لأي شخص تطبيقها فوراً بدون خبرة سابقة</p></div>
    <div class="feat-card"><div class="feat-icon">📋</div><h3>قوالب جاهزة</h3><p>قوالب احترافية يمكنك تعديلها بسهولة وتوفير ساعات من العمل</p></div>
    <div class="feat-card"><div class="feat-icon">🎯</div><h3>خطة عمل</h3><p>خطة يومية واضحة تساعدك على التقدم بشكل منتظم ومقيس</p></div>
    <div class="feat-card"><div class="feat-icon">💬</div><h3>دعم مستمر</h3><p>مجتمع داعم وإجابات على أسئلتك خلال 24 ساعة</p></div>
  </div>
</div>
<div class="pricing">
  <h2>السعر</h2>
  <p class="sub">استثمار بسيط، نتائج كبيرة</p>
  <div class="price-box">
    <div class="orig">99 ر.س</div>
    <div class="amount">29 ر.س</div>
    <ul>
      <li>الدليل الكامل (PDF)</li>
      <li>القوالب الجاهزة</li>
      <li>خطة العمل اليومية</li>
      <li>تحديثات مجانية</li>
    </ul>
    <button class="cta" onclick="openModal()">اشترِ الآن — 29 ر.س فقط</button>
  </div>
</div>
<div class="testi">
  <h2>ماذا يقول العملاء؟</h2>
  <div class="testi-grid">
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"استخدمت الدليل وحصلت على وظيفتي خلال أسبوعين فقط. محتوى رائع ومنظم جداً."</p><div class="testi-author">— أحمد م.</div></div>
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"القوالب وفّرت عليّ الكثير من الوقت. الأفضل في هذا المجال بكل صراحة."</p><div class="testi-author">— سارة ك.</div></div>
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"استثمار يستحق كل درهم. الخطة اليومية غيّرت طريقة عملي تماماً."</p><div class="testi-author">— محمد ع.</div></div>
  </div>
</div>
<footer>جميع الحقوق محفوظة © 2025 — منتجي الرقمي</footer>
<div class="modal" id="modal">
  <div class="mbox">
    <h3>🎉 احصل على المنتج الآن</h3>
    <p>أدخل بياناتك وسنرسل لك رابط التحميل فوراً</p>
    <input id="mName" placeholder="اسمك الكريم">
    <input id="mPhone" placeholder="رقم الواتساب (مع رمز الدولة)">
    <button class="submit" onclick="submitOrder()">إتمام الطلب — 29 ر.س</button>
    <br><button class="cl" onclick="closeModal()">إغلاق</button>
  </div>
</div>
<script>
function openModal(){document.getElementById('modal').classList.add('open')}
function closeModal(){document.getElementById('modal').classList.remove('open')}
function submitOrder(){
  var n=document.getElementById('mName').value.trim(),p=document.getElementById('mPhone').value.trim();
  if(!n||!p){alert('يرجى تعبئة جميع الحقول');return;}
  document.querySelector('.mbox').innerHTML='<div style="font-size:56px;margin-bottom:16px">✅</div><h3 style="font-size:22px;font-weight:800;margin-bottom:8px">تم استلام طلبك!</h3><p style="color:#64748b">سيتم التواصل معك على واتساب خلال دقائق لإتمام الدفع وإرسال المنتج.</p>';
}
document.getElementById('modal').addEventListener('click',function(e){if(e.target===this)closeModal()});
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# صفحة هبوط — منتج رقمي
افتح index.html لمعاينة الصفحة. عدّل النصوص والأسعار حسب منتجك.
<<<ENDFILE>>>
<<<META>>>
{"description":"صفحة هبوط احترافية لمنتج رقمي مع نظام طلب","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# ── 5. لوحة تحليلات ──────────────────────────────────────────────────────────
_TEMPLATE_ANALYTICS = """\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>لوحة التحليلات</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.hdr{padding:20px 28px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #1e293b}
.hdr h1{font-size:20px;font-weight:700;display:flex;align-items:center;gap:8px}
.period{display:flex;gap:6px}
.period button{background:#1e293b;border:none;color:#94a3b8;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit}
.period button.active{background:#3b82f6;color:#fff}
.main{padding:24px 28px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.kpi{background:#1e293b;border-radius:12px;padding:20px}
.kpi .l{font-size:12px;color:#64748b;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.kpi .v{font-size:28px;font-weight:800}
.kpi .chg{font-size:12px;margin-top:4px}
.up{color:#22c55e}.dn{color:#ef4444}
.charts{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:24px}
.chart-card{background:#1e293b;border-radius:12px;padding:20px}
.chart-card h3{font-size:14px;font-weight:600;margin-bottom:16px;color:#94a3b8}
canvas{width:100%!important}
.table-card{background:#1e293b;border-radius:12px;padding:20px}
.table-card h3{font-size:14px;font-weight:600;margin-bottom:16px;color:#94a3b8}
table{width:100%;border-collapse:collapse}
th{text-align:right;padding:8px 12px;font-size:11px;color:#64748b;border-bottom:1px solid #334155}
td{padding:10px 12px;font-size:13px;border-bottom:1px solid #1e293b}
.trend{display:inline-block;width:60px;height:6px;border-radius:3px;background:#334155;position:relative;overflow:hidden}
.trend-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,#3b82f6,#8b5cf6)}
</style>
</head>
<body>
<div class="hdr">
  <h1>📊 لوحة التحليلات</h1>
  <div class="period">
    <button class="active">اليوم</button>
    <button onclick="setPeriod(this,'7d')">7 أيام</button>
    <button onclick="setPeriod(this,'30d')">30 يوم</button>
  </div>
</div>
<div class="main">
  <div class="kpis">
    <div class="kpi"><div class="l">💰 الإيرادات</div><div class="v" id="k0">12,450</div><div class="chg up">↑ 18% عن الأمس</div></div>
    <div class="kpi"><div class="l">👥 الزوار</div><div class="v" id="k1">3,284</div><div class="chg up">↑ 7%</div></div>
    <div class="kpi"><div class="l">🛒 الطلبات</div><div class="v" id="k2">127</div><div class="chg dn">↓ 3%</div></div>
    <div class="kpi"><div class="l">⭐ التقييم</div><div class="v" id="k3">4.8</div><div class="chg up">↑ 0.2</div></div>
  </div>
  <div class="charts">
    <div class="chart-card"><h3>الإيرادات اليومية</h3><canvas id="lineChart" height="180"></canvas></div>
    <div class="chart-card"><h3>مصادر الزوار</h3><canvas id="pieChart" height="180"></canvas></div>
  </div>
  <div class="table-card">
    <h3>أفضل المنتجات</h3>
    <table>
      <thead><tr><th>المنتج</th><th>المبيعات</th><th>الإيرادات</th><th>الأداء</th></tr></thead>
      <tbody id="tbl"></tbody>
    </table>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
Chart.defaults.color='#64748b';Chart.defaults.borderColor='#334155';
var products=[
  {name:'المنتج الرئيسي',sales:89,rev:12450,pct:85},
  {name:'الإضافة الاحترافية',sales:34,rev:4760,pct:64},
  {name:'حزمة المبتدئين',sales:56,rev:2240,pct:42},
  {name:'الاشتراك السنوي',sales:12,rev:7200,pct:78},
];
document.getElementById('tbl').innerHTML=products.map(function(p){
  return'<tr><td>'+p.name+'</td><td>'+p.sales+'</td><td>'+p.rev.toLocaleString('ar')+' ر.س</td><td><div class="trend"><div class="trend-fill" style="width:'+p.pct+'%"></div></div></td></tr>';
}).join('');
var lCtx=document.getElementById('lineChart').getContext('2d');
new Chart(lCtx,{type:'line',data:{labels:['السبت','الأحد','الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة'],datasets:[{label:'الإيرادات',data:[8200,9400,7800,11200,10500,12450,9800],borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,.1)',tension:.4,fill:true}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{grid:{color:'#1e293b'}}}}});
var pCtx=document.getElementById('pieChart').getContext('2d');
new Chart(pCtx,{type:'doughnut',data:{labels:['إنستغرام','واتساب','بحث جوجل','مباشر'],datasets:[{data:[42,28,18,12],backgroundColor:['#3b82f6','#8b5cf6','#06b6d4','#22c55e'],borderWidth:0}]},options:{responsive:true,plugins:{legend:{position:'bottom'}}}});
function setPeriod(btn,p){document.querySelectorAll('.period button').forEach(function(b){b.classList.remove('active')});btn.classList.add('active');}
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# لوحة تحليلات
لوحة بيانات تفاعلية — افتح index.html في متصفح حديث.
<<<ENDFILE>>>
<<<META>>>
{"description":"لوحة تحليلات تفاعلية مع رسوم بيانية","run_command":"open index.html","language":"html"}
<<<ENDMETA>>>
"""

# ── Dynamic landing page builder ─────────────────────────────────────────────


def _parse_landing_vars(prompt: str) -> dict:
    """Extract product info from any Arabic/English prompt for a landing page."""
    v: dict = {
        "name":     "منتجي الرقمي",
        "tagline":  "ابدأ رحلتك نحو النجاح",
        "price":    "29",
        "currency": "درهم",
        "features": [],
        "headline": "تعبت من البحث بلا نتيجة؟",
        "headline2": "الحل أصبح بين يديك",
        "sub":      "كل ما تحتاجه في ملف واحد",
        "delivery": "رابط تحميل مباشر عبر واتساب",
    }

    # ── Product name ──────────────────────────────────────────────────────────
    m = re.search(r'اسم[^:\n]*:\s*([^\n]{2,60})', prompt)
    if m:
        v["name"] = m.group(1).strip().strip('"\'"«»')

    # ── Tagline / slogan ──────────────────────────────────────────────────────
    m = re.search(r'الشعار[^:\n]*:\s*([^\n]{2,80})', prompt)
    if m:
        v["tagline"] = m.group(1).strip()

    # ── Price & currency ──────────────────────────────────────────────────────
    m = re.search(r'(\d+)\s*(درهم|ريال|دولار|جنيه|ج\.م|د\.إ)', prompt)
    if m:
        v["price"]    = m.group(1)
        v["currency"] = m.group(2)

    # ── Feature bullets (✓ ✔ * • or plain * lines) ───────────────────────────
    feats = re.findall(r'[✓✔•]\s*([^\n]{3,80})', prompt)
    if not feats:
        feats = re.findall(r'^\s*\*\s+(.{3,80})$', prompt, re.MULTILINE)
    if feats:
        v["features"] = [f.strip() for f in feats[:6]]
    else:
        # fall back to numbered or dashed lines
        feats = re.findall(r'^\s*\d+[.)]\s+(.{3,60})$', prompt, re.MULTILINE)
        v["features"] = [f.strip() for f in feats[:6]]

    if not v["features"]:
        v["features"] = ["محتوى شامل وعملي", "قابل للتطبيق فوراً", "يوفّر عليك ساعات من البحث"]

    # ── Ad headline (line after "العنوان:") ───────────────────────────────────
    m = re.search(r'العنوان[^:\n]*:\s*\n?((?:[^\n]+\n?){1,3})', prompt)
    if m:
        lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
        if lines:
            v["headline"]  = lines[0][:80]
        if len(lines) > 1:
            v["headline2"] = lines[1][:80]

    # ── Sub / description ─────────────────────────────────────────────────────
    m = re.search(r'النص[^:\n]*:\s*\n?([^\n]{10,120})', prompt)
    if m:
        v["sub"] = m.group(1).strip()[:120]

    # ── Delivery method ────────────────────────────────────────────────────────
    m = re.search(r'طريقة التسليم[\s\S]{0,20}:\s*\n?([\s\S]{5,100}?)(?:\n\n|\Z)', prompt)
    if m:
        v["delivery"] = m.group(1).strip()[:100]

    return v


def _build_landing(prompt: str) -> str:
    """Generate a fully customised landing-page HTML from any product prompt."""
    v   = _parse_landing_vars(prompt)
    name      = v["name"]
    tagline   = v["tagline"]
    price     = v["price"]
    currency  = v["currency"]
    headline  = v["headline"]
    headline2 = v["headline2"]
    sub       = v["sub"]
    delivery  = v["delivery"]
    features  = v["features"]

    feat_icons = ["📘", "📋", "🎯", "💡", "🗓️", "🌐"]
    feat_html  = "\n".join(
        f'    <div class="feat-card">'
        f'<div class="feat-icon">{feat_icons[i % len(feat_icons)]}</div>'
        f'<p>{feat}</p></div>'
        for i, feat in enumerate(features)
    )
    price_items = "\n".join(
        f"      <li>{feat}</li>" for feat in features
    )

    html = f"""\
<<<FILE: index.html>>>
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;color:#1a1a2e;background:#fff}}
nav{{background:#fff;padding:16px 32px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;box-shadow:0 1px 8px rgba(0,0,0,.06);z-index:10}}
.logo{{font-size:20px;font-weight:800;color:#7c3aed}}
.nav-cta{{background:#7c3aed;color:#fff;border:none;padding:10px 22px;border-radius:8px;cursor:pointer;font-weight:600;font-size:14px;font-family:inherit}}
.hero{{background:linear-gradient(135deg,#7c3aed 0%,#a855f7 50%,#ec4899 100%);color:#fff;padding:80px 24px;text-align:center}}
.hero .eyebrow{{font-size:13px;font-weight:600;letter-spacing:.08em;opacity:.85;margin-bottom:16px;text-transform:uppercase}}
.hero h1{{font-size:clamp(26px,5vw,48px);font-weight:900;line-height:1.2;margin-bottom:12px}}
.hero h2{{font-size:clamp(18px,3vw,28px);font-weight:700;opacity:.9;margin-bottom:20px}}
.hero .sub{{font-size:16px;opacity:.85;max-width:560px;margin:0 auto 32px;line-height:1.6}}
.hero-btns{{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}}
.btn-p{{background:#fff;color:#7c3aed;border:none;padding:14px 32px;border-radius:10px;font-weight:700;font-size:16px;cursor:pointer;font-family:inherit;transition:transform .15s}}
.btn-p:hover{{transform:scale(1.03)}}
.btn-s{{background:transparent;color:#fff;border:2px solid rgba(255,255,255,.6);padding:14px 32px;border-radius:10px;font-weight:600;font-size:15px;cursor:pointer;font-family:inherit}}
.proof{{background:#f8f4ff;padding:18px;text-align:center;font-size:14px;color:#6b21a8;font-weight:500}}
.features{{padding:60px 24px;max-width:960px;margin:0 auto}}
.features h2{{text-align:center;font-size:28px;font-weight:800;margin-bottom:8px}}
.features .sub{{text-align:center;color:#64748b;margin-bottom:36px}}
.feat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}}
.feat-card{{background:#f8f4ff;border-radius:14px;padding:22px;display:flex;align-items:flex-start;gap:14px}}
.feat-icon{{font-size:28px;flex-shrink:0}}
.feat-card p{{font-size:14px;color:#374151;line-height:1.6;font-weight:500}}
.pricing{{background:#0f0f1a;color:#fff;padding:60px 24px}}
.pricing h2{{text-align:center;font-size:28px;font-weight:800;margin-bottom:8px}}
.pricing .sub{{text-align:center;color:#94a3b8;margin-bottom:36px}}
.price-box{{max-width:400px;margin:0 auto;background:linear-gradient(135deg,#7c3aed,#a855f7);border-radius:20px;padding:36px;text-align:center}}
.price-box .amount{{font-size:52px;font-weight:900;margin:12px 0}}
.price-box ul{{list-style:none;margin:20px 0;text-align:right}}
.price-box li{{padding:8px 0;font-size:14px;border-bottom:1px solid rgba(255,255,255,.15)}}
.price-box li::before{{content:"✓ ";font-weight:700}}
.price-box .cta{{background:#fff;color:#7c3aed;border:none;width:100%;padding:14px;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;margin-top:20px;font-family:inherit}}
.delivery{{background:#f8f4ff;padding:24px;max-width:600px;margin:0 auto 60px;border-radius:14px;text-align:center}}
.delivery h3{{font-weight:700;margin-bottom:8px}}
.delivery p{{color:#64748b;font-size:14px;line-height:1.6}}
.testi{{padding:60px 24px;max-width:960px;margin:0 auto}}
.testi h2{{text-align:center;font-size:26px;font-weight:800;margin-bottom:36px}}
.testi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}}
.testi-card{{background:#f8f4ff;border-radius:14px;padding:22px}}
.stars{{color:#f59e0b;font-size:15px;margin-bottom:8px}}
.testi-text{{font-size:14px;color:#374151;line-height:1.6;margin-bottom:10px}}
.testi-author{{font-size:13px;font-weight:600;color:#7c3aed}}
footer{{background:#0f0f1a;color:#64748b;text-align:center;padding:20px;font-size:13px}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}}
.modal.open{{display:flex}}
.mbox{{background:#fff;border-radius:20px;padding:32px;width:440px;max-width:92vw;text-align:center}}
.mbox h3{{font-size:20px;font-weight:800;margin-bottom:8px}}
.mbox p{{color:#64748b;margin-bottom:20px;font-size:14px}}
.mbox input{{width:100%;padding:12px 16px;border:1px solid #e2e8f0;border-radius:10px;font-size:14px;font-family:inherit;margin-bottom:10px}}
.mbox input:focus{{outline:none;border-color:#7c3aed}}
.mbox .submit{{width:100%;background:#7c3aed;color:#fff;border:none;padding:14px;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}}
.mbox .cl{{background:none;border:none;color:#94a3b8;cursor:pointer;margin-top:10px;font-size:13px}}
</style>
</head>
<body>
<nav>
  <div class="logo">✦ {name}</div>
  <button class="nav-cta" onclick="openModal()">احصل عليه الآن</button>
</nav>
<div class="hero">
  <div class="eyebrow">🔥 عرض محدود</div>
  <h1>{headline}</h1>
  <h2>{headline2}</h2>
  <div class="sub">{sub}</div>
  <div class="hero-btns">
    <button class="btn-p" onclick="openModal()">احصل عليه الآن 🚀</button>
    <button class="btn-s" onclick="document.querySelector('.features').scrollIntoView({{behavior:'smooth'}})">اعرف أكثر</button>
  </div>
</div>
<div class="proof">⭐ {tagline}</div>
<div class="features">
  <h2>ماذا ستحصل عليه؟</h2>
  <p class="sub">كل ما تحتاجه في مكان واحد</p>
  <div class="feat-grid">
{feat_html}
  </div>
</div>
<div class="pricing">
  <h2>السعر</h2>
  <p class="sub">استثمار بسيط، نتائج حقيقية</p>
  <div class="price-box">
    <div class="amount">{price} {currency}</div>
    <ul>
{price_items}
    </ul>
    <button class="cta" onclick="openModal()">اشترِ الآن — {price} {currency} فقط</button>
  </div>
</div>
<div style="background:#fff;padding:40px 24px">
  <div class="delivery">
    <h3>📦 طريقة التسليم</h3>
    <p>{delivery}</p>
  </div>
</div>
<div class="testi">
  <h2>ماذا يقول العملاء؟</h2>
  <div class="testi-grid">
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"محتوى احترافي وعملي جداً، استفدت منه كثيراً وطبّقته فوراً."</p><div class="testi-author">— أحمد م.</div></div>
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"وفّر عليّ وقتاً وجهداً كبيراً. أنصح به كل شخص يريد نتائج سريعة."</p><div class="testi-author">— سارة ك.</div></div>
    <div class="testi-card"><div class="stars">★★★★★</div><p class="testi-text">"استثمار يستحق كل {currency}. النتائج تتكلم عن نفسها."</p><div class="testi-author">— محمد ع.</div></div>
  </div>
</div>
<footer>جميع الحقوق محفوظة © 2025 — {name}</footer>
<div class="modal" id="modal">
  <div class="mbox">
    <h3>🎉 احصل على {name} الآن</h3>
    <p>أدخل بياناتك وسنرسل لك رابط التحميل فوراً على واتساب</p>
    <input id="mName" placeholder="اسمك الكريم">
    <input id="mPhone" type="tel" placeholder="رقم الواتساب (مع رمز الدولة)">
    <button class="submit" onclick="submitOrder()">إتمام الطلب — {price} {currency}</button>
    <br><button class="cl" onclick="closeModal()">إغلاق</button>
  </div>
</div>
<script>
function openModal(){{document.getElementById('modal').classList.add('open')}}
function closeModal(){{document.getElementById('modal').classList.remove('open')}}
function submitOrder(){{
  var n=document.getElementById('mName').value.trim(),p=document.getElementById('mPhone').value.trim();
  if(!n||!p){{alert('يرجى تعبئة جميع الحقول');return;}}
  document.querySelector('.mbox').innerHTML='<div style="font-size:56px;margin-bottom:16px">✅</div><h3 style="font-size:20px;font-weight:800;margin-bottom:8px">تم استلام طلبك!</h3><p style="color:#64748b">سيتم التواصل معك على واتساب خلال دقائق لإتمام الدفع وإرسال {name}.</p>';
}}
document.getElementById('modal').addEventListener('click',function(e){{if(e.target===this)closeModal()}});
</script>
</body></html>
<<<ENDFILE>>>
<<<FILE: README.md>>>
# {name}
صفحة الهبوط — افتح index.html في متصفح حديث.
الشعار: {tagline}
السعر: {price} {currency}
<<<ENDFILE>>>
<<<META>>>
{{"description":"{name} — صفحة هبوط احترافية","run_command":"open index.html","language":"html"}}
<<<ENDMETA>>>
"""
    return html


# ═══════════════════════════════════════════════════════════════════════════════
#  Plan-based multi-file generation
# ═══════════════════════════════════════════════════════════════════════════════

def _slug(name: str) -> str:
    """Convert any name (Arabic or English) to a URL-safe ASCII slug."""
    try:
        norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    except Exception:
        norm = ""
    cleaned = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    # Fallback for non-Latin names (Arabic etc.): stable hash-based slug
    return cleaned or f"page{abs(hash(name)) % 9000 + 1000}"


def _pascal(name: str) -> str:
    """Convert any name to a PascalCase JS identifier."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_name).split()
    if not words:
        return f"Page{abs(hash(name)) % 9000 + 1000}"
    return "".join(w.capitalize() for w in words)


def _build_from_plan(prompt: str, plan_data: dict) -> str:
    """
    Generate a plan-driven multi-file HTML application for the dev-mock path.

    Always produces (minimum 4 files):
      - index.html          entry point with sidebar navigation
      - styles.css          RTL-aware base styles
      - app.js              client-side routing + state management
      - README.md           project summary drawn from the approved plan

    Conditionally produces (based on plan contents):
      - pages/<slug>.js     one per plan page (up to 6), renders page content
      - data/schema.sql     CREATE TABLE stubs for each database_table
      - api/routes.json     route catalogue for each api_route

    Typical total: 7–11 files — proving Plan → Generator → multi-file → Runtime.
    """
    app_name   = plan_data.get("name", "My App")
    description = plan_data.get("description", prompt[:100])
    pages       = (plan_data.get("pages", []) or [])[:6]
    db_tables   = plan_data.get("database_tables", []) or []
    api_routes  = plan_data.get("api_routes", []) or []
    agents      = plan_data.get("agents", []) or []
    workflows   = plan_data.get("workflows", []) or []
    integrations = plan_data.get("integrations", []) or []
    tech_stack  = plan_data.get("tech_stack", {}) or {}

    if not pages:
        pages = ["Home"]

    # Build the output incrementally
    out: list[str] = []

    def file_block(path: str, content: str) -> None:
        out.append(f"<<<FILE: {path}>>>\n{content}\n<<<ENDFILE>>>")

    # ── 1. index.html ─────────────────────────────────────────────────────────
    nav_items = "\n        ".join(
        f'<li><a href="#" class="nav-link" data-page="{_slug(p)}" onclick="showPage(\'{_slug(p)}\');return false;">{p}</a></li>'
        for p in pages
    )
    page_containers = "\n    ".join(
        f'<section id="page-{_slug(p)}" class="page-section" hidden></section>'
        for p in pages
    )
    page_scripts = "\n  ".join(
        f'<script src="pages/{_slug(p)}.js"></script>'
        for p in pages
    )
    first_slug = _slug(pages[0])

    index_html = f"""\
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{app_name}</title>
<link rel="stylesheet" href="styles.css">
{page_scripts}
<script src="app.js" defer></script>
</head>
<body>
<div class="layout">
  <nav class="sidebar">
    <div class="logo">✦ {app_name}</div>
    <ul class="nav-links">
        {nav_items}
    </ul>
    <div class="sidebar-footer">{description[:60]}</div>
  </nav>
  <main class="content">
    <header class="topbar">
      <h1 id="page-title">{pages[0]}</h1>
    </header>
    <div class="page-wrapper">
    {page_containers}
    </div>
  </main>
</div>
</body>
</html>"""
    file_block("index.html", index_html)

    # ── 2. styles.css ─────────────────────────────────────────────────────────
    styles_css = """\
/* ── Reset & variables ── */
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f8fafc;--sidebar:#0f172a;--sidebar-fg:#94a3b8;
  --sidebar-hover:#1e293b;--sidebar-active:#6366f1;
  --fg:#1e293b;--border:#e2e8f0;--card:#fff;
  --accent:#6366f1;--radius:12px;
}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg);height:100vh;overflow:hidden}

/* ── Layout ── */
.layout{display:flex;height:100vh}
.sidebar{width:240px;background:var(--sidebar);color:var(--sidebar-fg);
  display:flex;flex-direction:column;gap:0;flex-shrink:0}
.logo{padding:20px 20px 8px;font-size:18px;font-weight:800;color:#fff}
.nav-links{list-style:none;flex:1;padding:8px 12px}
.nav-links li{margin:2px 0}
.nav-link{display:block;padding:10px 14px;border-radius:8px;color:var(--sidebar-fg);
  text-decoration:none;font-size:14px;transition:background .15s,color .15s}
.nav-link:hover{background:var(--sidebar-hover);color:#e2e8f0}
.nav-link.active{background:var(--accent);color:#fff}
.sidebar-footer{padding:12px 20px 20px;font-size:11px;color:#475569;line-height:1.5}
.content{flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{padding:16px 24px;border-bottom:1px solid var(--border);background:var(--card)}
.topbar h1{font-size:18px;font-weight:700;color:var(--fg)}
.page-wrapper{flex:1;overflow-y:auto;padding:24px}
.page-section{animation:fadeIn .2s ease}

/* ── Page content defaults ── */
.page-header{margin-bottom:20px}
.page-header h2{font-size:22px;font-weight:700;margin-bottom:6px}
.page-header p{color:#64748b;font-size:14px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:var(--card);border-radius:var(--radius);padding:20px;
  box-shadow:0 1px 4px rgba(0,0,0,.06)}
.stat-card .value{font-size:28px;font-weight:800;color:var(--accent)}
.stat-card .label{font-size:12px;color:#94a3b8;margin-top:4px}
.data-table{width:100%;border-collapse:collapse;background:var(--card);
  border-radius:var(--radius);overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.data-table th{text-align:right;padding:12px 16px;font-size:12px;
  color:#64748b;border-bottom:1px solid var(--border);background:#f8fafc}
.data-table td{padding:12px 16px;font-size:13px;border-bottom:1px solid var(--border)}
.btn{padding:8px 16px;border:none;border-radius:8px;cursor:pointer;
  font-size:13px;font-weight:600;font-family:inherit;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:var(--accent);color:#fff}
.btn-secondary{background:#f1f5f9;color:var(--fg)}
.empty-state{text-align:center;padding:48px 24px;color:#94a3b8}
.empty-state .icon{font-size:48px;margin-bottom:12px}
.empty-state p{font-size:14px}

@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}"""
    file_block("styles.css", styles_css)

    # ── 3. app.js ─────────────────────────────────────────────────────────────
    pages_list_js = ", ".join(f'"{_slug(p)}"' for p in pages)
    page_title_map = json.dumps({_slug(p): p for p in pages}, ensure_ascii=False)

    app_js = f"""\
/* ── {app_name} — Client-side router ── */
const PAGES = [{pages_list_js}];
const PAGE_TITLES = {page_title_map};

function showPage(pageId) {{
  // Hide all sections
  document.querySelectorAll('.page-section').forEach(function(el) {{ el.hidden = true; }});
  // Show target
  var target = document.getElementById('page-' + pageId);
  if (target) {{
    target.hidden = false;
    // Render via page module if available
    var fnKey = 'renderPage_' + pageId;
    if (typeof window[fnKey] === 'function') {{
      if (!target.dataset.rendered) {{
        window[fnKey](target);
        target.dataset.rendered = '1';
      }}
    }}
  }}
  // Update nav active state
  document.querySelectorAll('.nav-link').forEach(function(link) {{
    link.classList.toggle('active', link.dataset.page === pageId);
  }});
  // Update topbar title
  var titleEl = document.getElementById('page-title');
  if (titleEl) titleEl.textContent = PAGE_TITLES[pageId] || pageId;
  // Store current page
  try {{ sessionStorage.setItem('currentPage', pageId); }} catch(e) {{}}
}}

document.addEventListener('DOMContentLoaded', function() {{
  var saved = null;
  try {{ saved = sessionStorage.getItem('currentPage'); }} catch(e) {{}}
  showPage((saved && PAGES.includes(saved)) ? saved : '{first_slug}');
}});"""
    file_block("app.js", app_js)

    # ── 4. pages/<slug>.js ────────────────────────────────────────────────────
    for idx, page in enumerate(pages):
        slug   = _slug(page)
        icon   = ["🏠", "📦", "🛒", "💳", "📋", "⚙️"][idx % 6]
        # Provide a page-specific stat count so each page looks different
        count1 = (idx + 1) * 7 + 3
        count2 = (idx + 1) * 4 + 1

        page_js = f"""\
/* ── Page: {page} ── */
window['renderPage_{slug}'] = function(container) {{
  container.innerHTML = [
    '<div class="page-header">',
    '  <h2>{icon} {page}</h2>',
    '  <p>إدارة بيانات {page} وعرض المعلومات المرتبطة بها.</p>',
    '</div>',
    '<div class="card-grid">',
    '  <div class="stat-card"><div class="value">{count1}</div><div class="label">إجمالي السجلات</div></div>',
    '  <div class="stat-card"><div class="value">{count2}</div><div class="label">إضافة هذا الأسبوع</div></div>',
    '  <div class="stat-card"><div class="value">100%</div><div class="label">نسبة الاكتمال</div></div>',
    '</div>',
    '<div style="display:flex;gap:10px;margin-bottom:16px">',
    '  <button class="btn btn-primary" onclick="alert(\'قريباً: إضافة سجل جديد\')">+ إضافة</button>',
    '  <button class="btn btn-secondary">تصدير</button>',
    '</div>',
    '<table class="data-table">',
    '  <thead><tr><th>#</th><th>الاسم</th><th>التاريخ</th><th>الحالة</th></tr></thead>',
    '  <tbody>',
    '    <tr><td>1</td><td>سجل تجريبي أول</td><td>2026-09-13</td><td>✅ نشط</td></tr>',
    '    <tr><td>2</td><td>سجل تجريبي ثانٍ</td><td>2026-09-12</td><td>✅ نشط</td></tr>',
    '    <tr><td>3</td><td>سجل تجريبي ثالث</td><td>2026-09-11</td><td>⏸ معلّق</td></tr>',
    '  </tbody>',
    '</table>',
  ].join('\\n');
}};"""
        file_block(f"pages/{slug}.js", page_js)

    # ── 5. data/schema.sql (if db_tables present) ────────────────────────────
    if db_tables:
        safe_tables = [
            re.sub(r"[^a-z0-9_]", "_",
                   unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().replace(" ", "_"))
            or f"table_{i}"
            for i, t in enumerate(db_tables[:8])
        ]
        sql_stmts = "\n\n".join(
            f"CREATE TABLE IF NOT EXISTS {t} (\n"
            f"  id          SERIAL PRIMARY KEY,\n"
            f"  name        TEXT    NOT NULL DEFAULT '',\n"
            f"  status      TEXT    NOT NULL DEFAULT 'active',\n"
            f"  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),\n"
            f"  updated_at  TIMESTAMP NOT NULL DEFAULT NOW()\n"
            f");"
            for t in safe_tables
        )
        schema_sql = f"-- {app_name} — Database Schema\n-- Generated from approved build plan\n\n{sql_stmts}"
        file_block("data/schema.sql", schema_sql)

    # ── 6. api/routes.json (if api_routes present) ───────────────────────────
    if api_routes:
        routes_doc = {
            "app": app_name,
            "version": "1.0.0",
            "description": description,
            "routes": [
                {
                    "path": r,
                    "methods": ["GET", "POST"],
                    "description": f"Resource endpoint: {r}",
                    "auth": "Bearer token required",
                }
                for r in api_routes[:8]
            ],
        }
        file_block("api/routes.json", json.dumps(routes_doc, ensure_ascii=False, indent=2))

    # ── 7. README.md ──────────────────────────────────────────────────────────
    readme_lines = [
        f"# {app_name}",
        "",
        f"> {description}",
        "",
        "## Tech Stack",
    ]
    for k, v in (tech_stack.items() if tech_stack else []):
        if v:
            readme_lines.append(f"- **{k.title()}**: {v}")
    if not tech_stack:
        readme_lines += ["- HTML / CSS / JavaScript (no build step)"]
    readme_lines += ["", "## Pages"]
    for p in pages:
        readme_lines.append(f"- `{p}`")
    if db_tables:
        readme_lines += ["", "## Database Tables"]
        for t in db_tables:
            readme_lines.append(f"- `{t}`")
    if api_routes:
        readme_lines += ["", "## API Routes"]
        for r in api_routes:
            readme_lines.append(f"- `{r}`")
    if agents:
        readme_lines += ["", "## AI Agents"]
        for a in agents:
            readme_lines.append(f"- {a}")
    if workflows:
        readme_lines += ["", "## Workflows"]
        for w in workflows:
            readme_lines.append(f"- {w}")
    if integrations:
        readme_lines += ["", "## Integrations"]
        for i in integrations:
            readme_lines.append(f"- {i}")
    readme_lines += [
        "",
        "## Getting Started",
        "",
        "1. Open `index.html` in a modern browser.",
        "2. Navigate between pages using the sidebar.",
        "3. No build step required for the development preview.",
        "",
        "## File Structure",
        "",
        "```",
        "index.html          # Entry point with sidebar navigation",
        "styles.css          # RTL-aware base styles",
        "app.js              # Client-side router",
    ]
    for p in pages:
        readme_lines.append(f"pages/{_slug(p)}.js       # {p} page module")
    if db_tables:
        readme_lines.append("data/schema.sql     # Database schema")
    if api_routes:
        readme_lines.append("api/routes.json     # API route catalogue")
    readme_lines.append("```")
    file_block("README.md", "\n".join(readme_lines))

    # ── META ──────────────────────────────────────────────────────────────────
    meta_obj = {
        "description": description[:120],
        "run_command": "open index.html",
        "language": "html",
    }
    out.append(f"<<<META>>>\n{json.dumps(meta_obj, ensure_ascii=False)}\n<<<ENDMETA>>>")

    return "\n".join(out)


# ── Keyword → template map ────────────────────────────────────────────────────

_KEYWORDS: list[tuple[str, str]] = [
    # (regex_pattern, template_key)
    # E-commerce / متجر
    (r"متجر|shop|store|تسوق|سلة|ecommerce|e-commerce|بضاعة", "ecommerce"),
    # Landing / digital product / صفحة هبوط
    (r"صفحة هبوط|landing|منتج رقمي|pdf|دليل|كورس|course|ebook|هبوط|تسويق|درهم|ريال|إعلان|واتساب بزنس|خطة.*يوم|يوم.*خطة|اسم.*المشروع|الشعار|سعر البيع|قنوات البيع", "landing"),
    # Analytics / تحليلات
    (r"تحليل|analytics|dashboard|لوحة.*بيانات|إحصاء|إحصائيات|رسم بياني|chart|report|تقرير", "analytics"),
    # Tasks / مهام
    (r"مهام|tasks|todo|مشاريع|kanban|project|جدول.*أعمال|أعمال.*جدول|منظم", "tasks"),
    # CRM
    (r"crm|علاقات.*عملاء|عملاء.*علاقات|صفقات|مبيعات|leads|عميل|sales|contacts", "crm"),
]

_STATIC_TEMPLATES: dict[str, str] = {
    "crm":       _TEMPLATE_CRM,
    "ecommerce": _TEMPLATE_ECOMMERCE,
    "tasks":     _TEMPLATE_TASKS,
    "analytics": _TEMPLATE_ANALYTICS,
}


def _select_template(prompt: str) -> str:
    """
    Pick the best generation strategy for the prompt.

    Priority:
      1. Approved plan XML (<approved_plan>…</approved_plan>) — triggers
         plan-based multi-file generation that mirrors the user-reviewed
         Build Plan (pages, DB, API routes, agents, workflows, integrations).
         This replaces the old "2-file keyword template" path for builds that
         started from the plan-approval flow.
      2. Keyword matching — falls back to the existing static templates when
         no plan XML is present (backward-compatible for direct /api/build/stream
         calls without a plan, e.g. the BuildTab in the dev panel).
    """
    # ── 1. Approved plan takes priority ──────────────────────────────────────
    plan_match = re.search(r"<approved_plan>\s*([\s\S]*?)\s*</approved_plan>", prompt)
    if plan_match:
        try:
            plan_data = json.loads(plan_match.group(1))
            # Extract the user's original prompt (text after the XML wrapper)
            user_prompt = re.sub(r"^[\s\S]*?</approved_plan>\s*", "", prompt).strip()
            user_prompt = re.sub(r"^Build this application:\s*", "", user_prompt).strip()
            if not user_prompt:
                user_prompt = plan_data.get("description", prompt[:80])
            log.info(
                "DevMockProvider: plan-based generation app=%r pages=%d tables=%d routes=%d",
                plan_data.get("name", "?"),
                len(plan_data.get("pages", [])),
                len(plan_data.get("database_tables", [])),
                len(plan_data.get("api_routes", [])),
            )
            return _build_from_plan(user_prompt, plan_data)
        except Exception as exc:
            log.warning(
                "DevMockProvider: plan parse failed (%s) — falling back to keyword templates",
                exc,
            )

    # ── 2. Keyword-based templates (legacy / direct-call path) ───────────────
    for pattern, key in _KEYWORDS:
        if re.search(pattern, prompt, re.IGNORECASE):
            log.info("DevMockProvider: matched key=%r snippet=%r", key, prompt[:80])
            if key == "landing":
                return _build_landing(prompt)
            return _STATIC_TEMPLATES[key]
    log.info("DevMockProvider: no keyword match — building landing from prompt")
    return _build_landing(prompt)   # best generic default for any product description


# ── Provider ──────────────────────────────────────────────────────────────────

class DevMockProvider(BaseProvider):
    """
    Development mock provider — free, no API key, no Anthropic credits needed.

    Streams a prompt-aware application in the build-stream <<<FILE:>>> format
    so the real SSE pipeline (parser → file-write → SSE events) is exercised
    end-to-end.  Template selection is keyword-based (Arabic + English).

    Intentionally NOT in platform_registry.default() — only reachable via
    provider="dev_mock", which build.py sets for the owner account.
    """

    provider_id = "dev_mock"

    def _env_key(self) -> str:
        return ""  # no env var needed

    @property
    def is_available(self) -> bool:
        return True

    def default_model(self) -> str:
        return "dev-mock-v2"

    def cost_per_token(self, model: str) -> tuple[float, float]:
        return (0.0, 0.0)

    def _prompt_from(self, request: CompletionRequest) -> str:
        """Extract user prompt text from the request messages."""
        for msg in reversed(request.messages):
            if msg.role == "user":
                return msg.content if isinstance(msg.content, str) else ""
        return ""

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        prompt = self._prompt_from(request)
        output = _select_template(prompt)
        log.info("DevMockProvider.complete: %d chars", len(output))
        return CompletionResponse(
            content=output,
            finish_reason="stop",
            usage=UsageStats(
                input_tokens=0,
                output_tokens=len(output) // 4,
                total_tokens=len(output) // 4,
                provider=self.provider_id,
                model=self.default_model(),
                cost_usd=0.0,
            ),
        )

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        prompt = self._prompt_from(request)
        text = _select_template(prompt)
        log.info("DevMockProvider.stream: %d chars", len(text))
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
