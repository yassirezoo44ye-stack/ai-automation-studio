'use strict';
const $ = id => document.getElementById(id);
let products = [], user = null, currency = 'AED', cart = {}, orderKey = null;
try { cart = JSON.parse(localStorage.getItem('store.cart.v1') || '{}'); } catch { cart = {}; }
function notice(message) { $('notice').textContent = message; }
function node(tag, text, className) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; }
function action(text, run) { const b = node('button', text); b.type = 'button'; b.onclick = () => safe(run); return b; }
async function safe(run) { try { await run(); } catch(e) { notice(e.message); } }
async function api(path, method = 'GET', body) {
  const response = await fetch(`api/${path}`, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  let data; try { data = await response.json(); } catch { throw new Error('تعذّر الاتصال بالمتجر'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'تحقق من المدخلات وحاول مجددًا');
  return data;
}
const statusLabel = status => ({pending:'بانتظار التأكيد',confirmed:'تم التأكيد',shipped:'قيد التوصيل',delivered:'تم التسليم',cancelled:'ملغي'}[status] || status);
const money = cents => new Intl.NumberFormat('ar-AE', { style: 'currency', currency }).format(cents / 100);
function persist() { try { localStorage.setItem('store.cart.v1', JSON.stringify(cart)); } catch { /* Opaque Flow preview keeps the cart in memory; orders stay in the database. */ } $('count').textContent = Object.values(cart).reduce((a,b) => a + Number(b), 0); }
function show(id) {
  if (id === 'admin' && !user?.admin) return;
  document.querySelectorAll('main > section').forEach(s => s.hidden = s.id !== id);
  if (id === 'cart') renderCart();
  if (id === 'orders') safe(loadOrders);
  if (id === 'admin') safe(loadAdmin);
}
async function refreshProducts() { products = await api('products'); renderProducts(); persist(); }
function renderProducts() {
  const q = $('search').value.trim().toLocaleLowerCase(); $('products').replaceChildren();
  for (const product of products.filter(p => `${p.title} ${p.description}`.toLocaleLowerCase().includes(q))) {
    const card = node('article', undefined, 'card'); card.append(node('h3', product.title), node('p', product.description), node('strong', money(product.price)), node('p', `المتاح: ${product.stock}`));
    const add = action('أضف إلى السلة', () => { const qty = (Number(cart[product.id]) || 0) + 1; if (qty > Math.min(product.stock,100)) throw new Error('الكمية غير متاحة'); cart[product.id] = qty; orderKey = null; persist(); notice('أُضيف المنتج إلى السلة'); });
    add.disabled = product.stock === 0; card.append(add); $('products').append(card);
  }
  if (!$('products').children.length) $('products').append(node('p', 'لا توجد منتجات متاحة. يضيفها صاحب المتجر من الإدارة.'));
}
function renderCart() {
  $('cart-items').replaceChildren(); let total = 0;
  for (const [id, quantity] of Object.entries(cart)) {
    const product = products.find(p => p.id === id); const row = node('article', undefined, 'card');
    row.append(node('h3', product?.title || 'منتج لم يعد متاحًا'));
    const input = node('input'); input.type = 'number'; input.min = '1'; input.max = '100'; input.step = '1'; input.value = quantity; input.setAttribute('aria-label', `كمية ${product?.title || id}`);
    input.onchange = () => { const qty = Number(input.value); if (Number.isInteger(qty) && qty >= 1 && qty <= 100) cart[id] = qty; orderKey = null; persist(); renderCart(); };
    row.append(input, action('حذف', () => { delete cart[id]; orderKey = null; persist(); renderCart(); }));
    if (product) { total += product.price * quantity; row.append(node('p', money(product.price * quantity))); }
    $('cart-items').append(row);
  }
  $('total').textContent = `الإجمالي التقريبي: ${money(total)}`;
  $('checkout').hidden = Object.keys(cart).length === 0;
  if (!Object.keys(cart).length) $('cart-items').append(node('p', 'السلة فارغة'));
}
async function refreshUser() {
  try { user = await api('me'); } catch { user = null; }
  $('identity').textContent = user?.email || 'سجّل الدخول لإتمام الطلب ومتابعته';
  $('admin-nav').hidden = !user?.admin; $('credentials').hidden = !!user; $('logout').hidden = !user;
}
$('credentials').onsubmit = event => safe(async () => {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.target));
  if (event.submitter.value === 'register') await api('register','POST',body);
  await api('login','POST',body); event.target.reset(); await refreshUser(); notice('تم تسجيل الدخول'); show('shop');
});
$('logout').onclick = () => safe(async () => { await api('logout','POST',{}); await refreshUser(); show('shop'); });
$('checkout').onsubmit = event => safe(async () => {
  event.preventDefault(); if (!user) { show('account'); throw new Error('سجّل الدخول أولًا'); }
  const button = event.target.querySelector('button'); button.disabled = true;
  try {
    orderKey ||= crypto.randomUUID();
    const order = await api('orders','POST',{ ...Object.fromEntries(new FormData(event.target)), request_id: orderKey, items: Object.entries(cart).map(([product_id, quantity]) => ({ product_id, quantity: Number(quantity) })) });
    cart = {}; orderKey = null; persist(); await refreshProducts(); show('orders'); notice(`تم إنشاء الطلب ${order.id} — ${money(order.total)}، الدفع عند الاستلام`);
  } finally { button.disabled = false; }
});
async function loadOrders() {
  if (!user) { show('account'); return; } $('order-list').replaceChildren();
  const orders = await api('orders');
  for (const order of orders) { const row = node('article',undefined,'card'); row.append(node('h3',order.id),node('p', `${statusLabel(order.status)} — ${money(order.total)}`)); for (const item of order.items) row.append(node('p',`${item.title} × ${item.quantity}`)); $('order-list').append(row); }
  if (!orders.length) $('order-list').append(node('p','لا توجد طلبات بعد'));
}
$('product-form').onsubmit = event => safe(async () => {
  event.preventDefault(); const values = Object.fromEntries(new FormData(event.target)); const price = Math.round(Number(values.price) * 100);
  const body = { title: values.title, description: values.description, price, stock: Number(values.stock), active: event.target.elements.active.checked };
  await api(`admin/products${values.id ? '/' + values.id : ''}`,values.id ? 'PUT' : 'POST',body); event.target.reset(); await refreshProducts(); await loadAdmin(); notice('حُفظ المنتج');
});
async function loadAdmin() {
  $('admin-products').replaceChildren(); for (const p of await api('admin/products')) $('admin-products').append(action(`تعديل ${p.title}`, () => { const f = $('product-form'); for (const key of ['id','title','description','stock']) f.elements[key].value = p[key]; f.elements.price.value = (p.price/100).toFixed(2); f.elements.active.checked = !!p.active; f.scrollIntoView(); }));
  $('admin-orders').replaceChildren(); const transitions = { pending: ['confirmed','cancelled'], confirmed: ['shipped','cancelled'], shipped: ['delivered'], delivered: [], cancelled: [] };
  for (const order of await api('admin/orders')) { const row = node('article',undefined,'card'); row.append(node('h4',order.id),node('p',`${money(order.total)} — ${statusLabel(order.status)}`),node('p',order.address),node('p',order.phone)); for (const item of order.items) row.append(node('p', `${item.title} × ${item.quantity}`)); for (const status of transitions[order.status] || []) row.append(action(statusLabel(status), async () => { await api(`admin/orders/${order.id}`,'PATCH',{status}); await refreshProducts(); await loadAdmin(); })); $('admin-orders').append(row); }
}
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => show(button.dataset.view));
$('setup-form').onsubmit = event => safe(async () => {
  event.preventDefault(); await api('setup', 'POST', Object.fromEntries(new FormData(event.target)));
  event.target.reset(); $('setup-panel').hidden = true; notice('تم إعداد صاحب المتجر. سجّل الدخول بحساب الإدارة لإضافة المنتجات.');
});
$('search').oninput = renderProducts;
const navigation = [...document.querySelectorAll('nav button')];
navigation.forEach(button => { button.disabled = true; });
safe(async () => { const health = await api('health'); currency = health.currency; $('setup-panel').hidden = !health.setup_required; await Promise.all([refreshProducts(),refreshUser()]); }).finally(() => navigation.forEach(button => { button.disabled = false; }));
