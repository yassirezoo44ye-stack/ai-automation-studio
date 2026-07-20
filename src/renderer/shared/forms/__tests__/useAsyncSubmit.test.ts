import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { useAsyncSubmit } from "../useAsyncSubmit";
import { APIError } from "../../utils/api";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("useAsyncSubmit", () => {
  it("tracks isSubmitting -> success across a resolving call", async () => {
    const { result } = renderHook(() => useAsyncSubmit<string>());
    const d = deferred<string>();
    act(() => result.current.run(() => d.promise));
    expect(result.current.isSubmitting).toBe(true);
    expect(result.current.success).toBe(false);
    await act(async () => { d.resolve("ok"); await d.promise; });
    await waitFor(() => expect(result.current.isSubmitting).toBe(false));
    expect(result.current.success).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("surfaces APIError's probableCause/suggestedFix on rejection, not a generic message", async () => {
    const { result } = renderHook(() => useAsyncSubmit<void>());
    const err = new APIError("boom", { url: "/x", status: 401, contentType: "application/json", probableCause: "Session expired", suggestedFix: "Log in again" });
    await act(async () => {
      result.current.run(() => Promise.reject(err));
      await Promise.resolve().then(() => Promise.resolve()); // let the microtask chain settle
    });
    await waitFor(() => expect(result.current.error).toBe("Session expired"));
    expect(result.current.suggestedFix).toBe("Log in again");
    expect(result.current.success).toBe(false);
  });

  it("ignores a second run() while one is already in flight — prevents duplicate submissions", () => {
    const fn = vi.fn(() => new Promise<void>(() => {})); // never resolves
    const { result } = renderHook(() => useAsyncSubmit<void>());
    act(() => result.current.run(fn));
    act(() => result.current.run(fn));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("retry() re-invokes the last submitted function", async () => {
    const fn = vi.fn().mockResolvedValueOnce(undefined).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useAsyncSubmit<void>());
    await act(async () => { result.current.run(fn); });
    await waitFor(() => expect(result.current.success).toBe(true));
    await act(async () => { result.current.retry(); });
    await waitFor(() => expect(fn).toHaveBeenCalledTimes(2));
  });

  it("cancel() aborts the in-flight signal and stops reporting isSubmitting", async () => {
    const { result } = renderHook(() => useAsyncSubmit<void>());
    let sawAbort = false;
    act(() => result.current.run(signal => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => { sawAbort = true; reject(new DOMException("aborted", "AbortError")); });
    })));
    expect(result.current.isSubmitting).toBe(true);
    act(() => result.current.cancel());
    expect(result.current.isSubmitting).toBe(false);
    await waitFor(() => expect(sawAbort).toBe(true));
    // An aborted call must not surface as a user-facing error.
    expect(result.current.error).toBeNull();
  });

  it("a superseded run (cancelled, then re-run) does not let the stale call overwrite fresher state", async () => {
    const { result } = renderHook(() => useAsyncSubmit<string>());
    const first = deferred<string>();
    const second = deferred<string>();

    act(() => result.current.run(() => first.promise));
    expect(result.current.isSubmitting).toBe(true);

    act(() => result.current.cancel()); // separate act() so React re-renders isSubmitting=false first
    expect(result.current.isSubmitting).toBe(false);

    await act(async () => { result.current.run(() => second.promise); second.resolve("second"); await second.promise; });
    await waitFor(() => expect(result.current.success).toBe(true));

    // The first (cancelled) promise resolving late must not flip state back.
    await act(async () => { first.resolve("first-late"); await first.promise.catch(() => {}); });
    expect(result.current.success).toBe(true);
  });
});
