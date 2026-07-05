/**
 * CostClient — frontend client for cost tracking and spending limits.
 */
import { apiJSON } from "../../../shared/utils/api";

export interface CostSummary {
  total_usd:    number;
  record_count: number;
  by_provider:  Record<string, number>;
  by_agent:     Record<string, number>;
  limits:       { scope: string; limit_usd: number }[];
}

export interface UsageByProvider {
  provider_id: string;
  total_usd:   number;
}

export class CostClient {
  async summary(): Promise<CostSummary> {
    return apiJSON<CostSummary>("/api/ai/cost/summary");
  }

  async usage(since?: string): Promise<{ total_usd: number; by_provider: UsageByProvider[] }> {
    const params = since ? `?since=${encodeURIComponent(since)}` : "";
    return apiJSON(`/api/ai/usage${params}`);
  }

  async byProvider(since?: string): Promise<UsageByProvider[]> {
    const params = since ? `?since=${encodeURIComponent(since)}` : "";
    const data = await apiJSON<{ providers: UsageByProvider[] }>(`/api/ai/usage/providers${params}`);
    return data.providers ?? [];
  }
}

export const costClient = new CostClient();
