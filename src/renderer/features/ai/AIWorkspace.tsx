/**
 * AIWorkspace — AI platform shell.
 * Manages shared state (agents, projects) and tab routing.
 * All tab logic lives in ./tabs/*.
 */
import { useState, useEffect, useCallback } from "react";
import { useToast } from "../../contexts/toast";
import { apiFetch, parseJSON } from "../../utils/api";
import { S } from "../../styles/theme";
import { GoldButton } from "../../shared/ui/gold";
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
          <div className="pill-tabs">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                role="tab"
                aria-selected={tab === id}
                className={`pill-tab${tab === id ? " active" : ""}`}
              >{label}</button>
            ))}
          </div>
        </div>
        {tab === "agents" && (
          <GoldButton onClick={() => { setChatAgentId(null); setTab("agents"); }}>
            + New Agent
          </GoldButton>
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
