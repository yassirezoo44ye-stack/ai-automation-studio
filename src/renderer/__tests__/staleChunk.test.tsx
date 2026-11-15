/**
 * Stale-chunk recovery after a deploy (FE-01).
 *
 * Guards against:
 *  - reloading on an ordinary TypeError thrown inside a module;
 *  - the old guard, a sessionStorage flag that was never cleared, so only
 *    the first deploy per tab was ever recovered (reproduced in a real
 *    browser: the second deploy left "Failed to fetch dynamically imported
 *    module" on screen, and Retry could not clear it);
 *  - reloading in a loop when a chunk is genuinely missing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Suspense } from "react";
import type { ComponentType } from "react";
import {
  isStaleChunkError, reloadForNewBuild, lazyPage, RELOAD_COOLDOWN_MS,
} from "../shared/lib/staleChunk";
import { ErrorBoundary } from "../shared/ui/ErrorBoundary";

const STALE = () => new TypeError(
  "Failed to fetch dynamically imported module: https://app.example.com/assets/LeadsPage-CXOxiSQ.js");

describe("isStaleChunkError", () => {
  it.each([
    ["Chrome", STALE()],
    ["Safari", new TypeError("Importing a module script failed.")],
    ["Firefox", new TypeError("error loading dynamically imported module: https://app.example.com/assets/c.js")],
    ["Vite CSS preload", new Error("Unable to preload CSS for /assets/LeadsPage-x.css")],
  ])("%s → true", (_name, err) => {
    expect(isStaleChunkError(err)).toBe(true);
  });

  it.each([
    ["null dereference", new TypeError("Cannot read properties of undefined (reading 'foo')")],
    ["empty TypeError", new TypeError("")],
    ["plain Error with the message", new Error("Failed to fetch dynamically imported module")],
    ["string", "Failed to fetch dynamically imported module"],
    ["null", null],
    ["undefined", undefined],
  ])("%s → false", (_name, err) => {
    expect(isStaleChunkError(err)).toBe(false);
  });
});

describe("reloadForNewBuild", () => {
  let reload: ReturnType<typeof vi.fn>;
  const original = window.location;

  beforeEach(() => {
    sessionStorage.clear();
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true, value: { ...original, reload },
    });
  });
  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: original });
    sessionStorage.clear();
  });

  it("reloads on the first stale chunk", () => {
    expect(reloadForNewBuild(1_000_000)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not loop when the chunk still fails right after the reload", () => {
    reloadForNewBuild(1_000_000);
    expect(reloadForNewBuild(1_000_000 + 2_000)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("recovers a later deploy in the same tab", () => {
    reloadForNewBuild(1_000_000);
    expect(reloadForNewBuild(1_000_000 + RELOAD_COOLDOWN_MS + 1)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("does not reload without sessionStorage (no loop guard available)", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(reloadForNewBuild()).toBe(false);
    expect(reload).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("lazyPage + ErrorBoundary", () => {
  let reload: ReturnType<typeof vi.fn>;
  const original = window.location;

  beforeEach(() => {
    sessionStorage.clear();
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true, value: { ...original, reload },
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: original });
    vi.restoreAllMocks();
  });

  it("stale chunk → reloads, and the error screen offers Reload, not a dead Retry", async () => {
    const Page = lazyPage<ComponentType>(() => Promise.reject(STALE()));
    render(<ErrorBoundary name="leads"><Suspense fallback="…"><Page /></Suspense></ErrorBoundary>);
    expect(await screen.findByText("A new version of Flow is available")).toBeTruthy();
    expect(reload).toHaveBeenCalledTimes(1);   // automatic reload
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(2);   // the button reloads too
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("an ordinary error inside the page does not reload and keeps Retry", async () => {
    const Page = lazyPage<ComponentType>(() => Promise.reject(new TypeError("Cannot read properties of undefined")));
    render(<ErrorBoundary name="leads"><Suspense fallback="…"><Page /></Suspense></ErrorBoundary>);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });

  it("loads the component normally", async () => {
    const Page = lazyPage(() => Promise.resolve(() => <p>leads ready</p>));
    render(<Suspense fallback="…"><Page /></Suspense>);
    expect(await screen.findByText("leads ready")).toBeTruthy();
  });
});
