/**
 * ChatTab phase-A acceptance tests (UI side). The server side of the same
 * guarantees is covered by tests/test_chat_persistence_phase_a.py.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getDraft, saveSession } from "../chat/chatSession";
import type * as RealApi from "../../../shared/utils/api";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1", email: "yassir@test.local", name: "Yassir" } }),
}));

type Json = unknown;
const jsonRoutes = new Map<string, (path: string, init?: RequestInit) => Json>();
const apiJSON = vi.fn(async (path: string, init?: RequestInit) => {
  for (const [prefix, handler] of jsonRoutes) {
    if (path === prefix || path.startsWith(prefix + "?")) return handler(path, init);
  }
  throw new Error(`unmocked apiJSON ${path}`);
});
const apiFetch = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>();

vi.mock("../../../utils/api", async () => {
  const real = await vi.importActual<typeof RealApi>("../../../shared/utils/api");
  return {
    ...real,
    apiJSON: (path: string, init?: RequestInit) => apiJSON(path, init),
    apiFetch: (path: string, init?: RequestInit) => apiFetch(path, init),
  };
});

// jsdom has no scrollIntoView.
Element.prototype.scrollIntoView = vi.fn();

import { ChatTab } from "./ChatTab";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** A stream the test drives frame by frame. */
function controlledStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; } });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    push: (ev: object) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`)),
    close: () => ctrl.close(),
  };
}

function sentBodies() {
  return apiFetch.mock.calls
    .filter(([p]) => p === "/api/run/stream")
    .map(([, init]) => JSON.parse(String(init?.body)));
}

function renderTab() {
  return render(<ChatTab agents={[]} projects={[]} />);
}

const composer = () => screen.getByRole("textbox", { name: "Write your message" });
const sendBtn  = () => screen.getByRole("button", { name: /^Send/ });

beforeEach(() => {
  localStorage.clear();
  apiJSON.mockClear();
  apiFetch.mockReset();
  jsonRoutes.clear();
  jsonRoutes.set("/api/chat/limits", () => ({ max_prompt_chars: 32000, warn_at_chars: 27200 }));
  jsonRoutes.set("/api/conversations", () => []);
  vi.stubGlobal("confirm", () => true);
});
afterEach(() => vi.unstubAllGlobals());

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ChatTab — persistence and restore", () => {
  it("reopens the last conversation and its history after a reload", async () => {
    saveSession("u1", { projectId: "demo", convId: "c1" });
    jsonRoutes.set("/api/conversations", () => [{ id: "c1", title: "Weekly plan", updated_at: new Date().toISOString() }]);
    jsonRoutes.set("/api/conversations/c1", () => ({ id: "c1", title: "Weekly plan" }));
    jsonRoutes.set("/api/conversations/c1/messages", () => [
      { id: "m1", role: "user", content: "Plan my week", status: "complete", client_request_id: "r1" },
      { id: "m2", role: "assistant", content: "Here is your plan", status: "complete", client_request_id: "r1" },
    ]);
    renderTab();
    expect(await screen.findByText("Here is your plan")).toBeInTheDocument();
    expect(screen.getByText("Plan my week")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Weekly plan/ })).toHaveAttribute("aria-current", "page");
  });

  it("drops a restored conversation the server no longer has", async () => {
    saveSession("u1", { projectId: "demo", convId: "gone" });
    const { APIError } = await import("../../../shared/utils/api");
    jsonRoutes.set("/api/conversations/gone", () => {
      throw new APIError("not found", { url: "/x", status: 404, contentType: "application/json" });
    });
    jsonRoutes.set("/api/conversations/gone/messages", () => {
      throw new APIError("not found", { url: "/x", status: 404, contentType: "application/json" });
    });
    renderTab();
    await waitFor(() => expect(JSON.parse(localStorage.getItem("flow.chat.session.v1:u1")!).convId).toBeNull());
  });

  it("restores the unsent draft for the conversation", async () => {
    localStorage.setItem("flow.chat.draft.v1:u1:demo:new", "half-written\nmessage");
    renderTab();
    expect(composer()).toHaveValue("half-written\nmessage");
  });
});

describe("ChatTab — failed send, draft and idempotent retry", () => {
  it("keeps the draft when the request fails and retries with the same request id", async () => {
    renderTab();
    fireEvent.change(composer(), { target: { value: "Plan my week" } });
    apiFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await act(async () => { fireEvent.click(sendBtn()); });

    expect(await screen.findByText(/Failed to send/)).toBeInTheDocument();
    // Draft is still stored — nothing confirmed it was saved.
    expect(getDraft("u1", "demo", null)).toBe("Plan my week");

    const s = controlledStream();
    apiFetch.mockResolvedValueOnce(s.response);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
    await act(async () => {
      s.push({ type: "conv_id", conv_id: "c9", user_saved: true });
      s.push({ type: "delta", text: "Done." });
      s.push({ type: "done" });
      s.close();
    });

    expect(await screen.findByText("Done.")).toBeInTheDocument();
    const [first, second] = sentBodies();
    expect(second.client_request_id).toBe(first.client_request_id);
    expect(screen.getAllByText("Plan my week")).toHaveLength(1);
    expect(getDraft("u1", "demo", null)).toBe("");
  });

  it("returns the full text to the composer with the reason when the server rejects it", async () => {
    renderTab();
    const text = "long brief\n```js\ncode()\n```";
    fireEvent.change(composer(), { target: { value: text } });
    apiFetch.mockResolvedValueOnce(new Response(JSON.stringify({
      detail: { code: "prompt_too_long", message: "The message is 40,000 characters; the limit is 32,000.", message_ar: "…", limit: 32000, length: 40000 },
    }), { status: 413, headers: { "Content-Type": "application/json" } }));
    await act(async () => { fireEvent.click(sendBtn()); });

    expect(await screen.findByRole("alert")).toHaveTextContent("the limit is 32,000");
    expect(composer()).toHaveValue(text);
    expect(screen.queryByText("long brief", { exact: false, selector: ".msg-row *" })).toBeNull();
  });

  it("marks a cut-off reply as incomplete instead of pretending it finished", async () => {
    renderTab();
    fireEvent.change(composer(), { target: { value: "Write a report" } });
    const s = controlledStream();
    apiFetch.mockResolvedValueOnce(s.response);
    await act(async () => { fireEvent.click(sendBtn()); });
    await act(async () => {
      s.push({ type: "conv_id", conv_id: "c2", user_saved: true });
      s.push({ type: "delta", text: "First half" });
      s.close(); // connection drops: no done, no error
    });
    expect(await screen.findByText(/Reply incomplete/)).toBeInTheDocument();
    expect(screen.getByText("First half")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("ChatTab — limits", () => {
  it("shows the shared limit before sending and blocks oversized text without losing it", async () => {
    jsonRoutes.set("/api/chat/limits", () => ({ max_prompt_chars: 20, warn_at_chars: 15 }));
    renderTab();
    await waitFor(() => expect(screen.getByText(/0 \/ 20/)).toBeInTheDocument());

    const text = "مرحبا ".repeat(5); // 30 code points
    fireEvent.change(composer(), { target: { value: text } });
    expect(screen.getByText(/the limit is 20/)).toBeInTheDocument();
    expect(sendBtn()).toBeDisabled();
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(sentBodies()).toHaveLength(0);
    expect(composer()).toHaveValue(text);
  });
});

describe("ChatTab — streams never leak across conversations", () => {
  it("history load for a just-created conversation does not erase the streaming reply", async () => {
    renderTab();
    fireEvent.change(composer(), { target: { value: "Start" } });
    const s = controlledStream();
    apiFetch.mockResolvedValueOnce(s.response);
    // The DB only has the user message while the reply streams.
    jsonRoutes.set("/api/conversations/new1/messages", () => [
      { id: "m1", role: "user", content: "Start", status: "complete", client_request_id: "x" },
    ]);
    await act(async () => { fireEvent.click(sendBtn()); });
    await act(async () => {
      s.push({ type: "conv_id", conv_id: "new1", user_saved: true });
      s.push({ type: "delta", text: "streaming text" });
    });
    await waitFor(() => expect(apiJSON).toHaveBeenCalledWith("/api/conversations/new1/messages", undefined));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("streaming text")).toBeInTheDocument();
    await act(async () => { s.push({ type: "done" }); s.close(); });
    expect(screen.getByText("streaming text")).toBeInTheDocument();
  });

  it("switching conversations mid-stream keeps the reply out of the other conversation", async () => {
    saveSession("u1", { projectId: "demo", convId: "c1" });
    const now = new Date().toISOString();
    jsonRoutes.set("/api/conversations", () => [
      { id: "c1", title: "First", updated_at: now },
      { id: "c2", title: "Second", updated_at: now },
    ]);
    jsonRoutes.set("/api/conversations/c1", () => ({ id: "c1" }));
    jsonRoutes.set("/api/conversations/c1/messages", () => []);
    jsonRoutes.set("/api/conversations/c2/messages", () => [
      { id: "z1", role: "user", content: "Other topic", status: "complete", client_request_id: null },
    ]);
    renderTab();
    await screen.findByRole("button", { name: /^Second/ });

    fireEvent.change(composer(), { target: { value: "Question for first" } });
    const s = controlledStream();
    apiFetch.mockResolvedValueOnce(s.response);
    await act(async () => { fireEvent.click(sendBtn()); });
    await act(async () => {
      s.push({ type: "conv_id", conv_id: "c1", user_saved: true });
      s.push({ type: "delta", text: "partA " });
    });

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Second/ })); });
    expect(await screen.findByText("Other topic")).toBeInTheDocument();
    await act(async () => { s.push({ type: "delta", text: "partB" }); s.push({ type: "done" }); s.close(); });

    const main = document.querySelector(".chat-main") as HTMLElement;
    expect(within(main).queryByText(/partA|partB/)).toBeNull();
    expect(within(main).queryByText("Question for first")).toBeNull();
    // The composer is usable in the new conversation (stream detached).
    expect(screen.getByRole("button", { name: /^Send/ })).toBeInTheDocument();
  });
});

describe("ChatTab — conversation list actions", () => {
  it("rename, archive and delete are separate, labelled, keyboard-reachable buttons", async () => {
    const now = new Date().toISOString();
    let title = "Budget";
    jsonRoutes.set("/api/conversations", () => [{ id: "c1", title, updated_at: now, archived: false }]);
    const patches: unknown[] = [];
    jsonRoutes.set("/api/conversations/c1", (_p, init) => {
      if (init?.method === "PATCH") { const b = JSON.parse(String(init.body)); patches.push(b); if (b.title) title = b.title; }
      return { id: "c1", title };
    });
    renderTab();

    const renameBtn = await screen.findByRole("button", { name: "Rename “Budget”" });
    expect(screen.getByRole("button", { name: "Archive “Budget”" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete “Budget”" })).toBeInTheDocument();

    fireEvent.click(renameBtn);
    const field = screen.getByRole("textbox", { name: "New conversation name" });
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "Q3 budget" } });
    await act(async () => { fireEvent.keyDown(field, { key: "Enter" }); });
    await waitFor(() => expect(patches).toEqual([{ title: "Q3 budget" }]));

    await act(async () => { fireEvent.click(await screen.findByRole("button", { name: "Archive “Q3 budget”" })); });
    await waitFor(() => expect(patches).toContainEqual({ archived: true }));
  });

  it("search queries the server (titles and content), not just loaded titles", async () => {
    renderTab();
    fireEvent.change(screen.getByRole("searchbox", { name: /Search conversation titles and content/ }), { target: { value: "invoice" } });
    await waitFor(() => expect(apiJSON.mock.calls.some(([p]) => String(p).includes("q=invoice"))).toBe(true), { timeout: 2000 });
  });
});

describe("ChatTab — message rendering", () => {
  it("keeps line breaks and code in the user's message", async () => {
    saveSession("u1", { projectId: "demo", convId: "c1" });
    const content = "سطر أول\n\n```py\nprint(1)\n```";
    jsonRoutes.set("/api/conversations/c1", () => ({ id: "c1" }));
    jsonRoutes.set("/api/conversations/c1/messages", () => [
      { id: "m1", role: "user", content, status: "complete", client_request_id: "r" },
      { id: "m2", role: "assistant", content: "ok", status: "complete", client_request_id: "r" },
    ]);
    renderTab();
    const bubble = await screen.findByText((_, el) => el?.textContent === content && el.getAttribute("dir") === "auto");
    expect(bubble).toHaveStyle({ whiteSpace: "pre-wrap" });
  });

  it("labels the message copy button for what it does", async () => {
    saveSession("u1", { projectId: "demo", convId: "c1" });
    jsonRoutes.set("/api/conversations/c1", () => ({ id: "c1" }));
    jsonRoutes.set("/api/conversations/c1/messages", () => [
      { id: "m2", role: "assistant", content: "hello", status: "complete", client_request_id: null },
    ]);
    renderTab();
    expect(await screen.findByRole("button", { name: "Copy message" })).toBeInTheDocument();
  });
});

describe("ChatTab — small screens", () => {
  it("the conversations drawer opens from the toolbar and closes with Escape, returning focus", async () => {
    renderTab();
    const toggle = screen.getByRole("button", { name: "Show conversations" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close conversations list" })).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".chat-layout")).toHaveClass("chat-layout--rail-open");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".chat-layout")).not.toHaveClass("chat-layout--rail-open");
    expect(screen.getByRole("button", { name: "Show conversations" })).toHaveFocus();
  });

  it("marks the page so the floating copilot button can stay off the Send button", () => {
    const { unmount } = renderTab();
    expect(document.body).toHaveClass("flow-chat-open");
    unmount();
    expect(document.body).not.toHaveClass("flow-chat-open");
  });
});
