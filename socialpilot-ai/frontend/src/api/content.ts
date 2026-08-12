// Content Strategy + AI Generation API calls. Goes through the same
// apiFetch() every other authenticated call uses (api/client.ts) — no
// second HTTP client, so 401-retry/CSRF/refresh-dedup all apply here too.
import { apiFetch } from "./client";
import type {
  ContentGeneration,
  ContentItem,
  ContentItemInput,
  ContentItemStatus,
  ContentItemUpdateInput,
  ContentPillar,
  ContentPillarInput,
  ContentStrategy,
  ContentStrategyInput,
  GenerateIdeasInput,
  GeneratePostInput,
} from "./contentTypes";

const base = (orgId: string) => `/organizations/${orgId}/content`;

// --- Strategies -------------------------------------------------------------

export function createStrategy(orgId: string, input: ContentStrategyInput): Promise<ContentStrategy> {
  return apiFetch<ContentStrategy>(`${base(orgId)}/strategies`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listStrategies(orgId: string): Promise<ContentStrategy[]> {
  return apiFetch<ContentStrategy[]>(`${base(orgId)}/strategies`);
}

export function getStrategy(orgId: string, strategyId: string): Promise<ContentStrategy> {
  return apiFetch<ContentStrategy>(`${base(orgId)}/strategies/${strategyId}`);
}

export function updateStrategy(
  orgId: string, strategyId: string, input: Partial<ContentStrategyInput>,
): Promise<ContentStrategy> {
  return apiFetch<ContentStrategy>(`${base(orgId)}/strategies/${strategyId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteStrategy(orgId: string, strategyId: string): Promise<void> {
  return apiFetch<void>(`${base(orgId)}/strategies/${strategyId}`, { method: "DELETE" });
}

// --- Pillars ------------------------------------------------------------------

export function createPillar(orgId: string, strategyId: string, input: ContentPillarInput): Promise<ContentPillar> {
  return apiFetch<ContentPillar>(`${base(orgId)}/strategies/${strategyId}/pillars`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listPillars(orgId: string, strategyId: string): Promise<ContentPillar[]> {
  return apiFetch<ContentPillar[]>(`${base(orgId)}/strategies/${strategyId}/pillars`);
}

export function deletePillar(orgId: string, pillarId: string): Promise<void> {
  return apiFetch<void>(`${base(orgId)}/pillars/${pillarId}`, { method: "DELETE" });
}

// --- Generation -----------------------------------------------------------------

export function generateIdeas(orgId: string, input: GenerateIdeasInput): Promise<ContentGeneration> {
  return apiFetch<ContentGeneration>(`${base(orgId)}/generate/ideas`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function generatePost(orgId: string, input: GeneratePostInput): Promise<ContentGeneration> {
  return apiFetch<ContentGeneration>(`${base(orgId)}/generate/post`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// --- Items (library) --------------------------------------------------------------

export function createItem(orgId: string, input: ContentItemInput): Promise<ContentItem> {
  return apiFetch<ContentItem>(`${base(orgId)}/items`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listItems(
  orgId: string, filters: { platform?: string; status?: ContentItemStatus } = {},
): Promise<ContentItem[]> {
  const params = new URLSearchParams();
  if (filters.platform) params.set("platform", filters.platform);
  if (filters.status) params.set("status", filters.status);
  const qs = params.toString();
  return apiFetch<ContentItem[]>(`${base(orgId)}/items${qs ? `?${qs}` : ""}`);
}

export function updateItem(orgId: string, itemId: string, input: ContentItemUpdateInput): Promise<ContentItem> {
  return apiFetch<ContentItem>(`${base(orgId)}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteItem(orgId: string, itemId: string): Promise<void> {
  return apiFetch<void>(`${base(orgId)}/items/${itemId}`, { method: "DELETE" });
}
