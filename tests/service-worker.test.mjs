/**
 * M8 (Vercel / browser cache). Runs public/sw.js in a sandbox with fake
 * caches and fetch, and pins two things found on the real deployment:
 * the worker must never store signed-in or cross-origin responses, and it
 * must not keep the index.html the host returns for a missing chunk.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import { describe, expect, it } from "vitest";

const ORIGIN = "https://app.example.test";
const source = readFileSync(join(process.cwd(), "public/sw.js"), "utf8");

function makeWorker({ network }) {
  const stores = new Map();
  const listeners = {};
  const open = name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const m = stores.get(name);
    return Promise.resolve({
      addAll: urls => { urls.forEach(u => m.set(u, new Response("shell", { headers: { "content-type": "text/html" } }))); return Promise.resolve(); },
      put: (req, res) => { m.set(typeof req === "string" ? req : req.url, res); return Promise.resolve(); },
    });
  };
  const caches = {
    open,
    keys: () => Promise.resolve([...stores.keys()]),
    delete: name => Promise.resolve(stores.delete(name)),
    match: key => {
      const k = typeof key === "string" ? key : key.url;
      for (const m of stores.values()) {
        if (m.has(k)) return Promise.resolve(m.get(k));
        if (m.has(new URL(k, ORIGIN).pathname)) return Promise.resolve(m.get(new URL(k, ORIGIN).pathname));
      }
      return Promise.resolve(undefined);
    },
  };
  const self = {
    location: new URL(ORIGIN + "/sw.js"),
    addEventListener: (type, fn) => { listeners[type] = fn; },
    skipWaiting: () => {},
    clients: { claim: () => {} },
  };
  vm.runInNewContext(source, { self, caches, fetch: network, URL, Response, Promise, console });
  return { listeners, stores, caches };
}

/** Dispatches a fetch event; returns the response the worker answered with, or null if it let it through. */
async function dispatch(worker, url, { mode = "cors", headers = {}, method = "GET" } = {}) {
  let answered = null;
  const request = { url: new URL(url, ORIGIN).toString(), method, mode, headers: new Headers(headers) };
  worker.listeners.fetch({ request, respondWith: p => { answered = p; } });
  if (!answered) return null;
  const res = await answered;
  await new Promise(r => setTimeout(r, 0));
  return res;
}

const cachedKeys = worker => [...worker.stores.values()].flatMap(m => [...m.keys()]);

describe("service worker caching", () => {
  it("leaves signed-in, cross-origin and API requests to the network", async () => {
    const worker = makeWorker({ network: () => Promise.resolve(new Response("{}", { headers: { "content-type": "application/json" } })) });
    expect(await dispatch(worker, "https://api.example.test/marketplace/listings", { headers: { Authorization: "Bearer x" } })).toBeNull();
    expect(await dispatch(worker, "https://api.example.test/sandbox/workers")).toBeNull();
    expect(await dispatch(worker, "/api/notifications")).toBeNull();
    expect(await dispatch(worker, "/marketplace/listings", { headers: { "X-Sub-Token": "t" } })).toBeNull();
    expect(await dispatch(worker, "/assets/app.js", { method: "POST" })).toBeNull();
    expect(cachedKeys(worker)).toEqual([]);
  });

  it("does not keep the HTML fallback served for a missing chunk", async () => {
    const worker = makeWorker({ network: () => Promise.resolve(new Response("<!doctype html>", { headers: { "content-type": "text/html" } })) });
    await dispatch(worker, "/assets/Page-old.js");
    expect(cachedKeys(worker)).toEqual([]);
  });

  it("caches hashed assets and serves the app shell offline", async () => {
    let online = true;
    const worker = makeWorker({
      network: req => online
        ? Promise.resolve(new Response(req.url.endsWith(".js") ? "js" : "<html>", { headers: { "content-type": req.url.endsWith(".js") ? "text/javascript" : "text/html" } }))
        : Promise.reject(new TypeError("offline")),
    });
    await dispatch(worker, "/assets/index-abc.js");
    await dispatch(worker, "/leads", { mode: "navigate" });
    expect(cachedKeys(worker).sort()).toEqual(["/", `${ORIGIN}/assets/index-abc.js`]);

    online = false;
    expect(await (await dispatch(worker, "/assets/index-abc.js")).text()).toBe("js");
    expect(await (await dispatch(worker, "/settings", { mode: "navigate" })).text()).toBe("<html>");
  });

  it("drops caches written by the previous worker", async () => {
    const worker = makeWorker({ network: () => Promise.reject(new TypeError("offline")) });
    await worker.caches.open("ai-studio-v1");
    let done;
    worker.listeners.activate({ waitUntil: p => { done = p; } });
    await done;
    expect([...worker.stores.keys()]).not.toContain("ai-studio-v1");
  });
});

describe("vercel.json", () => {
  const cfg = JSON.parse(readFileSync(join(process.cwd(), "vercel.json"), "utf8"));
  // Vercel path-to-regexp sources -> RegExp, for the forms this file uses.
  const toRe = src => new RegExp("^" + src
    .replace(/\/:rest\*$/, "(?:/.*)?")
    .replace(/:root\(/, "(")
    .replace(/:[a-z]+\*/gi, ".*")
    .replace(/:[a-z]+/gi, "[^/]+") + "$");
  const spa = cfg.rewrites.filter(r => r.destination === "/index.html").map(r => toRe(r.source));
  const rewritten = path => spa.some(re => re.test(path));

  it("lets a missing /assets/ file 404 instead of rewriting it to index.html", () => {
    expect(rewritten("/assets/Page-old.js")).toBe(false);
    expect(rewritten("/leads")).toBe(true);
    expect(rewritten("/settings/billing")).toBe(true);
  });

  it("answers unknown pages with a real 404 and serves robots.txt and sitemap.xml as files", () => {
    for (const path of ["/no-such-page", "/robots.txt", "/sitemap.xml", "/dashboard.html"]) {
      expect(rewritten(path), path).toBe(false);
    }
    for (const path of ["/ar", "/en", "/study-library", "/login", "/register", "/feed/abc", "/project/p1/ai", "/oauth-callback"]) {
      expect(rewritten(path), path).toBe(true);
    }
  });

  it("keeps signed-in app pages out of search results but not the public pages", () => {
    const noindex = cfg.headers
      .filter(h => h.headers.some(x => x.key === "X-Robots-Tag" && /noindex/.test(x.value)))
      .map(h => toRe(h.source));
    const hidden = path => noindex.some(re => re.test(path));
    for (const path of ["/settings", "/billing/plans", "/feed/abc", "/project/p1/ai"]) expect(hidden(path), path).toBe(true);
    for (const path of ["/", "/ar", "/en", "/study-library"]) expect(hidden(path), path).toBe(false);
  });
});
