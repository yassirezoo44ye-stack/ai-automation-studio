/** Shared contract: Python len and Array.from both count Unicode code points. */
export const MAX_PROMPT_CHARACTERS = 32_000;
export function promptCharacters(text: string): number { return Array.from(text).length; }
export function validatePrompt(text: string, maximum = MAX_PROMPT_CHARACTERS): string | null {
  if (!text.trim()) return 'اكتب طلبًا أولًا. / Enter a request first.';
  if (promptCharacters(text) > maximum) {
    return `الحد ${maximum} حرف. النص محفوظ دون اختصار؛ قسّم الطلب إلى أجزاء مترابطة. / Limit: ${maximum} characters. Your text is unchanged; split it into linked parts.`;
  }
  return null;
}
export interface ChatStreamEvent { type: string; conv_id?: string; text?: string; message?: string }
/** Decode SSE records across arbitrary byte boundaries; EOF is not success. */
export async function* readChatEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatStreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const record = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const data = record.split(/\r?\n/).filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (!data) continue;
        const event = JSON.parse(data) as ChatStreamEvent;
        if (event.type === 'done' || event.type === 'error') completed = true;
        yield event;
        if (completed) return;
      }
      if (done) break;
    }
    throw new Error('انقطع الرد قبل تأكيد اكتماله وحفظه. / Reply interrupted before completion was confirmed.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** Show actionable HTTP failures without echoing validation input or server traces. */
export async function chatHttpFailure(response: Pick<Response, "status" | "json">): Promise<string> {
  const status = response.status;
  if (status === 422) {
    try {
      const body: unknown = await response.json();
      const detail = body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail : undefined;
      if (Array.isArray(detail)) {
        for (const item of detail) {
          if (!item || typeof item !== "object") continue;
          const issue = item as { loc?: unknown; type?: unknown; ctx?: { max_length?: unknown; limit_value?: unknown } };
          const loc = Array.isArray(issue.loc) ? issue.loc : [];
          const field = loc[loc.length - 1];
          const maximum = issue.ctx?.max_length ?? issue.ctx?.limit_value;
          if ((field === "prompt" || field === "display_text") &&
              (issue.type === "string_too_long" || issue.type === "value_error.any_str.max_length") &&
              typeof maximum === "number" && Number.isSafeInteger(maximum) && maximum > 0) {
            return `الخادم يقبل حتى ${maximum} حرف لهذا الطلب، ويشمل ذلك سياق الصفحة المضاف. لم يبدأ التنفيذ؛ نصك باقٍ في خانة الكتابة. قسّمه إلى أجزاء مترابطة. / Server limit: ${maximum} characters including page context. Execution has not started; your draft is unchanged. Split the request into linked parts.`;
          }
        }
      }
    } catch { /* A proxy may send HTML or an empty validation response. */ }
    return "تعذر قبول بيانات الطلب (422). لم يبدأ التنفيذ؛ راجع الحقول واحتفظ بنصك. / Request validation failed (422). Execution has not started; review the fields. Your draft is unchanged.";
  }
  if (status === 401) return "انتهت الجلسة أو لم يُقبل تسجيل الدخول. أعد الدخول؛ نصك لم يُمسح. / Sign in again. Your draft is unchanged.";
  if (status === 403) return "لا توجد صلاحية لهذا الإجراء. / You do not have permission for this action.";
  if (status === 402) return "يتطلب مزود الذكاء الاصطناعي مراجعة الفوترة أو الرصيد. / AI provider billing or credits need attention.";
  if (status === 429) return "طلبات كثيرة؛ انتظر قليلًا ثم أعد المحاولة. / Too many requests. Wait briefly before retrying.";
  return `تعذر إكمال الطلب (HTTP ${status}). نصك لم يُمسح. / Request failed (HTTP ${status}). Your draft is unchanged.`;
}
