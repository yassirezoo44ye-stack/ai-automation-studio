export type Page = "home" | "ai" | "dev" | "design" | "automation" | "social" | "settings" | "agentos" | "marketplace";

export type Message = { id: string; role: "user" | "assistant"; content: string };
export type Conv    = { id: string; title: string; updated_at: string };
export type Project = { id: string; name: string; description: string; status: string; created_at: string };
export type Task = {
  id: string; title: string; notes: string | null; status: "pending" | "in_progress" | "done";
  priority: "low" | "medium" | "high"; category: string | null; tags: string[];
  due_date: string | null; recurrence: string; source: string; project_id: string | null;
  created_at: string; completed_at: string | null;
};
export type Agent = {
  id: string; name: string; avatar: string; description: string;
  system_prompt: string; model: string; temperature: number;
  message_count: number; created_at: string;
};
export type BuildFile  = { path: string; content: string };
export type BuildState = "idle" | "building" | "done" | "error";
export type Toast      = { id: string; msg: string; kind: "ok" | "err" | "info" };
export type SocialTab  = "youtube" | "facebook";
export type SettingsTab = "system" | "ai" | "appearance" | "about";
