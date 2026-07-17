/**
 * AIWorkspace — AI platform shell.
 * Manages shared state (agents, projects) and tab routing.
 * All tab logic lives in ./tabs/*.
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { S } from "../../styles/theme";
import type { Project, Agent } from "../../types";
import { ChatTab }   from "./tabs/ChatTab";
import { AgentsTab } from "./tabs/AgentsTab";

type AITab = "chat" | "agents";

export function AIWorkspace() {
  const toast   = useToast();
  const [tab, setTab] = useState<AITab>("chat");

  const [projects, setProjects]   = useState<Project[]>([]);
  const [agents, setAgents]       = useState<Agent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  // chatAgentId is set when the user clicks "Chat" on an agent card
  const [chatAgentId, setChatAgentId] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    setLoadingAgents(true);
    try {
      const r = await apiFetch("/api/agents");
      setAgents(await parseJSON<Agent[]>(r, "/api/agents"));
    } catch { toast("Could not load agents", "err"); }
    finally { setLoadingAgents(false); }
  }, [toast]);

  useEffect(() => {
    apiFetch("/api/projects")
      .then(r => parseJSON<Project[]>(r, "/api/projects"))
      .then(setProjects)
      .catch(() => {});
    void Promise.resolve().then(loadAgents);
  }, [loadAgents]);

  const handleChatWith = (agentId: string) => {
    setChatAgentId(agentId);
    setTab("chat");
  };

  const TABS: [AITab, string][] = [["chat", "Chat"], ["agents", "Agents"]];

  return (
    <>
      <header style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={S.headerTitle}>AI Workspace</span>
          <div style={{ display: "flex", gap: 4, background: "rgba(255,255,255,.04)", borderRadius: 12, padding: 4 }}>
            {TABS.map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                role="tab"
                aria-selected={tab === id}
                style={{
                  padding: "6px 16px", borderRadius: 9, border: "none", cursor: "pointer",
                  fontSize: 13, fontWeight: 500, transition: "all .18s",
                  background: tab === id ? "linear-gradient(135deg,#8b5cf6,#6366f1)" : "transparent",
                  color:      tab === id ? "#fff" : "rgba(148,163,184,.6)",
                  boxShadow:  tab === id ? "0 2px 12px rgba(139,92,246,.35)" : "none",
                }}
              >{label}</button>
            ))}
          </div>
        </div>
        {tab === "agents" && (
          <button
            onClick={() => { setChatAgentId(null); setTab("agents"); }}
            style={S.btnPrimary}
          >+ New Agent</button>
        )}
      </header>

      {tab === "chat" && (
        <ChatTab
          agents={agents}
          projects={projects}
          initialAgentId={chatAgentId}
        />
      )}
      {tab === "agents" && (
        <AgentsTab
          agents={agents}
          loading={loadingAgents}
          onRefresh={loadAgents}
          onChatWith={handleChatWith}
        />
      )}
    </>
  );
}
