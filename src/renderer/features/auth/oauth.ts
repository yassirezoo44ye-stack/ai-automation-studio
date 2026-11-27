import { API } from "../../shared/utils/api";

export type OAuthProvider = "google" | "github" | "microsoft";
const PROVIDERS: readonly OAuthProvider[] = ["google", "github", "microsoft"];

/**
 * The sign-in providers this server has configured, or null when that is
 * unknown (request failed, or an older backend that does not say). The
 * page shows every button when null, as before.
 */
export async function oauthProviders(): Promise<OAuthProvider[] | null> {
  try {
    const res = await fetch(`${API}/api/auth/oauth-config`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
    if (!res.ok) return null;
    const { providers } = await res.json() as { providers?: unknown };
    if (!Array.isArray(providers)) return null;
    return PROVIDERS.filter(p => providers.includes(p));
  } catch {
    return null;
  }
}

export async function oauthStartUrl(provider: OAuthProvider): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API}/api/auth/oauth-config`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
  } catch {
    throw new Error("تعذر الاتصال بخدمة تسجيل الدخول. تحقق من الاتصال وأعد المحاولة.");
  }
  if (!response.ok) throw new Error("تعذر بدء تسجيل الدخول. حاول مرة أخرى.");
  const config = await response.json() as { origin?: string; providers?: unknown };
  if (!config.origin) throw new Error("عنوان تسجيل الدخول غير مهيأ.");
  // Starting an unconfigured provider would land on a bare 503 JSON page.
  if (Array.isArray(config.providers) && !config.providers.includes(provider)) {
    throw new Error("طريقة تسجيل الدخول هذه غير متاحة حاليًا.");
  }
  const url = new URL(config.origin);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(local && url.protocol === "http:")) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("عنوان تسجيل الدخول غير صالح.");
  }
  return `${url.origin}/api/auth/${provider}`;
}
