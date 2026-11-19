/* Runs inside an opaque iframe. It never sees Flow credentials or parent storage. */
(() => {
  const context = JSON.parse(document.getElementById('store-preview-context').textContent);
  let sequence = 0;
  const pending = new Map();
  window.addEventListener('message', event => {
    if (event.source !== parent || event.origin !== context.parentOrigin || event.data?.type !== 'store-response' || event.data.nonce !== context.nonce) return;
    const resolve = pending.get(event.data.id);
    if (!resolve) return;
    pending.delete(event.data.id);
    resolve(new Response(event.data.text, {status: event.data.status, headers: {'Content-Type':'application/json'}}));
  });
  window.fetch = (path, options = {}) => new Promise((resolve, reject) => {
    if (typeof path !== 'string' || !/^api\/[A-Za-z0-9/_-]+$/.test(path)) return reject(new Error('Only store API requests are allowed'));
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error('Store request timed out')); }, 20000);
    pending.set(id, response => { clearTimeout(timeout); resolve(response); });
    parent.postMessage({type:'store-fetch', nonce:context.nonce, id, path, method:options.method || 'GET', body:options.body}, context.parentOrigin);
  });
})();
