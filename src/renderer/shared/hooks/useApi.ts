import { useState, useCallback, useRef } from "react";

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface UseApiResult<T> extends ApiState<T> {
  execute: (...args: unknown[]) => Promise<T | null>;
  reset: () => void;
}

export function useApi<T>(
  fn: (...args: unknown[]) => Promise<T>,
): UseApiResult<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: false, error: null });
  const fnRef = useRef(fn);
  // eslint-disable-next-line react-hooks/refs
  fnRef.current = fn;

  const execute = useCallback(async (...args: unknown[]): Promise<T | null> => {
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      const data = await fnRef.current(...args);
      setState({ data, loading: false, error: null });
      return data;
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "An error occurred";
      setState(s => ({ ...s, loading: false, error: message }));
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null });
  }, []);

  return { ...state, execute, reset };
}
