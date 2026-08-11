import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import * as api from "../api/client";
import { subscribeTokenState, getTokenState } from "../api/tokenStore";
import type { OrganizationMembership, UserPublic } from "../api/types";

interface AuthContextValue {
  user: UserPublic | null;
  organizations: OrganizationMembership[];
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: {
    email: string;
    password: string;
    full_name: string;
    organization_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [, forceRender] = useState(0);

  useEffect(() => subscribeTokenState(() => forceRender((n) => n + 1)), []);

  // On first load the access token is empty (it only ever lives in memory) —
  // try to silently mint a fresh one from the httpOnly refresh cookie, if any.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const refreshed = await api.tryRefresh();
      if (refreshed && !cancelled) {
        try {
          const me = await api.fetchMe();
          if (!cancelled) {
            setUser(me.user);
            setOrganizations(me.organizations);
          }
        } catch {
          // refresh succeeded but /me failed unexpectedly — leave logged out
        }
      }
      if (!cancelled) setIsBootstrapping(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    setUser(result.user);
    setOrganizations(result.organizations);
  }, []);

  const register = useCallback(
    async (input: { email: string; password: string; full_name: string; organization_name?: string }) => {
      const result = await api.register(input);
      setUser(result.user);
      setOrganizations(result.organizations);
    },
    [],
  );

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setOrganizations([]);
  }, []);

  const { accessToken } = getTokenState();

  return (
    <AuthContext.Provider
      value={{
        user,
        organizations,
        isAuthenticated: Boolean(accessToken && user),
        isBootstrapping,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
