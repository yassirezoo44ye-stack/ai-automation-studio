import { apiFetch } from "../../utils/api";

/** Bound connection waits and preserve cancellation when leaving the page. */
export async function studyFetch(path: string, options?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const parent = options?.signal;
  const cancel = () => controller.abort();
  if (parent?.aborted) cancel();
  parent?.addEventListener("abort", cancel, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 30000);
  try {
    return await apiFetch(path, { ...options, signal: controller.signal });
  } catch (error) {
    if (timedOut) throw new Error("استغرق الاتصال وقتًا طويلًا. تحقق من الشبكة ثم أعد المحاولة.");
    throw error;
  } finally {
    window.clearTimeout(timer);
    parent?.removeEventListener("abort", cancel);
  }
}
