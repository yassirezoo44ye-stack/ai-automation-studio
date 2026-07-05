/**
 * Provider-agnostic AI types — mirrors the backend's Pydantic models.
 * No provider SDK imports live here or anywhere in this layer.
 */

export type ProviderID = "anthropic" | "openai" | "gemini";

export type Role = "system" | "user" | "assistant" | "tool";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface ToolSchema {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface UsageStats {
  input_tokens:  number;
  output_tokens: number;
  total_tokens:  number;
  cost_usd:      number;
  provider:      string;
  model:         string;
  cached:        boolean;
}

/** Request sent to POST /api/ai/complete or POST /api/ai/stream */
export interface InferenceRequest {
  messages:            ChatMessage[];
  provider?:           ProviderID;
  model?:              string;
  fallback_providers?: ProviderID[];
  max_tokens?:         number;
  temperature?:        number;
  top_p?:              number;
  system?:             string;
  tools?:              ToolSchema[];
  conversation_id?:    string;
  prompt_id?:          string;
  prompt_variables?:   Record<string, string>;
  cache_ttl?:          number;
  memory_enabled?:     boolean;
  timeout?:            number;
  max_retries?:        number;
  auto_execute_tools?: boolean;
}

/** Response from POST /api/ai/complete */
export interface CompletionResponse {
  id:              string;
  content:         string;
  tool_calls:      ToolCall[];
  finish_reason:   string;
  usage:           UsageStats;
  conversation_id: string | null;
  cached:          boolean;
}

/** One SSE chunk from POST /api/ai/stream */
export interface StreamChunk {
  type:       "delta" | "tool_call" | "tool_result" | "usage" | "done" | "error" | "conv_id";
  text?:      string;
  tool_call?: ToolCall;
  tool_name?: string;
  result?:    string;
  usage?:     UsageStats;
  error?:     string;
  conv_id?:   string;
}

export interface Conversation {
  id:         string;
  title:      string;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id:           string;
  role:         Role;
  content:      string;
  tool_call_id: string | null;
  created_at:   string;
}

export interface MemoryItem {
  id:              string;
  content:         string;
  importance:      number;
  conversation_id: string | null;
  created_at:      string;
}

export interface PromptVersion {
  id:            string;
  prompt_id:     string;
  version:       number;
  system:        string | null;
  user_template: string | null;
  variables:     string[];
  created_at:    string;
  is_active:     boolean;
}

export interface UsageTotals {
  calls:        number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cost_usd:     number | null;
  cached_calls: number;
}

export interface ProviderUsage {
  provider:     string;
  model:        string;
  calls:        number;
  total_tokens: number;
  cost_usd:     number;
}
