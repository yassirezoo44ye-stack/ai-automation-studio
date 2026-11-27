/**
 * Confirmation card for one assistant proposal (M4, M5).
 *
 * Nothing happens until the user presses Confirm. The request goes through
 * the regular authenticated API with the user's own session, so server-side
 * permissions and org membership decide whether it is allowed. A confirmed
 * card is remembered in this browser so reloading the conversation does not
 * offer to apply the same change twice.
 *
 * Status changes (M5) first load the record by id through the same API: the
 * card shows its real name and current status, and an id the user cannot see
 * (wrong, guessed or from another workspace) shows "not found" with no
 * Confirm button.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../../shared/utils/api";
import { useAppContext } from "../../../contexts/app";
import { actionKey, type AssistantAction } from "../../../shared/utils/assistantActions";

type State = "idle" | "running" | "done" | "dismissed" | "error";
type Target = { label: string; status: string } | "loading" | "missing";

function readDone(key: string): boolean {
  try { return localStorage.getItem(key) === "done"; } catch { return false; }
}

function isUpdate(a: AssistantAction): a is Extract<AssistantAction, { kind: "update_task_status" | "update_lead_status" }> {
  return a.kind === "update_task_status" || a.kind === "update_lead_status";
}

async function errorDetail(res: Response): Promise<string> {
  try { return ((await res.json()) as { detail?: string }).detail ?? ""; } catch { return ""; }
}

function request(action: AssistantAction): { path: string; method: string; body: unknown } {
  switch (action.kind) {
    case "create_task":
      return { path: "/api/tasks", method: "POST", body: { title: action.title, priority: action.priority, due_date: action.due_date, notes: action.notes, source: "assistant" } };
    case "create_lead":
      return { path: "/api/leads", method: "POST", body: { name: action.name, email: action.email, phone: action.phone, source: action.source ?? "Flow assistant" } };
    case "update_task_status":
      return { path: `/api/tasks/${action.id}`, method: "PUT", body: { status: action.status } };
    case "update_lead_status":
      return { path: `/api/leads/${action.id}/status`, method: "PATCH", body: { status: action.status } };
  }
}

async function execute(action: AssistantAction): Promise<void> {
  const req = request(action);
  const res = await apiFetch(req.path, {
    method: req.method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  if (!res.ok) throw new Error((await errorDetail(res)) || `HTTP ${res.status}`);
}

/** Loads the record a status change points at; "missing" when the user cannot see it. */
function useTarget(action: AssistantAction, skip: boolean): Target | null {
  const update = isUpdate(action);
  const [target, setTarget] = useState<Target | null>(update && !skip ? "loading" : null);
  const path = update ? (action.kind === "update_task_status" ? `/api/tasks/${action.id}` : `/api/leads/${action.id}`) : "";
  useEffect(() => {
    if (!path || skip) return;
    let live = true;
    (async () => {
      try {
        const res = await apiFetch(path);
        if (!res.ok) { if (live) setTarget("missing"); return; }
        const row = (await res.json()) as { title?: string; name?: string; status?: string };
        if (live) setTarget({ label: row.title ?? row.name ?? "", status: row.status ?? "" });
      } catch { if (live) setTarget("missing"); }
    })();
    return () => { live = false; };
  }, [path, skip]);
  return target;
}

export function AssistantActionCard({ action, messageContent, index }: {
  action: AssistantAction; messageContent: string; index: number;
}) {
  const { t } = useTranslation("ai");
  const { setPage } = useAppContext();
  const key = actionKey(messageContent, index);
  const [state, setState] = useState<State>(() => readDone(key) ? "done" : "idle");
  const [error, setError] = useState("");
  const target = useTarget(action, state === "done");

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

  const statusLabel = (s: string) => {
    if (!isUpdate(action) || !s) return s;
    const group = action.kind === "update_task_status" ? "task" : "lead";
    return t(`chatTab.actions.status.${group}.${s}`, { defaultValue: s });
  };

  let fields: [string, string | undefined][];
  switch (action.kind) {
    case "create_task":
      fields = [[t("chatTab.actions.fields.title"), action.title],
        [t("chatTab.actions.fields.priority"), t(`chatTab.actions.priority.${action.priority}`)],
        [t("chatTab.actions.fields.due"), action.due_date],
        [t("chatTab.actions.fields.notes"), action.notes]];
      break;
    case "create_lead":
      fields = [[t("chatTab.actions.fields.name"), action.name],
        [t("chatTab.actions.fields.source"), action.source],
        [t("chatTab.actions.fields.email"), action.email],
        [t("chatTab.actions.fields.phone"), action.phone]];
      break;
    default: {
      const loaded = target && typeof target === "object" ? target : null;
      fields = [[t(action.kind === "update_task_status" ? "chatTab.actions.fields.task" : "chatTab.actions.fields.lead"), loaded?.label],
        [t("chatTab.actions.fields.current"), loaded ? statusLabel(loaded.status) : undefined],
        [t("chatTab.actions.fields.newStatus"), statusLabel(action.status)]];
    }
  }

  const unchanged = isUpdate(action) && target && typeof target === "object" && target.status === action.status;
  const blocked = target === "loading" || target === "missing" || unchanged;
  const icon = action.kind === "create_lead" || action.kind === "update_lead_status" ? "👤" : action.kind === "create_task" ? "✓" : "↻";
  const leadPage = action.kind === "create_lead" || action.kind === "update_lead_status";

  return (
    <div className={`action-card action-card--${state}`} role="group" aria-label={t(`chatTab.actions.kind.${action.kind}`)}>
      <div className="action-card__head">
        <span className="action-card__icon" aria-hidden="true">{icon}</span>
        <span className="action-card__title">{t(`chatTab.actions.kind.${action.kind}`)}</span>
        {state !== "done" && <span className="action-card__badge">{t("chatTab.actions.needsConfirm")}</span>}
      </div>
      <dl className="action-card__fields">
        {fields.filter(([, v]) => v).map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      {state === "done" ? (
        <div className="action-card__result" role="status">
          ✓ {t("chatTab.actions.done")}
          {leadPage && (
            <button type="button" className="action-card__link" onClick={() => setPage("leads")}>
              {t("chatTab.nav.open", { page: t("common:sidebar.nav.leads") })}
            </button>
          )}
        </div>
      ) : target === "loading" ? (
        <div className="action-card__result" role="status">{t("chatTab.actions.loading")}</div>
      ) : target === "missing" ? (
        <>
          <div className="action-card__error" role="alert">{t("chatTab.actions.notFound")}</div>
          <div className="action-card__buttons">
            <button type="button" className="action-card__dismiss" onClick={() => setState("dismissed")}>
              {t("chatTab.actions.dismiss")}
            </button>
          </div>
        </>
      ) : (
        <>
          {unchanged && <div className="action-card__result" role="status">{t("chatTab.actions.unchanged")}</div>}
          <div className="action-card__buttons">
            {!blocked && (
              <button type="button" className="action-card__confirm" onClick={() => void confirm()} disabled={state === "running"}>
                {state === "running" ? t("chatTab.actions.running") : t("chatTab.actions.confirm")}
              </button>
            )}
            <button type="button" className="action-card__dismiss" onClick={() => setState("dismissed")} disabled={state === "running"}>
              {t("chatTab.actions.dismiss")}
            </button>
          </div>
        </>
      )}
      {state === "error" && <div className="action-card__error" role="alert">{t("chatTab.actions.failed", { message: error })}</div>}
    </div>
  );
}
