import type { FlowCreation, CreationType } from "../../discover/types/creation.types";
import { fetchDiscoverFeed } from "../../discover/services/discoverService";
import { MOCK_FEED } from "../mock/feedData";
import type { FeedItem, FeedContentType, CTAType, FeedCreator, FeedMedia } from "../types/feed.types";
import type { Page } from "../../../types";

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
    likes:       0,
    comments:    0,
    shares:      0,
    saves:       0,
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

/* ── Loader with MOCK_FEED fallback ─────────────────────────────── */
export async function loadFeedItems(): Promise<FeedItem[]> {
  try {
    const { items } = await fetchDiscoverFeed({ limit: 30 });
    if (items.length > 0) {
      return items.map(creationToFeedItem);
    }
  } catch {
    // Network unavailable or API error — fall through to mock
  }
  return MOCK_FEED;
}
