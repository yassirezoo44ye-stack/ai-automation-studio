import { API } from "../../shared/utils/api";

export async function oauthStartUrl(provider: "google" | "github" | "microsoft"): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API}/api/auth/oauth-config`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
  } catch {
    throw new Error("تعذر الاتصال بخدمة تسجيل الدخول. تحقق من الاتصال وأعد المحاولة.");
  }
  if (!response.ok) throw new Error("تعذر بدء تسجيل الدخول. حاول مرة أخرى.");
  const config = await response.json() as { origin?: string };
  if (!config.origin) throw new Error("عنوان تسجيل الدخول غير مهيأ.");
  const url = new URL(config.origin);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(local && url.protocol === "http:")) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("عنوان تسجيل الدخول غير صالح.");
  }
  return `${url.origin}/api/auth/${provider}`;
}
