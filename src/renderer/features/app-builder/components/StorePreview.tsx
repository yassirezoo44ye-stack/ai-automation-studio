import storeScript from "../../../../../app/templates/commerce/assets/app.js?raw";
import storeScriptUrl from "../../../../../app/templates/commerce/assets/app.js?url&no-inline";
import bridgeScriptUrl from "../preview/store-bridge.js?url&no-inline";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { authH } from "../../../shared/utils/api";

/** Opaque sandbox + project-scoped RPC. Generated scripts never receive Flow tokens. */
export function StorePreview({ projectId }: { projectId: string }) {
  const { t } = useTranslation("appBuilder");
  const frame = useRef<HTMLIFrameElement>(null);
  const [source, setSource] = useState("");
  const [error, setError] = useState<"connection" | "client" | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    const controller = new AbortController();
    const nonce = crypto.randomUUID();
    const root = `/api/projects/${encodeURIComponent(projectId)}/proxy/`;
    async function request(path: string, method = "GET", body?: string) {
      return fetch(root + path, { method, body, headers: authH({ "X-Flow-Store-Preview": "1" }), credentials: "same-origin", signal: controller.signal });
    }
    const receive = async (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || !event.data || event.data.nonce !== nonce || event.data.type !== "store-fetch") return;
      const { id, path, method, body } = event.data;
      if (!Number.isSafeInteger(id) || typeof path !== "string" || !/^api\/[A-Za-z0-9/_-]+$/.test(path) || !["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method) || (body !== undefined && (typeof body !== "string" || body.length > 32768))) return;
      try {
        const response = await request(path, method, body);
        const text = await response.text();
        if (active) frame.current?.contentWindow?.postMessage({ type: "store-response", nonce, id, status: response.status, text }, "*");
      } catch {
        if (active) frame.current?.contentWindow?.postMessage({ type: "store-response", nonce, id, status: 503, text: JSON.stringify({ detail: "Connection failed" }) }, "*");
      }
    };
    window.addEventListener("message", receive);
    async function load() {
      setError(null); setSource("");
      try {
        const responses = await Promise.all([request(""), request("assets/app.js"), request("assets/style.css")]);
        if (responses.some(response => !response.ok)) throw new Error("Preview unavailable");
        const [html, script, css] = await Promise.all(responses.map(response => response.text()));
        if (!active) return;
        // Preview only the shipped, verified storefront client. Custom client
        // code remains in the exported project; never evaluate it in Flow's origin.
        if (script.trim() !== storeScript.trim()) { setError("client"); return; }
        const clientUrl = new URL(storeScriptUrl, window.location.origin).href;
        const bridgeUrl = new URL(bridgeScriptUrl, window.location.origin).href;
        const document = new DOMParser().parseFromString(html, "text/html");
        document.querySelectorAll("script, link, meta[http-equiv], base").forEach(node => node.remove());
        const policy = document.createElement("meta"); policy.httpEquiv = "Content-Security-Policy";
        policy.content = `default-src 'none'; script-src ${new URL(bridgeUrl).origin + new URL(bridgeUrl).pathname} ${new URL(clientUrl).origin + new URL(clientUrl).pathname}; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; form-action 'none'; frame-src 'none'; base-uri 'none'`;
        document.head.prepend(policy);
        const style = document.createElement("style"); style.textContent = css; document.head.append(style);
        const context = document.createElement("script"); context.id = "store-preview-context"; context.type = "application/json";
        context.textContent = JSON.stringify({ nonce, parentOrigin: window.location.origin }); document.body.append(context);
        for (const src of [bridgeUrl, clientUrl]) { const js = document.createElement("script"); js.src = src; document.body.append(js); }
        const htmlUrl = URL.createObjectURL(new Blob(["<!doctype html>" + document.documentElement.outerHTML], { type: "text/html" })); urls.push(htmlUrl);
        setSource(htmlUrl);
      } catch { if (active) setError("connection"); }
    }
    void load();
    return () => { active = false; controller.abort(); window.removeEventListener("message", receive); urls.forEach(url => URL.revokeObjectURL(url)); };
  }, [projectId, retry]);
  return <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
    {error ? <div role="alert"><p>{t(error === "client" ? "commerce.customClient" : "commerce.previewError")}</p><button onClick={() => setRetry(value => value + 1)}>{t("commerce.retry")}</button></div>
      : source ? <iframe ref={frame} key={source} src={source} title={t("commerce.preview")} sandbox="allow-scripts allow-forms" style={{ flex: 1, border: 0, width: "100%" }} />
        : <p role="status">{t("commerce.loading")}</p>}
  </div>;
}
