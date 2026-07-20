/**
 * useAsyncData — the one hook every list/detail view uses to fetch data.
 *
 * Encapsulates the state machine every page was previously reimplementing
 * ad hoc (see ChatTab.loadConvs pre-fix: `try { setConvs(await ...) } catch {}`
 * — no loading indicator, silently swallowed errors, no retry, stale
 * responses could clobber newer ones when a dependency changed mid-fetch).
 *
 * - status is derived, not stored redundantly: 'loading' while no data has
 *   ever loaded, 'refreshing' while re-fetching with existing data still on
 *   screen (so the UI can keep showing stale content instead of blanking),
 *   'error' | 'empty' | 'success' once a fetch has completed.
 * - refetch() is retry AND manual-refresh — one code path for both.
 * - Out-of-order responses are dropped: if deps change while a fetch is in
 *   flight, the stale response is ignored when it resolves.
 * - refetchInterval opts a view into polling; refetchOnFocus opts it into
 *   refreshing when the tab regains focus. Both default off — most views
 *   should refetch on mount + after mutations, not on a timer.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { APIError } from "../utils/api";

export type AsyncStatus = "loading" | "refreshing" | "success" | "empty" | "error";

export interface UseAsyncDataOptions<T> {
  /** Skip fetching (e.g. a tab that's not active yet). Default true. */
  enabled?: boolean;
  /** A value is "empty" (distinct from error) when this returns true. Default: array with length 0. */
  isEmpty?: (data: T) => boolean;
  /** Poll every N ms while mounted and enabled. Off by default. */
  refetchInterval?: number;
  /** Re-fetch when the browser tab/window regains focus. Off by default. */
  refetchOnFocus?: boolean;
}

export interface UseAsyncDataResult<T> {
  data: T | undefined;
  status: AsyncStatus;
  /** Human-readable message — APIError's probableCause/suggestedFix when available. */
  error: string | null;
  suggestedFix: string | null;
  refetch: () => void;
}

function defaultIsEmpty(data: unknown): boolean {
  return Array.isArray(data) && data.length === 0;
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: React.DependencyList,
  options: UseAsyncDataOptions<T> = {},
): UseAsyncDataResult<T> {
  const { enabled = true, isEmpty = defaultIsEmpty as (d: T) => boolean, refetchInterval, refetchOnFocus } = options;

  const [data, setData] = useState<T | undefined>(undefined);
  const [status, setStatus] = useState<AsyncStatus>(enabled ? "loading" : "success");
  const [error, setError] = useState<string | null>(null);
  const [suggestedFix, setSuggestedFix] = useState<string | null>(null);

  // Bumped on every fetch start; a response is applied only if it's still
  // the most recent request when it resolves — guards against a fast
  // project-switch racing a slow one and clobbering fresher data.
  const requestIdRef = useRef(0);
  const fetcherRef = useRef(fetcher);
  // Refs sync outside render (not during) so a fresh fetcher closure is
  // always available to `run` without making it a dependency itself.
  useEffect(() => { fetcherRef.current = fetcher; });

  const run = useCallback(async (isRefetch: boolean) => {
    const requestId = ++requestIdRef.current;
    setStatus(prev => (isRefetch && prev === "success") || prev === "refreshing" ? "refreshing" : "loading");
    setError(null);
    setSuggestedFix(null);
    try {
      const result = await fetcherRef.current();
      if (requestIdRef.current !== requestId) return; // superseded by a newer request
      setData(result);
      setStatus(isEmpty(result) ? "empty" : "success");
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      const msg = err instanceof APIError ? err.details.probableCause ?? err.message
                : err instanceof Error ? err.message
                : "Something went wrong.";
      setError(msg);
      setSuggestedFix(err instanceof APIError ? err.details.suggestedFix ?? null : null);
      setStatus("error");
    }
  }, [isEmpty]);

  useEffect(() => {
    if (!enabled) {
      // A disabled hook (e.g. no conversation selected yet) must not keep
      // reporting the previous target's data/status — otherwise a caller
      // that gates rendering on `enabled` can still observe stale loading/
      // error/data from whatever was last fetched before it was disabled.
      requestIdRef.current++;
      void Promise.resolve().then(() => {
        setData(undefined);
        setError(null);
        setSuggestedFix(null);
        setStatus("success");
      });
      return;
    }
    // Deferred a microtask so the fetch (and its eventual setState) runs
    // outside the effect's own commit, not synchronously within it.
    void Promise.resolve().then(() => run(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  useEffect(() => {
    if (!enabled || !refetchInterval) return;
    const id = setInterval(() => void run(true), refetchInterval);
    return () => clearInterval(id);
  }, [enabled, refetchInterval, run]);

  useEffect(() => {
    if (!enabled || !refetchOnFocus) return;
    const onFocus = () => void run(true);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [enabled, refetchOnFocus, run]);

  const refetch = useCallback(() => { void run(true); }, [run]);

  return { data, status, error, suggestedFix, refetch };
}
