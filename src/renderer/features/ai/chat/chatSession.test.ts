import { beforeEach, describe, expect, it } from "vitest";
import {
  carryOverErrors, clearAllChatStorage, clearDraft, countChars, DEFAULT_LIMITS, describeSendFailure,
  getDraft, limitState, loadSession, parseLimits, parseSseBuffer, saveSession, setDraft,
} from "./chatSession";

beforeEach(() => localStorage.clear());

describe("session restore", () => {
  it("defaults to the demo project with no conversation", () => {
    expect(loadSession("u1")).toEqual({ projectId: "demo", convId: null });
    expect(loadSession(null)).toEqual({ projectId: "demo", convId: null });
  });

  it("round-trips per user and never leaks to another user", () => {
    saveSession("u1", { projectId: "p-1", convId: "c-1" });
    expect(loadSession("u1")).toEqual({ projectId: "p-1", convId: "c-1" });
    expect(loadSession("u2")).toEqual({ projectId: "demo", convId: null });
  });

  it("survives corrupted storage", () => {
    localStorage.setItem("flow.chat.session.v1:u1", "{not json");
    expect(loadSession("u1")).toEqual({ projectId: "demo", convId: null });
  });
});

describe("drafts", () => {
  it("are scoped by user, project and conversation", () => {
    setDraft("u1", "demo", null, "new chat draft");
    setDraft("u1", "demo", "c-1", "reply draft");
    expect(getDraft("u1", "demo", null)).toBe("new chat draft");
    expect(getDraft("u1", "demo", "c-1")).toBe("reply draft");
    expect(getDraft("u2", "demo", null)).toBe("");
    expect(getDraft("u1", "p-2", null)).toBe("");
  });

  it("keep newlines, code and Arabic exactly", () => {
    const text = "مرحبا\n\n```ts\nconst x = 1;\n```\n";
    setDraft("u1", "demo", null, text);
    expect(getDraft("u1", "demo", null)).toBe(text);
  });

  it("clearing one draft leaves the others", () => {
    setDraft("u1", "demo", null, "a");
    setDraft("u1", "demo", "c-1", "b");
    clearDraft("u1", "demo", null);
    expect(getDraft("u1", "demo", null)).toBe("");
    expect(getDraft("u1", "demo", "c-1")).toBe("b");
  });

  it("logout wipe removes all chat keys but nothing else", () => {
    setDraft("u1", "demo", null, "a");
    saveSession("u1", { projectId: "demo", convId: "c" });
    localStorage.setItem("theme", "dark");
    clearAllChatStorage();
    expect(getDraft("u1", "demo", null)).toBe("");
    expect(loadSession("u1").convId).toBeNull();
    expect(localStorage.getItem("theme")).toBe("dark");
  });
});

describe("limits", () => {
  it("counts code points like the server", () => {
    expect(countChars("abc")).toBe(3);
    expect(countChars("مرحبا")).toBe(5);
    expect(countChars("👍🏽")).toBe(2); // two code points, four UTF-16 units
    expect("👍🏽".length).toBe(4);
  });

  it("classifies ok / warn / over", () => {
    const l = { maxPromptChars: 100, warnAtChars: 85 };
    expect(limitState(84, l)).toBe("ok");
    expect(limitState(85, l)).toBe("warn");
    expect(limitState(100, l)).toBe("warn");
    expect(limitState(101, l)).toBe("over");
  });

  it("parses the server payload and falls back safely", () => {
    expect(parseLimits({ max_prompt_chars: 1000, warn_at_chars: 900 })).toEqual({ maxPromptChars: 1000, warnAtChars: 900 });
    expect(parseLimits(null)).toEqual(DEFAULT_LIMITS);
    expect(parseLimits({ max_prompt_chars: 1000, warn_at_chars: 5000 }).warnAtChars).toBe(850);
  });
});

describe("SSE parsing", () => {
  it("returns complete events and keeps the partial tail", () => {
    const { events, rest } = parseSseBuffer('data: {"type":"delta","text":"a"}\n\ndata: {"type":"de');
    expect(events).toEqual([{ type: "delta", text: "a" }]);
    expect(rest).toBe('data: {"type":"de');
  });

  it("skips malformed frames instead of throwing", () => {
    const { events } = parseSseBuffer('data: {oops\ndata: {"type":"done"}\n');
    expect(events).toEqual([{ type: "done" }]);
  });
});

describe("send failures", () => {
  it("413 explains the limit in the user's language and keeps the text", () => {
    const body = { detail: { code: "prompt_too_long", message: "too long", message_ar: "طويلة جدًا", limit: 10, length: 11 } };
    expect(describeSendFailure(413, body, "ar", "x")).toEqual({ rejectedBeforeSave: true, retryable: false, message: "طويلة جدًا" });
    expect(describeSendFailure(413, body, "en", "x").message).toBe("too long");
  });

  it("server errors are retryable", () => {
    expect(describeSendFailure(503, null, "ar", "fallback")).toEqual({ rejectedBeforeSave: false, retryable: true, message: "fallback" });
  });

  it("string details pass through", () => {
    expect(describeSendFailure(404, { detail: "Conversation not found" }, "en", "x").message).toBe("Conversation not found");
  });
});

type M = { role: string; requestId?: string | null; status?: string; error?: string | null };

describe("carryOverErrors", () => {
  it("keeps the reason the client saw for a failed reply when history reloads", () => {
    const local: M[] = [
      { role: "user", requestId: "r1", status: "saved" },
      { role: "assistant", requestId: "r1", status: "failed", error: "No AI provider is configured" },
    ];
    const loaded: M[] = [
      { role: "user", requestId: "r1", status: "saved" },
      { role: "assistant", requestId: "r1", status: "failed" },
    ];
    expect(carryOverErrors(loaded, local)[1].error).toBe("No AI provider is configured");
  });

  it("does not attach an old reason to a reply that has since completed", () => {
    const local: M[] = [{ role: "assistant", requestId: "r1", status: "failed", error: "boom" }];
    const loaded: M[] = [{ role: "assistant", requestId: "r1", status: "complete" }];
    expect(carryOverErrors(loaded, local)[0]).toEqual({ role: "assistant", requestId: "r1", status: "complete" });
  });
});
