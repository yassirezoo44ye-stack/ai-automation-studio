/**
 * DiagnosticsClient — frontend client for the AI diagnostics dashboard.
 */
import { apiJSON } from "../../../shared/utils/api";

export interface Phase3Diagnostics {
  orchestrator: Record<string, unknown> | null;
  streaming:    { active_sessions: number; total_tokens: number };
  knowledge:    { documents: number; chunks: number } | null;
  marketplace:  { catalog_size: number; plugin_count: number; categories: string[] } | null;
  cost:         { total_usd: number; record_count: number; by_provider: Record<string, number> };
  agents:       string[];
  workflow_execs: number;
}

export interface DiagnosticsReport {
  providers:    Record<string, unknown>;
  models:       unknown[];
  metrics:      Record<string, unknown>;
  cache:        Record<string, unknown>;
  tools:        Record<string, unknown>;
  event_bus:    Record<string, unknown>;
  phase3:       Phase3Diagnostics;
}

export class DiagnosticsClient {
  async report(includeDb = false): Promise<DiagnosticsReport> {
    return apiJSON<DiagnosticsReport>(
      `/api/ai/diagnostics${includeDb ? "?include_db=true" : ""}`,
    );
  }

  async costSummary(): Promise<Phase3Diagnostics["cost"]> {
    const report = await this.report();
    return report.phase3.cost;
  }

  async agentList(): Promise<string[]> {
    const report = await this.report();
    return report.phase3.agents ?? [];
  }
}

export const diagnosticsClient = new DiagnosticsClient();
