import { useEffect, useState } from "react";
import { listProviders } from "../client";
import type { ProviderID } from "../types";

interface ProvidersState {
  available: ProviderID[];
  default:   ProviderID | null;
  all:       ProviderID[];
  loading:   boolean;
  error:     string | null;
}

export function useProviders(): ProvidersState {
  const [state, setState] = useState<ProvidersState>({
    available: [],
    default:   null,
    all:       [],
    loading:   true,
    error:     null,
  });

  useEffect(() => {
    let active = true;
    listProviders()
      .then((data) => {
        if (active) setState({ ...data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (active) setState((s) => ({
          ...s,
          loading: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      });
    return () => { active = false; };
  }, []);

  return state;
}
