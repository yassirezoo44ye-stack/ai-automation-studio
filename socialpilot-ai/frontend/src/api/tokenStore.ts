// In-memory-only access-token state: it never touches localStorage/sessionStorage,
// so it isn't reachable by an XSS payload that merely reads storage — only by one
// that can execute code in-page (a stronger bar). The refresh token itself never
// reaches JS at all; it lives solely in the httpOnly cookie the backend sets (see
// backend/app/core/cookies.py).
//
// The CSRF token is deliberately NOT kept here — it lives in a non-httpOnly
// cookie precisely so the frontend can re-read it fresh from `document.cookie`
// on every request (see `readCsrfCookie` in client.ts), including after a page
// reload wipes this in-memory store. Caching it here too would go stale on
// reload while the real cookie (and the token the backend expects back) is
// still perfectly valid.
//
// This is a tiny module-level pub-sub rather than React context state because
// `apiFetch` (a plain async function, not a component) needs synchronous read
// access to "the current token" without prop-drilling a setter through every
// call site.

interface TokenState {
  accessToken: string | null;
}

let state: TokenState = { accessToken: null };
const listeners = new Set<() => void>();

export function getTokenState(): TokenState {
  return state;
}

export function setTokenState(next: TokenState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

export function clearTokenState(): void {
  setTokenState({ accessToken: null });
}

export function subscribeTokenState(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
