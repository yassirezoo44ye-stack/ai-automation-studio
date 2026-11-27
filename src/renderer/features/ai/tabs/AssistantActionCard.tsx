/**
 * Confirmation card for one assistant proposal (M4).
 *
 * Nothing happens until the user presses Confirm. The request goes through
 * the regular authenticated API with the user's own session, so server-side
 * permissions and org membership decide whether it is allowed. A confirmed
 * card is remembered in this browser so reloading the conversation does not
 * offer to create the same record twice.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../../shared/utils/api";
import { useAppContext } from "../../../contexts/app";
import { actionKey, type AssistantAction } from "../../../shared/utils/assistantActions";

type State = "idle" | "running" | "done" | "dismissed" | "error";

function readDone(key: string): boolean {
  try { return localStorage.getItem(key) === "done"; } catch { return false; }
}

async function execute(action: AssistantAction): Promise<void> {
  const req = action.kind === "create_task"
    ? { path: "/api/tasks", body: { title: action.title, priority: action.priority, due_date: action.due_date, notes: action.notes, source: "assistant" } }
    : { path: "/api/leads", body: { name: action.name, email: action.email, phone: action.phone, source: action.source ?? "Flow assistant" } };
  const res = await apiFetch(req.path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail ?? ""; } catch { /* not JSON */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
}

export function AssistantActionCard({ action, messageContent, index }: {
  action: AssistantAction; messageContent: string; index: number;
}) {
  const { t } = useTranslation("ai");
  const { setPage } = useAppContext();
  const key = actionKey(messageContent, index);
  const [state, setState] = useState<State>(() => readDone(key) ? "done" : "idle");
  const [error, setError] = useState("");

  async function confirm() {
    if (state === "running" || state === "done") return;
    setState("running"); setError("");
    try {
      await execute(action);
      try { localStorage.setItem(key, "done"); } catch { /* storage blocked */ }
      setState("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setState("error");
    }
  }

  if (state === "dismissed") return null;

  const fields: [string, string | undefined][] = action.kind === "create_task"
    ? [[t("chatTab.actions.fields.title"), action.title],
       [t("chatTab.actions.fields.priority"), t(`chatTab.actions.priority.${action.priority}`)],
       [t("chatTab.actions.fields.due"), action.due_date],
       [t("chatTab.actions.fields.notes"), action.notes]]
    : [[t("chatTab.actions.fields.name"), action.name],
       [t("chatTab.actions.fields.source"), action.source],
       [t("chatTab.actions.fields.email"), action.email],
       [t("chatTab.actions.fields.phone"), action.phone]];

  return (
    <div className={`action-card action-card--${state}`} role="group" aria-label={t(`chatTab.actions.kind.${action.kind}`)}>
      <div className="action-card__head">
        <span className="action-card__icon" aria-hidden="true">{action.kind === "create_task" ? "✓" : "👤"}</span>
        <span className="action-card__title">{t(`chatTab.actions.kind.${action.kind}`)}</span>
        <span className="action-card__badge">{t("chatTab.actions.needsConfirm")}</span>
      </div>
      <dl className="action-card__fields">
        {fields.filter(([, v]) => v).map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      {state === "done" ? (
        <div className="action-card__result" role="status">
          ✓ {t("chatTab.actions.done")}
          {action.kind === "create_lead" && (
            <button type="button" className="action-card__link" onClick={() => setPage("leads")}>
              {t("chatTab.nav.open", { page: t("common:sidebar.nav.leads") })}
            </button>
          )}
        </div>
      ) : (
        <div className="action-card__buttons">
          <button type="button" className="action-card__confirm" onClick={() => void confirm()} disabled={state === "running"}>
            {state === "running" ? t("chatTab.actions.running") : t("chatTab.actions.confirm")}
          </button>
          <button type="button" className="action-card__dismiss" onClick={() => setState("dismissed")} disabled={state === "running"}>
            {t("chatTab.actions.dismiss")}
          </button>
        </div>
      )}
      {state === "error" && <div className="action-card__error" role="alert">{t("chatTab.actions.failed", { message: error })}</div>}
    </div>
  );
}
