import { apiFetch, parseJSON, API } from "../../../shared/utils/api";

export async function fetchSystemInfo(): Promise<Record<string, unknown>> {
  const r = await apiFetch("/api/runtime/health");
  return parseJSON<Record<string, unknown>>(r, "/api/runtime/health");
}

export async function checkHealth(): Promise<boolean> {
  try {
    const r = await apiFetch("/health");
    return r.ok;
  } catch {
    return false;
  }
}

export function getStoredEmail(): string {
  return localStorage.getItem("sub_email") ?? "";
}

export function getStoredToken(): string {
  return localStorage.getItem("sub_token") ?? "";
}

export function clearAuth(): void {
  localStorage.removeItem("sub_email");
  localStorage.removeItem("sub_token");
}

export { API };
