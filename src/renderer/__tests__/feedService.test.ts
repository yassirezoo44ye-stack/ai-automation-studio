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
import { MOCK_FEED } from "../features/feed/mock/feedData";
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

  it("returns isMock:true and MOCK_FEED when Discover returns empty", async () => {
    mockFetchDiscover.mockResolvedValueOnce({ items: [], total: 0 });

    const result = await loadFeedItems();

    expect(result.isMock).toBe(true);
    expect(result.items).toBe(MOCK_FEED);
  });

  it("returns isMock:true and MOCK_FEED when Discover throws", async () => {
    mockFetchDiscover.mockRejectedValueOnce(new Error("network error"));

    const result = await loadFeedItems();

    expect(result.isMock).toBe(true);
    expect(result.items).toBe(MOCK_FEED);
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
    const { user_liked, user_saved, likes_count, saves_count, ...rest } = BASE_CREATION;
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

/*
 * Limitation: FeedPage interaction tests (verify Like/Save API not called when
 * isMock=true, called when isMock=false) require React component rendering via
 * @testing-library/react. This setup does not exist in the current test suite
 * (all existing tests are pure utility/service unit tests). Skipping to avoid
 * inventing new infrastructure. The guard is enforced at the UI level via the
 * disabled prop on the Like/Save buttons in FeedActionPanel.
 */
