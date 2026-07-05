// Types
export type {
  ChatMessage,
  CompletionResponse,
  Conversation,
  ConversationMessage,
  InferenceRequest,
  MemoryItem,
  PromptVersion,
  ProviderID,
  ProviderUsage,
  Role,
  StreamChunk,
  ToolCall,
  ToolSchema,
  UsageStats,
  UsageTotals,
} from "./types";

// Client
export {
  complete,
  createConversation,
  createPrompt,
  deleteConversation,
  deleteMemoryItem,
  getActivePromptVersion,
  getMessages,
  getUsageByProvider,
  getUsageTotals,
  listConversations,
  listPromptVersions,
  listProviders,
  listTools,
  publishPromptVersion,
  recallMemory,
  storeMemory,
  streamRaw,
} from "./client";

// Streaming
export { streamChunks, streamToText } from "./streaming";

// Hooks
export { useChat } from "./hooks/useChat";
export type { DisplayMessage, UseChatOptions } from "./hooks/useChat";
export { useProviders } from "./hooks/useProviders";
export { useUsage } from "./hooks/useUsage";
