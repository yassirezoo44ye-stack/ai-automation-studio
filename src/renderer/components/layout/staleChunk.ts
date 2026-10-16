// Substrings emitted by each browser when a dynamic import 404s after a deploy.
// Deliberately NOT matching every TypeError — only these browser-native messages
// confirm the error is a failed network fetch, not a runtime error inside the
// imported module (e.g. "Cannot read properties of undefined").
//
// Lives outside AppLayout.tsx so that file only exports components
// (react-refresh/only-export-components).
const _STALE_CHUNK_MSGS = [
  "Failed to fetch dynamically imported module", // Chrome / Edge
  "Importing a module script failed",            // Safari
  "error loading dynamically imported module",   // Firefox
];

export function _isStaleChunkError(err: unknown): boolean {
  if (!(err instanceof TypeError)) return false;
  const msg = (err as TypeError).message;
  return _STALE_CHUNK_MSGS.some(p => msg.includes(p));
}
