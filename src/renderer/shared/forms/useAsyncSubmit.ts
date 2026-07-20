/**
 * useAsyncSubmit — the submit-lifecycle half of the form architecture
 * (useForm owns field/validation state; this owns loading/success/error/
 * cancel/retry/timeout for the network call triggered on valid submit).
 *
 * The work function is supplied at call time (`run(fn)`), not fixed at
 * hook-creation — so it works equally for existing functions that don't
 * accept an AbortSignal (AuthContext's login/register: cancellation there
 * just means "ignore this call's eventual result", the in-flight request
 * itself can't be aborted without changing that API) and for new fetch-
 * based submits that do (`run(signal => apiFetch(url, { signal, ... }))`,
 * where cancel() genuinely aborts the network request).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { APIError } from "../utils/api";

export interface UseAsyncSubmitOptions {
  /** Abort (and report a timeout error) if the submit hasn't resolved within this long. Off by default. */
  timeoutMs?: number;
  onSuccess?: () => void;
}

export interface UseAsyncSubmitResult<T> {
  run: (submitFn: (signal: AbortSignal) => Promise<T>) => void;
  isSubmitting: boolean;
  success: boolean;
  error: string | null;
  suggestedFix: string | null;
  /** Aborts the in-flight signal (real cancellation for signal-aware submitFns) and stops reporting its result either way. */
  cancel: () => void;
  /** Re-runs the last submitFn passed to run() — the Retry button's onClick. */
  retry: () => void;
  reset: () => void;
}

export function useAsyncSubmit<T = void>(options: UseAsyncSubmitOptions = {}): UseAsyncSubmitResult<T> {
  const { timeoutMs, onSuccess } = options;
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedFix, setSuggestedFix] = useState<string | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  const lastFnRef = useRef<((signal: AbortSignal) => Promise<T>) | null>(null);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; controllerRef.current?.abort(); }, []);

  const run = useCallback((submitFn: (signal: AbortSignal) => Promise<T>) => {
    if (isSubmitting) return; // prevent duplicate submissions
    lastFnRef.current = submitFn;
    controllerRef.current?.abort(); // cancel any previous in-flight submit
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestIdRef.current;

    setIsSubmitting(true);
    setSuccess(false);
    setError(null);
    setSuggestedFix(null);

    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    if (timeoutMs) timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    void submitFn(controller.signal)
      .then(() => {
        if (timeoutId) clearTimeout(timeoutId);
        if (!mountedRef.current || requestIdRef.current !== requestId) return; // unmounted or superseded — safe no-op
        setIsSubmitting(false);
        setSuccess(true);
        onSuccess?.();
      })
      .catch((err: unknown) => {
        if (timeoutId) clearTimeout(timeoutId);
        if (!mountedRef.current || requestIdRef.current !== requestId) return;
        if (err instanceof DOMException && err.name === "AbortError") {
          // Explicit cancel() — not an error the user needs to see.
          setIsSubmitting(false);
          return;
        }
        setIsSubmitting(false);
        setSuccess(false);
        if (err instanceof APIError) {
          setError(err.details.probableCause ?? err.message);
          setSuggestedFix(err.details.suggestedFix ?? null);
        } else if (err instanceof Error) {
          setError(err.message || "Something went wrong.");
        } else {
          setError("Something went wrong.");
        }
      });
  }, [isSubmitting, timeoutMs, onSuccess]);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setIsSubmitting(false);
  }, []);

  const retry = useCallback(() => {
    if (lastFnRef.current) run(lastFnRef.current);
  }, [run]);

  const reset = useCallback(() => {
    setIsSubmitting(false); setSuccess(false); setError(null); setSuggestedFix(null);
  }, []);

  return { run, isSubmitting, success, error, suggestedFix, cancel, retry, reset };
}
