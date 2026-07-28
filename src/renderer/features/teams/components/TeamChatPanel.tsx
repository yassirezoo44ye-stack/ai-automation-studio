/**
 * TeamChatPanel — message list + composer for one chat room.
 * teamId null renders the organization's org-wide "General" room.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../../contexts/AuthContext";
import { useTeamChat } from "../../../shared/hooks/useTeamChat";
import { GlassCard, GoldButton } from "../../../shared/ui/gold";

interface Props {
  organizationId: string;
  teamId: string | null;
}

export function TeamChatPanel({ organizationId, teamId }: Props) {
  const { t } = useTranslation("teams");
  const { user } = useAuth();
  const { messages, status, connectionStatus, sending, send } = useTeamChat(organizationId, teamId);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  const submit = async () => {
    if (!draft.trim() || sending) return;
    const ok = await send(draft);
    if (ok) setDraft("");
  };

  const connectionColor = connectionStatus === "live" ? "var(--green)"
    : connectionStatus === "connecting" || connectionStatus === "reconnecting" ? "var(--yellow)"
    : "var(--t5)";

  return (
    <GlassCard lift={false} style={{ display: "flex", flexDirection: "column", height: 340 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexShrink: 0 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t2)" }}>
          {teamId ? t("chat.teamRoomTitle") : t("chat.generalRoomTitle")}
        </span>
        <span style={{ fontSize: 10, color: connectionColor, display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: connectionColor }} />
          {t(`chat.connection.${connectionStatus}`)}
        </span>
      </div>

      <div ref={listRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
        {status === "loading" ? (
          <div className="skeleton" style={{ height: 60, borderRadius: 8 }} />
        ) : messages.length === 0 ? (
          <div style={{ fontSize: 11, color: "var(--t4)", textAlign: "center", padding: "20px 0" }}>
            {t("chat.empty")}
          </div>
        ) : messages.map(m => {
          const mine = m.user_id === user?.id;
          return (
            <div key={m.id} style={{ alignSelf: mine ? "flex-end" : "flex-start", maxWidth: "80%" }}>
              {!mine && (
                <div style={{ fontSize: 10, color: "var(--t4)", marginBottom: 2 }}>{m.name || m.email}</div>
              )}
              <div style={{
                padding: "6px 10px", borderRadius: 10, fontSize: 12, lineHeight: 1.5,
                background: mine ? "var(--accent-dim)" : "var(--bg-hover)",
                color: "var(--t1)", wordBreak: "break-word",
              }}>
                {m.body}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }}
          placeholder={t("chat.placeholder")}
          className="g-input" style={{ flex: 1, fontSize: 12 }}
        />
        <GoldButton onClick={() => void submit()} disabled={sending || !draft.trim()} style={{ padding: "6px 14px", fontSize: 12 }}>
          {t("chat.send")}
        </GoldButton>
      </div>
    </GlassCard>
  );
}
