import type { FlowCreation, CreationType } from "../../discover/types/creation.types";
import { fetchDiscoverFeed } from "../../discover/services/discoverService";
import { API, apiFetch } from "../../../shared/utils/api";
import type { FeedItem, FeedContentType, CTAType, FeedCreator, FeedMedia } from "../types/feed.types";
import type { Page } from "../../../types";

export async function toggleLike(creationId: string): Promise<{ liked: boolean; count: number }> {
  const res = await apiFetch(`/api/creations/${creationId}/like`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function toggleSave(creationId: string): Promise<{ saved: boolean; count: number }> {
  const res = await apiFetch(`/api/creations/${creationId}/save`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/* ── Gradient palette per type ──────────────────────────────────── */
const TYPE_GRADIENTS: Record<string, string> = {
  APP:            "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
  AUTOMATION:     "linear-gradient(135deg, #064e3b 0%, #065f46 50%, #047857 100%)",
  AGENT:          "linear-gradient(135deg, #2e1065 0%, #4c1d95 50%, #5b21b6 100%)",
  WORKFLOW:       "linear-gradient(135deg, #451a03 0%, #78350f 50%, #92400e 100%)",
  TEMPLATE:       "linear-gradient(135deg, #831843 0%, #9d174d 50%, #be185d 100%)",
  DESIGN:         "linear-gradient(135deg, #4a044e 0%, #7e22ce 50%, #9333ea 100%)",
  DEVICE_WORKFLOW:"linear-gradient(135deg, #0c4a6e 0%, #075985 50%, #0369a1 100%)",
};

/* ── Type mappings ──────────────────────────────────────────────── */
const CTA_FOR_TYPE: Record<CreationType, CTAType> = {
  APP:            "build-app",
  AGENT:          "build-agent",
  WORKFLOW:       "run-workflow",
  AUTOMATION:     "use-automation",
  TEMPLATE:       "use-template",
  DEVICE_WORKFLOW:"run-workflow",
};

const PAGE_FOR_TYPE: Record<CreationType, Page> = {
  APP:            "app-builder",
  AGENT:          "agentos",
  WORKFLOW:       "automation",
  AUTOMATION:     "automation",
  TEMPLATE:       "design",
  DEVICE_WORKFLOW:"devices",
};

const DEFAULT_CREATOR: FeedCreator = {
  id:     "flow-platform",
  name:   "Flow Platform",
  handle: "@flow",
};

/* ── Mapper ─────────────────────────────────────────────────────── */
export function creationToFeedItem(c: FlowCreation): FeedItem {
  const feedType = c.type as FeedContentType;

  const media: FeedMedia = c.thumbnail_url
    ? { type: "image", src: c.thumbnail_url }
    : { type: "gradient", gradient: TYPE_GRADIENTS[c.type] ?? TYPE_GRADIENTS.APP };

  return {
    id:          c.id,
    type:        feedType,
    creator:     DEFAULT_CREATOR,
    title:       c.title,
    description: c.description ?? "",
    media,
    tags:        c.tags ?? [],
    likes:       c.likes_count ?? 0,
    comments:    0,
    shares:      0,
    saves:       c.saves_count ?? 0,
    userLiked:   c.user_liked ?? false,
    userSaved:   c.user_saved ?? false,
    ctaType:     CTA_FOR_TYPE[c.type] ?? "build-app",
    targetPage:  PAGE_FOR_TYPE[c.type] ?? "app-builder",
    sourceId:    c.source_id ?? undefined,
    sourceType:  "creation",
    sourceMeta:  {
      prompt:      c.description ?? c.title,
      title:       c.title,
      creationId:  c.id,
    },
  };
}

/* ── Loader ──────────────────────────────────────────────────── */
export async function loadFeedItems(): Promise<{ items: FeedItem[]; isMock: boolean; error: boolean }> {
  const [creations, lessons] = await Promise.allSettled([
    fetchDiscoverFeed({ limit: 30 }),
    loadStudyItems(),
  ]);
  const studyItems = lessons.status === "fulfilled" ? lessons.value : [];
  const creationItems = creations.status === "fulfilled" ? creations.value.items.map(creationToFeedItem) : [];
  // A failed source must not hide the other source's published content.
  return {
    items: [...studyItems, ...creationItems],
    isMock: false,
    error: creations.status === "rejected" || lessons.status === "rejected",
  };
}

async function loadStudyItems(): Promise<FeedItem[]> {
  const response = await apiFetch("/api/study-library/catalog?limit=30&offset=0");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const { lessons } = await response.json();
  return lessons.map((lesson: { slug: string; title: string; description: string; subject: string }) => ({
    id: `study:${lesson.slug}`,
    type: "STUDY",
    title: lesson.title,
    description: lesson.description,
    creator: DEFAULT_CREATOR,
    media: { type: "image", src: `${API}/api/study-library/lessons/${encodeURIComponent(lesson.slug)}/cover` },
    tags: [lesson.subject],
    likes: 0, comments: 0, shares: 0, saves: 0,
    ctaType: "use-template",
    targetPage: "study-library",
    sourceId: lesson.slug,
    sourceType: "slug",
  }));
}
