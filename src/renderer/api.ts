export const API = import.meta.env.VITE_API_URL ?? "";

function getToken(): string {
  return localStorage.getItem("sub_token") ?? "";
}

export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "Content-Type": "application/json", "X-Sub-Token": getToken(), ...extra };
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers as Record<string, string> ?? {}) },
  });
}
