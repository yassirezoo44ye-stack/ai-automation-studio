import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

const REFRESH_KEY = "axon_refresh_token";
const SUB_KEY = "sub_token";

// Inject auth headers on all /api/ requests
const _origFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  const url =
    typeof input === "string"
      ? input
      : input instanceof Request
        ? input.url
        : String(input);

  if (url.includes("/api/") && !url.includes("/api/auth/")) {
    // Prefer new JWT access token (stored in module scope via AuthContext)
    // Fall back to legacy subscription token for backward compat
    const accessToken = (window as unknown as Record<string, string>).__axon_access_token;
    const subToken = localStorage.getItem(SUB_KEY) ?? "";
    const headers: Record<string, string> = { ...(init?.headers as Record<string, string> ?? {}) };
    if (accessToken) {
      headers["Authorization"] = `Bearer ${accessToken}`;
    } else if (subToken) {
      headers["X-Sub-Token"] = subToken;
    }
    init = { ...init, headers };
  }

  return _origFetch(input, init);
};

// AuthContext will set this so fetch interceptor can read latest token
export function setGlobalAccessToken(token: string | null) {
  (window as unknown as Record<string, string | null>).__axon_access_token = token;
}

// Clear stale refresh token key from old auth system if user switches to new
if (!localStorage.getItem(REFRESH_KEY) && !localStorage.getItem(SUB_KEY)) {
  // Fresh start — nothing to do
}

ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
