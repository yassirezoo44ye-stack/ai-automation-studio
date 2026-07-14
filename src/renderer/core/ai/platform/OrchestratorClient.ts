/**
 * OrchestratorClient — frontend client for the AIOrchestrator.
 * Sends requests through the enterprise orchestration pipeline.
 */
import { apiJSON, apiFetch, parseJSON } from "../../../shared/utils/api";

export interface OrchestratorRequest {
  prompt:           string;
  mode?:            "auto" | "single" | "multi-agent";
  conversation_id?: string;
  project_id?:      string;
  max_cost_usd?:    number;
  context?:         Record<string, unknown>;
}

export interface TaskSummary {
  id:     string;
  type:   string;
  desc:   string;
  result: Record<string, unknown>;
}

export interface OrchestratorResult {
  request_id:   string;
  content:      string;
  tasks:        TaskSummary[];
  total_cost:   number;
  total_tokens: number;
  success:      boolean;
  errors:       string[];
  metadata:     Record<string, unknown>;
}

export class OrchestratorClient {
  async run(request: OrchestratorRequest): Promise<OrchestratorResult> {
    return apiJSON<OrchestratorResult>("/api/ai/orchestrate", {
      method: "POST",
      body:   JSON.stringify(request),
    });
  }

  async *stream(
    request: OrchestratorRequest,
  ): AsyncGenerator<{ type: string; content?: string; [k: string]: unknown }> {
    const res = await apiFetch("/api/ai/orchestrate/stream", {
      method: "POST",
      body:   JSON.stringify(request),
    });

    if (!res.ok || !res.body) {
      const err = await parseJSON<{ detail?: string }>(res, "/api/ai/orchestrate/stream").catch(() => ({ detail: "Stream failed" }));
      throw new Error(err.detail ?? "Stream failed");
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part.split("\n").find(l => l.startsWith("data:"));
        if (dataLine) {
          try { yield JSON.parse(dataLine.slice(5).trim()); } catch { /* skip malformed */ }
        }
      }
    }
  }
}

export const orchestratorClient = new OrchestratorClient();
