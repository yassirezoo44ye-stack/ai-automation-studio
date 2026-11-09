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
