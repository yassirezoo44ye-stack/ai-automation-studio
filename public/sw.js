// Flow service worker: offline shell and hashed build assets only.
//
// It must never store anything private. The old version cached every
// successful GET that did not contain "/api/", which included signed-in
// calls to the backend's /marketplace, /plugins and /sandbox routes (sent
// to VITE_API_URL on another origin with an Authorization header) and
// served them back from CacheStorage when offline, to whoever used the
// device next. It also cached the index.html that the host returns for a
// missing /assets/*.js file after a deploy, so the broken chunk kept
// coming back from the cache. Renaming the cache deletes those entries.
const CACHE = "flow-static-v2";
const SHELL = "/";

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll([SHELL]).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

/** Which requests this worker handles at all. Everything else goes straight to the network. */
function isCacheable(request) {
  if (request.method !== "GET") return false;
  if (request.headers.has("authorization") || request.headers.has("x-sub-token")) return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (request.mode === "navigate") return true;
  return url.pathname.startsWith("/assets/");
}

/** A response that is safe to keep: OK, and not HTML standing in for a script or style. */
function isStorable(request, response) {
  if (!response || !response.ok || response.type === "opaque") return false;
  if (request.mode === "navigate") return true;
  const type = response.headers.get("content-type") || "";
  return !type.includes("text/html");
}

self.addEventListener("fetch", e => {
  const request = e.request;
  if (!isCacheable(request)) return;
  const navigate = request.mode === "navigate";
  e.respondWith(
    fetch(request)
      .then(r => {
        if (isStorable(request, r)) {
          const clone = r.clone();
          // Every page is the same SPA shell, so store it once under "/".
          caches.open(CACHE).then(c => c.put(navigate ? SHELL : request, clone));
        }
        return r;
      })
      .catch(() =>
        caches.match(navigate ? SHELL : request).then(hit => hit || Response.error())
      )
  );
});
