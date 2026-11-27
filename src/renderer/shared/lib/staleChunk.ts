/**
 * Recovery from stale lazy chunks after a deploy.
 *
 * Every build gives each lazy page a new hashed file name, and a deploy
 * removes the old files. A tab opened before the deploy still runs the old
 * bundle, so the first time it opens a page it has not loaded yet, the
 * import asks for a file that no longer exists (on Vercel the SPA rewrite
 * even answers it with index.html) and the browser rejects the import with
 * "Failed to fetch dynamically imported module". The fix is to load the new
 * index.html, i.e. reload the page.
 *
 * Loop guard: the time of the last automatic reload is kept in
 * sessionStorage. Another reload is allowed once RELOAD_COOLDOWN_MS has
 * passed, so every later deploy in the same tab is recovered too, while a
 * chunk that is genuinely missing (it still fails right after a reload)
 * shows the error screen instead of reloading forever. The previous guard
 * was a flag that was never cleared, so only the first deploy per tab was
 * ever recovered.
 */
import { lazy } from "react";
import type { ComponentType, LazyExoticComponent } from "react";

const RELOAD_AT_KEY = "__flow_chunk_reload_at__";
export const RELOAD_COOLDOWN_MS = 10_000;

// Browser-issued messages for a dynamic import that could not be fetched.
// Only these: a TypeError thrown while *running* a module (e.g. reading a
// property of undefined) is a real bug, and reloading would hide it.
const STALE_CHUNK_MSGS = [
  "Failed to fetch dynamically imported module", // Chrome / Edge
  "Importing a module script failed",            // Safari
  "error loading dynamically imported module",   // Firefox
];

export function isStaleChunkError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  // Vite's own error when a chunk's CSS dependency could not be preloaded.
  if (err.message.includes("Unable to preload CSS for")) return true;
  return err instanceof TypeError && STALE_CHUNK_MSGS.some(m => err.message.includes(m));
}

/** Reload the page to pick up the new build, unless one was just tried.
 *  Returns true when a reload was started. */
export function reloadForNewBuild(now: number = Date.now()): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_AT_KEY) || 0);
    if (last && now - last < RELOAD_COOLDOWN_MS) return false;
    sessionStorage.setItem(RELOAD_AT_KEY, String(now));
  } catch {
    // sessionStorage unavailable (some private modes): without a guard a
    // reload could loop, so leave it to the error screen's button.
    return false;
  }
  window.location.reload();
  return true;
}

/** React.lazy with stale-chunk recovery. `load` resolves to the component:
 *  lazyPage(() => import("../features/leads").then(m => m.LeadsPage)) */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- same bound as React.lazy
export function lazyPage<T extends ComponentType<any>>(
  load: () => Promise<T>,
): LazyExoticComponent<T> {
  return lazy(() =>
    load().then(
      component => ({ default: component }),
      (err: unknown) => {
        if (isStaleChunkError(err)) reloadForNewBuild();
        throw err;
      },
    ),
  );
}
