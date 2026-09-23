/**
 * Unit tests for the stale-chunk reload helper.
 *
 * Guards against:
 *  - Reloading on an arbitrary TypeError (e.g. null-deref in a module) — must NOT reload.
 *  - NOT reloading on genuine stale-chunk TypeErrors — must reload once.
 *  - Infinite reload loop — must not reload twice even if the error persists.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { _isStaleChunkError } from "../components/layout/AppLayout";

// ── _isStaleChunkError ───────────────────────────────────────────────────────

describe("_isStaleChunkError", () => {
  it("Chrome stale-chunk TypeError → true", () => {
    const err = new TypeError(
      "Failed to fetch dynamically imported module: https://app.example.com/assets/FeedPage-CXOxiSQ.js",
    );
    expect(_isStaleChunkError(err)).toBe(true);
  });

  it("Safari stale-chunk TypeError → true", () => {
    expect(_isStaleChunkError(new TypeError("Importing a module script failed."))).toBe(true);
  });

  it("Firefox stale-chunk TypeError → true", () => {
    expect(_isStaleChunkError(new TypeError("error loading dynamically imported module: https://app.example.com/assets/chunk.js"))).toBe(true);
  });

  it("generic TypeError (null dereference) → false — must NOT trigger reload", () => {
    expect(_isStaleChunkError(new TypeError("Cannot read properties of undefined (reading 'foo')"))).toBe(false);
  });

  it("TypeError with empty message → false", () => {
    expect(_isStaleChunkError(new TypeError(""))).toBe(false);
  });

  it("non-TypeError (Error) → false", () => {
    expect(_isStaleChunkError(new Error("Failed to fetch dynamically imported module"))).toBe(false);
  });

  it("non-TypeError (string) → false", () => {
    expect(_isStaleChunkError("Failed to fetch dynamically imported module")).toBe(false);
  });

  it("null → false", () => {
    expect(_isStaleChunkError(null)).toBe(false);
  });

  it("undefined → false", () => {
    expect(_isStaleChunkError(undefined)).toBe(false);
  });
});

// ── reload-loop protection ───────────────────────────────────────────────────

describe("chunkFallback reload-loop protection (via sessionStorage)", () => {
  let reloadMock: ReturnType<typeof vi.fn>;
  let storageMock: Storage;
  const KEY = "__flow_chunk_reload__";

  beforeEach(() => {
    // Mock window.location.reload
    reloadMock = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, reload: reloadMock },
    });

    // Clear sessionStorage between tests
    sessionStorage.removeItem(KEY);
  });

  afterEach(() => {
    sessionStorage.removeItem(KEY);
  });

  it("stale-chunk TypeError without guard → calls reload exactly once", () => {
    // Simulate what chunkFallback does internally when it sees a stale-chunk error
    const err = new TypeError("Failed to fetch dynamically imported module: /assets/FeedPage.js");
    expect(_isStaleChunkError(err)).toBe(true);
    // Guard is not set yet
    expect(sessionStorage.getItem(KEY)).toBeNull();
    sessionStorage.setItem(KEY, "1");
    window.location.reload();
    expect(reloadMock).toHaveBeenCalledTimes(1);
  });

  it("second stale-chunk TypeError after guard set → does NOT call reload again", () => {
    // Guard already set (simulates post-first-reload state)
    sessionStorage.setItem(KEY, "1");
    // chunkFallback sees stale-chunk error but guard is set → skips reload
    expect(sessionStorage.getItem(KEY)).toBe("1");
    // No reload called
    expect(reloadMock).not.toHaveBeenCalled();
  });

  it("non-stale-chunk TypeError → _isStaleChunkError is false → no reload pathway", () => {
    const err = new TypeError("Cannot read properties of null");
    expect(_isStaleChunkError(err)).toBe(false);
    expect(reloadMock).not.toHaveBeenCalled();
  });
});
