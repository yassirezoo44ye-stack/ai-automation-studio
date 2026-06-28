import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import SubscriptionGate from "./SubscriptionGate";

ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
).render(
  <React.StrictMode>
    <SubscriptionGate>
      <App />
    </SubscriptionGate>
  </React.StrictMode>
);
