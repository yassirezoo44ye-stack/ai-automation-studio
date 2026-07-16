import { useCallback, useEffect, useState } from "react";
import { getUsageByProvider, getUsageTotals } from "../client";
import type { ProviderUsage, UsageTotals } from "../types";

interface UseUsageReturn {
  totals:       UsageTotals | null;
  byProvider:   ProviderUsage[];
  loading:      boolean;
  error:        string | null;
  refresh:      () => void;
}

export function useUsage(since?: string): UseUsageReturn {
  const [totals, setTotals]         = useState<UsageTotals | null>(null);
  const [byProvider, setByProvider] = useState<ProviderUsage[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [tick, setTick]             = useState(0);

  useEffect(() => {
    let active = true;
     
    setLoading(true);
    Promise.all([getUsageTotals(since), getUsageByProvider(since)])
      .then(([t, bp]) => {
        if (!active) return;
        setTotals(t);
        setByProvider(bp);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [since, tick]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  return { totals, byProvider, loading, error, refresh };
}
