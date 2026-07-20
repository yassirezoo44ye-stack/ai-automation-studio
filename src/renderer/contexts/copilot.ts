// Copilot context + hook — split from CopilotContext.tsx so that file
// exports only its component (react-refresh/only-export-components).
import { createContext, useContext } from "react";

export interface CopilotMessage { id: string; role: "user" | "assistant"; content: string }

export interface CopilotAction { label: string; page: string }

export interface CopilotContextType {
  open: boolean;
  setOpen: (v: boolean) => void;
  messages: CopilotMessage[];
  streaming: boolean;
  error: string | null;
  suggestedAction: CopilotAction | null;
  send: (text: string) => void;
  dismissAction: () => void;
  reset: () => void;
}

const noop = () => {};

export const CopilotContext = createContext<CopilotContextType>({
  open: false,
  setOpen: noop,
  messages: [],
  streaming: false,
  error: null,
  suggestedAction: null,
  send: noop,
  dismissAction: noop,
  reset: noop,
});

export function useCopilot(): CopilotContextType {
  return useContext(CopilotContext);
}
