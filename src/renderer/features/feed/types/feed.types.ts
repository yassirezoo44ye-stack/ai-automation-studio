import type { Page } from "../../../types";

/** Content categories shown in the Feed */
export type FeedContentType =
  | "APP"
  | "AUTOMATION"
  | "AGENT"
  | "WORKFLOW"
  | "TEMPLATE"
  | "DESIGN";

/** Top-bar navigation tabs */
export type FeedTab = "for-you" | "following" | "explore";

/** The CTA action type — drives both label and navigator */
export type CTAType =
  | "build-app"
  | "use-automation"
  | "build-agent"
  | "run-workflow"
  | "use-template"
  | "open-design";

/** Media attached to a feed card (Phase 1: gradient or static image) */
export interface FeedMedia {
  /** "gradient" = CSS gradient string; "image" = static URL; "video" = future */
  type: "gradient" | "image" | "video";
  /** CSS gradient string (when type === "gradient") */
  gradient?: string;
  /** URL for image or video poster */
  src?: string;
  /** Poster frame for video (future) */
  poster?: string;
}

export interface FeedCreator {
  id: string;
  name: string;
  handle: string;
  /** Avatar URL — optional; initials shown as fallback */
  avatar?: string;
}

/**
 * Core feed item model.
 *
 * Designed so Phase 1 mock data and future API responses use identical shape.
 * `sourceId` + `sourceMeta` carry enough info for the builder to load a
 * specific template/project/automation on CTA press (Phase 2).
 */
export interface FeedItem {
  id: string;
  type: FeedContentType;
  creator: FeedCreator;
  title: string;
  /** Short description shown in the bottom overlay */
  description: string;
  media: FeedMedia;
  tags: string[];
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  /** Drives CTA button label */
  ctaType: CTAType;
  /** Page to navigate to when CTA is pressed */
  targetPage: Page;
  /** Future: ID of the template / automation / project to open in the builder */
  sourceId?: string;
  /** Future: additional builder context (prompt, config, etc.) */
  sourceMeta?: Record<string, unknown>;
  /** Whether the current user has liked/saved this item (local state seed) */
  userLiked?: boolean;
  userSaved?: boolean;
}

/** Local interaction state per item (not persisted in Phase 1) */
export interface FeedItemState {
  liked: boolean;
  saved: boolean;
  likes: number;
  saves: number;
}
