/**
 * OrgContext — current organization selection for the multi-tenant SaaS.
 *
 * Mirrors AuthContext's pattern: a module-level `window.__axon_org_id`
 * accessor lets the plain apiFetch()/authH() functions in shared/utils/api.ts
 * read the current org without importing React context machinery.
 */
import {
  createContext, useCallback, useContext, useEffect, useState,
} from "react";
import type { ReactNode } from "react";
import { apiFetch, parseJSON } from "../shared/utils/api";
import { useAuth } from "./AuthContext";

const CURRENT_ORG_KEY = "axon_current_org_id";

function setGlobalOrgId(id: string | null) {
  (window as unknown as Record<string, string | null>).__axon_org_id = id;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  kind: "personal" | "organization" | "enterprise";
  plan: string;
  created_at: string;
  my_role?: string;
}

interface OrgContextType {
  orgs: Org[];
  currentOrgId: string | null;
  currentOrg: Org | null;
  loading: boolean;
  setCurrentOrgId: (id: string | null) => void;
  refreshOrgs: () => Promise<void>;
  createOrg: (name: string, kind?: Org["kind"]) => Promise<Org>;
}

const OrgContext = createContext<OrgContextType | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useOrg(): OrgContextType {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error("useOrg must be used within OrgProvider");
  return ctx;
}

export function OrgProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [currentOrgId, setCurrentOrgIdState] = useState<string | null>(
    () => localStorage.getItem(CURRENT_ORG_KEY),
  );
  const [loading, setLoading] = useState(true);

  const setCurrentOrgId = useCallback((id: string | null) => {
    setCurrentOrgIdState(id);
    setGlobalOrgId(id);
    if (id) localStorage.setItem(CURRENT_ORG_KEY, id);
    else localStorage.removeItem(CURRENT_ORG_KEY);
  }, []);

  const refreshOrgs = useCallback(async () => {
    if (!user) { setOrgs([]); setLoading(false); return; }
    setLoading(true);
    try {
      const r = await apiFetch("/api/orgs");
      const d = await parseJSON<{ organizations: Org[] }>(r, "/api/orgs");
      setOrgs(d.organizations);
      // Auto-select: keep current if still valid, else first org, else clear.
      setCurrentOrgIdState(prev => {
        const stillValid = prev && d.organizations.some(o => o.id === prev);
        const next = stillValid ? prev : (d.organizations[0]?.id ?? null);
        setGlobalOrgId(next);
        if (next) localStorage.setItem(CURRENT_ORG_KEY, next);
        return next;
      });
    } catch {
      setOrgs([]);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    // Set the global accessor immediately from localStorage so the very
    // first request after a page refresh already carries the org header.
    setGlobalOrgId(currentOrgId);
    void Promise.resolve().then(refreshOrgs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const createOrg = useCallback(async (name: string, kind: Org["kind"] = "organization") => {
    const r = await apiFetch("/api/orgs", { method: "POST", body: JSON.stringify({ name, kind }) });
    const org = await parseJSON<Org>(r, "/api/orgs");
    setOrgs(prev => [...prev, org]);
    setCurrentOrgId(org.id);
    return org;
  }, [setCurrentOrgId]);

  const currentOrg = orgs.find(o => o.id === currentOrgId) ?? null;

  return (
    <OrgContext.Provider value={{ orgs, currentOrgId, currentOrg, loading, setCurrentOrgId, refreshOrgs, createOrg }}>
      {children}
    </OrgContext.Provider>
  );
}
