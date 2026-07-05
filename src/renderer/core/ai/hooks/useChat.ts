/**
 * Full-featured chat hook.
 * Handles streaming, history display, tool call display, conversation ID tracking,
 * and error state. Never references a provider directly.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { streamChunks } from "../streaming";
import type {
  ChatMessage,
  InferenceRequest,
  ToolCall,
  UsageStats,
} from "../types";

export interface DisplayMessage {
  id:        string;
  role:      "user" | "assistant" | "tool_result";
  content:   string;
  toolCalls: ToolCall[];
  usage?:    UsageStats;
  streaming: boolean;
}

export interface UseChatOptions {
  system?:          string;
  conversationId?:  string;
  provider?:        InferenceRequest["provider"];
  model?:           string;
  memoryEnabled?:   boolean;
  onConversationId?: (id: string) => void;
}

interface UseChatReturn {
  messages:       DisplayMessage[];
  isStreaming:     boolean;
  error:           string | null;
  conversationId:  string | null;
  send:            (userText: string, overrides?: Partial<InferenceRequest>) => Promise<void>;
  clear:           () => void;
}

let _msgId = 0;
const nextId = () => String(++_msgId);

export function useChat(options: UseChatOptions = {}): UseChatReturn {
  const [messages, setMessages]         = useState<DisplayMessage[]>([]);
  const [isStreaming, setIsStreaming]   = useState(false);
  const [error, setError]              = useState<string | null>(null);
  const [conversationId, setConvId]    = useState<string | null>(
    options.conversationId ?? null,
  );

  // Stable ref for options — avoids re-creating `send` on every render when
  // the caller passes an inline options object literal.
  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; });

  // Keep a mutable ref for the conversation ID so it's visible inside closures
  const convIdRef = useRef<string | null>(options.conversationId ?? null);

  const send = useCallback(
    async (userText: string, overrides: Partial<InferenceRequest> = {}) => {
      if (!userText.trim() || isStreaming) return;

      setError(null);

      // Build history from current messages for context
      const history: ChatMessage[] = messages
        .filter((m) => m.role !== "tool_result")
        .map((m) => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.content }));

      const userMsg: DisplayMessage = {
        id:        nextId(),
        role:      "user",
        content:   userText,
        toolCalls: [],
        streaming: false,
      };
      setMessages((prev) => [...prev, userMsg]);

      const assistantId = nextId();
      const assistantMsg: DisplayMessage = {
        id:        assistantId,
        role:      "assistant",
        content:   "",
        toolCalls: [],
        streaming: true,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setIsStreaming(true);

      const opts = optionsRef.current;
      const req: InferenceRequest = {
        messages: [...history, { role: "user", content: userText }],
        system:             opts.system,
        provider:           opts.provider,
        model:              opts.model,
        memory_enabled:     opts.memoryEnabled ?? false,
        conversation_id:    convIdRef.current ?? undefined,
        auto_execute_tools: true,
        ...overrides,
      };

      try {
        let accText      = "";
        const accTools:  ToolCall[] = [];
        let finalUsage:  UsageStats | undefined;

        for await (const chunk of streamChunks(req)) {
          switch (chunk.type) {
            case "conv_id":
              if (chunk.conv_id) {
                convIdRef.current = chunk.conv_id;
                setConvId(chunk.conv_id);
                options.onConversationId?.(chunk.conv_id);
              }
              break;

            case "delta":
              accText += chunk.text ?? "";
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: accText } : m,
                ),
              );
              break;

            case "tool_call":
              if (chunk.tool_call) {
                accTools.push(chunk.tool_call);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, toolCalls: [...accTools] } : m,
                  ),
                );
              }
              break;

            case "tool_result":
              setMessages((prev) => [
                ...prev,
                {
                  id:        nextId(),
                  role:      "tool_result",
                  content:   `**${chunk.tool_name}** → ${chunk.result}`,
                  toolCalls: [],
                  streaming: false,
                },
              ]);
              break;

            case "usage":
              finalUsage = chunk.usage;
              break;

            case "error":
              throw new Error(chunk.error ?? "Unknown stream error");
          }
        }

        // Finalize assistant message
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: accText, toolCalls: accTools, usage: finalUsage, streaming: false }
              : m,
          ),
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        // Mark assistant message as failed
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content || "(error)", streaming: false }
              : m,
          ),
        );
      } finally {
        setIsStreaming(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isStreaming, messages],
  );

  const clear = useCallback(() => {
    setMessages([]);
    setError(null);
    convIdRef.current = null;
    setConvId(null);
  }, []);

  return { messages, isStreaming, error, conversationId, send, clear };
}
