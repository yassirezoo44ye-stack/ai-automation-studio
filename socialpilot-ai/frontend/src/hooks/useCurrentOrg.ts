import { useAuth } from "../context/AuthContext";

/** Phase 1/2 has no org-switcher UI yet — every authenticated user's first
 * membership (the org they got as owner on registration, in the common
 * case) is treated as "the" active organization. Revisit once multi-org
 * switching is a real feature. */
export function useCurrentOrg() {
  const { organizations } = useAuth();
  return organizations[0] ?? null;
}
