// Copilot context + hook — split from CopilotContext.tsx so that file
// exports only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: "streaming" | "complete" | "stopped" | "failed";
}

export interface CopilotConversation {
  id: string;
  title: string;
  updated_at: string;
}

export interface CopilotAction { label: string; page: string }

export interface CopilotContextType {
  open: boolean;
  setOpen: (v: boolean) => void;
  messages: CopilotMessage[];
  conversations: CopilotConversation[];
  conversationId: string | null;
  loadingHistory: boolean;
  streaming: boolean;
  error: string | null;
  suggestedAction: CopilotAction | null;
  send: (text: string) => Promise<boolean>;
  openConversation: (id: string) => Promise<void>;
  dismissAction: () => void;
  reset: () => void;
}

const noop = () => {};
const asyncNoop = async () => false;

export const CopilotContext = createContext<CopilotContextType>({
  open: false,
  setOpen: noop,
  messages: [],
  conversations: [],
  conversationId: null,
  loadingHistory: false,
  streaming: false,
  error: null,
  suggestedAction: null,
  send: asyncNoop,
  openConversation: async () => {},
  dismissAction: noop,
  reset: noop,
});

export function useCopilot(): CopilotContextType {
  return useContext(CopilotContext);
}
