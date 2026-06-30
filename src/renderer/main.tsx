import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import SubscriptionGate from "./SubscriptionGate";

// Inject sub_token on all /api/ requests automatically
const _origFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  const url = typeof input === "string" ? input : (input instanceof Request ? input.url : String(input));
  const token = localStorage.getItem("sub_token") ?? "";
  if (token && url.includes("/api/") && !url.includes("/api/subscription/") && !url.includes("/api/stripe/")) {
    init = { ...init, headers: { "X-Sub-Token": token, ...(init?.headers as Record<string, string> ?? {}) } };
  }
  return _origFetch(input, init);
};

ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
).render(
  <React.StrictMode>
    <SubscriptionGate>
      <App />
    </SubscriptionGate>
  </React.StrictMode>
);
