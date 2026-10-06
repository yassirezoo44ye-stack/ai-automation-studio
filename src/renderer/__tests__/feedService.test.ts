import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("../features/discover/services/discoverService");
vi.mock("../shared/utils/api");

import {
  loadFeedItems,
  toggleLike,
  toggleSave,
  creationToFeedItem,
} from "../features/feed/services/feedService";
import { fetchDiscoverFeed } from "../features/discover/services/discoverService";
import { apiFetch } from "../shared/utils/api";
import type { FlowCreation } from "../features/discover/types/creation.types";

const mockFetchDiscover = vi.mocked(fetchDiscoverFeed);
const mockApiFetch = vi.mocked(apiFetch);

const BASE_CREATION: FlowCreation = {
  id: "aaaaaaaa-0000-4000-8000-000000000001",
  organization_id: "org-1",
  created_by_user_id: "user-1",
  type: "APP",
  title: "My App",
  description: "A test app",
  visibility: "public",
  source_type: null,
  source_id: null,
  thumbnail_url: null,
  tags: ["test"],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  user_liked: false,
  user_saved: false,
  likes_count: 5,
  saves_count: 2,
};

beforeEach(() => {
  vi.clearAllMocks();
});

/* ── loadFeedItems ──────────────────────────────────────────────── */

describe("loadFeedItems", () => {
  it("returns isMock:false when Discover returns real items", async () => {
    mockFetchDiscover.mockResolvedValueOnce({
      items: [BASE_CREATION],
      total: 1,
    });

    const result = await loadFeedItems();

    expect(result.isMock).toBe(false);
    expect(result.items).toHaveLength(1);
    expect(result.items[0].id).toBe(BASE_CREATION.id);
  });

  it("returns isMock:false, error:false and empty items when Discover returns empty", async () => {
    mockFetchDiscover.mockResolvedValueOnce({ items: [], total: 0 });

    const result = await loadFeedItems();

    expect(result.isMock).toBe(false);
    expect(result.error).toBe(false);
    expect(result.items).toHaveLength(0);
  });

  it("returns error:true, isMock:false and empty items when Discover throws", async () => {
    mockFetchDiscover.mockRejectedValueOnce(new Error("network error"));

    const result = await loadFeedItems();

    expect(result.error).toBe(true);
    expect(result.isMock).toBe(false);
    expect(result.items).toHaveLength(0);
  });

  it("empty response and API error produce distinct states", async () => {
    mockFetchDiscover.mockResolvedValueOnce({ items: [], total: 0 });
    const emptyResult = await loadFeedItems();

    mockFetchDiscover.mockRejectedValueOnce(new Error("500"));
    const errorResult = await loadFeedItems();

    expect(emptyResult.error).toBe(false);
    expect(errorResult.error).toBe(true);
    expect(emptyResult.items).toHaveLength(0);
    expect(errorResult.items).toHaveLength(0);
  });

  it("maps real data correctly via creationToFeedItem", async () => {
    const creation: FlowCreation = {
      ...BASE_CREATION,
      user_liked: true,
      user_saved: true,
      likes_count: 42,
      saves_count: 7,
    };
    mockFetchDiscover.mockResolvedValueOnce({ items: [creation], total: 1 });

    const { items } = await loadFeedItems();
    const item = items[0];

    expect(item.userLiked).toBe(true);
    expect(item.userSaved).toBe(true);
    expect(item.likes).toBe(42);
    expect(item.saves).toBe(7);
  });
});

/* ── creationToFeedItem ─────────────────────────────────────────── */

describe("creationToFeedItem", () => {
  it("maps id, title, tags from FlowCreation", () => {
    const item = creationToFeedItem(BASE_CREATION);
    expect(item.id).toBe(BASE_CREATION.id);
    expect(item.title).toBe("My App");
    expect(item.tags).toEqual(["test"]);
  });

  it("uses gradient media when thumbnail_url is null", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, thumbnail_url: null });
    expect(item.media.type).toBe("gradient");
  });

  it("uses image media when thumbnail_url is set", () => {
    const item = creationToFeedItem({
      ...BASE_CREATION,
      thumbnail_url: "https://example.com/img.png",
    });
    expect(item.media.type).toBe("image");
    if (item.media.type === "image") {
      expect(item.media.src).toBe("https://example.com/img.png");
    }
  });

  it("defaults userLiked/userSaved/likes/saves to safe values when absent", () => {
    const { user_liked: _ul, user_saved: _us, likes_count: _lc, saves_count: _sc, ...rest } = BASE_CREATION;
    const item = creationToFeedItem(rest as FlowCreation);
    expect(item.userLiked).toBe(false);
    expect(item.userSaved).toBe(false);
    expect(item.likes).toBe(0);
    expect(item.saves).toBe(0);
  });
});

/* ── toggleLike / toggleSave ────────────────────────────────────── */

describe("toggleLike", () => {
  it("resolves with API JSON on 2xx", async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ liked: true, count: 6 }),
    } as Response);

    const result = await toggleLike("abc");
    expect(result).toEqual({ liked: true, count: 6 });
  });

  it("throws on non-2xx response", async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
    } as Response);

    await expect(toggleLike("bad-id")).rejects.toThrow("HTTP 404");
  });
});

describe("toggleSave", () => {
  it("throws on non-2xx response", async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
    } as Response);

    await expect(toggleSave("bad-id")).rejects.toThrow("HTTP 401");
  });

  it("resolves saved and count on 2xx", async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ saved: true, count: 3 }),
    } as Response);

    const result = await toggleSave("abc");
    expect(result).toEqual({ saved: true, count: 3 });
  });
});

/* ── CTA + routing mapping ──────────────────────────────────────── */

describe("creationToFeedItem — CTA and routing", () => {
  it("maps APP type to build-app ctaType and app-builder targetPage", () => {
    const item = creationToFeedItem(BASE_CREATION);
    expect(item.ctaType).toBe("build-app");
    expect(item.targetPage).toBe("app-builder");
  });

  it("maps AGENT type to build-agent ctaType and agentos targetPage", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, type: "AGENT" });
    expect(item.ctaType).toBe("build-agent");
    expect(item.targetPage).toBe("agentos");
  });

  it("maps AUTOMATION type to use-automation ctaType and automation targetPage", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, type: "AUTOMATION" });
    expect(item.ctaType).toBe("use-automation");
    expect(item.targetPage).toBe("automation");
  });

  it("maps WORKFLOW type to run-workflow ctaType and automation targetPage", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, type: "WORKFLOW" });
    expect(item.ctaType).toBe("run-workflow");
    expect(item.targetPage).toBe("automation");
  });

  it("maps TEMPLATE type to use-template ctaType", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, type: "TEMPLATE" });
    expect(item.ctaType).toBe("use-template");
  });
});

/* ── FeedIntent field preservation ─────────────────────────────── */

describe("creationToFeedItem — FeedIntent fields", () => {
  it("sets sourceType to 'creation'", () => {
    const item = creationToFeedItem(BASE_CREATION);
    expect(item.sourceType).toBe("creation");
  });

  it("carries source_id as sourceId", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, source_id: "tpl-sales-v2" });
    expect(item.sourceId).toBe("tpl-sales-v2");
  });

  it("sourceMeta contains creationId and title", () => {
    const item = creationToFeedItem(BASE_CREATION);
    expect(item.sourceMeta).toMatchObject({
      creationId: BASE_CREATION.id,
      title: BASE_CREATION.title,
    });
  });

  it("sourceMeta.prompt falls back to title when description is absent", () => {
    const item = creationToFeedItem({ ...BASE_CREATION, description: null as unknown as string });
    expect(item.sourceMeta?.prompt).toBe(BASE_CREATION.title);
  });

  it("loadFeedItems produces items with isMock:false (never returns mock data)", async () => {
    mockFetchDiscover.mockResolvedValueOnce({ items: [BASE_CREATION], total: 1 });
    const { items, isMock } = await loadFeedItems();
    expect(isMock).toBe(false);
    expect(items[0].sourceType).toBe("creation");
  });
});

/*
 * Limitation: FeedPage interaction tests (verify Like/Save API not called when
 * isMock=true, called when isMock=false) require React component rendering via
 * @testing-library/react. This setup does not exist in the current test suite
 * (all existing tests are pure utility/service unit tests). Skipping to avoid
 * inventing new infrastructure. The guard is enforced at the UI level via the
 * disabled prop on the Like/Save buttons in FeedActionPanel.
 */
