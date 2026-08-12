// Mirrors backend/app/schemas/content.py — see api/types.ts's note on why
// this is hand-kept in sync rather than generated, for now.

export interface ContentStrategy {
  id: string;
  organization_id: string;
  name: string;
  business_description: string;
  target_audience: string;
  goals: string;
  tone: string;
  language: string;
  brand_voice: string;
  content_preferences: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContentStrategyInput {
  name: string;
  business_description?: string;
  target_audience?: string;
  goals?: string;
  tone?: string;
  language?: string;
  brand_voice?: string;
  content_preferences?: Record<string, unknown>;
}

export interface ContentPillar {
  id: string;
  organization_id: string;
  strategy_id: string;
  name: string;
  description: string | null;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface ContentPillarInput {
  name: string;
  description?: string;
  priority?: number;
}

export type GenerationStatus = "succeeded" | "failed";
export type GenerationType = "ideas" | "post";

export interface GeneratedIdea {
  title: string;
  hook: string;
  concept: string;
  pillar: string;
  suggested_platform: string;
  cta: string;
}

export interface GeneratedPost {
  hook: string;
  body: string;
  cta: string;
  hashtags: string[];
  platform: string;
  media_concept: string;
}

export interface ContentGeneration {
  id: string;
  organization_id: string;
  strategy_id: string;
  generation_type: GenerationType;
  platform: string | null;
  status: GenerationStatus;
  model: string;
  result: { ideas: GeneratedIdea[] } | GeneratedPost | null;
  error: string | null;
  created_at: string;
}

export interface GenerateIdeasInput {
  strategy_id: string;
  pillar_id?: string;
  platform?: string;
  tone?: string;
  language?: string;
  count?: number;
}

export interface GeneratePostInput {
  strategy_id: string;
  pillar_id?: string;
  platform: string;
  content_type?: string;
  tone?: string;
  language?: string;
  brief?: string;
}

export type ContentItemStatus = "draft" | "approved" | "archived";

export interface ContentItem {
  id: string;
  organization_id: string;
  strategy_id: string | null;
  generation_id: string | null;
  platform: string;
  title: string | null;
  body: string;
  hashtags: string[];
  status: ContentItemStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContentItemInput {
  strategy_id?: string | null;
  generation_id?: string | null;
  platform: string;
  title?: string | null;
  body: string;
  hashtags?: string[];
  status?: ContentItemStatus;
  metadata?: Record<string, unknown>;
}

export interface ContentItemUpdateInput {
  title?: string | null;
  body?: string;
  hashtags?: string[];
  status?: ContentItemStatus;
  metadata?: Record<string, unknown>;
}
