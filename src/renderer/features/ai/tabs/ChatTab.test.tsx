/**
 * FE-02 — chat stability: history restore, drafts, concurrent sends,
 * network loss and session restore after a page refresh. A refresh is
 * simulated by unmounting and mounting a fresh ChatTab; storage is kept,
 * exactly as the browser keeps it across a reload.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatTab } from "./ChatTab";
import i18n from "../../../i18n";
import type * as ApiModule from "../../../utils/api";

const CONVS = [{ id: "conv-1", title: "Pricing plan", updated_at: new Date().toISOString() }];
const HISTORY: Record<string, { id: string; role: string; content: string }[]> = {
  "conv-1": [
    { id: "m1", role: "user", content: "What should I charge?" },
    { id: "m2", role: "assistant", content: "Start from your costs." },
  ],
};

vi.mock("../../../utils/api", async original => {
  const real = await original<typeof ApiModule>();
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
  const route = (path: string) => {
    if (path.startsWith("/api/conversations?")) return CONVS;
    const m = path.match(/^\/api\/conversations\/([^/]+)\/messages$/);
    if (m) return HISTORY[m[1]] ?? [];
    if (path.startsWith("/api/tasks")) return { tasks: [] };
    if (path.startsWith("/api/agents/skills")) return { skills: [] };
    return {};
  };
  return {
    ...real,
    API: "",
    authH: () => ({ "Content-Type": "application/json" }),
    apiFetch: vi.fn(async (path: string) => json(route(path))),
    apiJSON: vi.fn(async (path: string) => route(path)),
  };
});

const fetchMock = vi.fn();
const enc = new TextEncoder();

/** A streaming Response whose events the test pushes one by one. */
function controllableStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; } });
  return {
    response: new Response(body, { status: 200 }),
    send: (ev: unknown) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(ev)}\n\n`)),
    close: () => ctrl.close(),
    fail: () => ctrl.error(new TypeError("network error")),
  };
}

/** Only the chat stream requests (other code may also call fetch). */
const streamCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/stream"));
/** Answer the chat stream with `stream`; any other fetch gets an empty JSON body. */
function serve(stream: () => Promise<Response>) {
  fetchMock.mockImplementation((url: string) => String(url).endsWith("/stream")
    ? stream() : Promise.resolve(new Response(JSON.stringify({ skills: [] }), { status: 200 })));
}

const input = () => screen.getByRole("textbox", { name: /message/i });
const mount = () => render(<ChatTab agents={[]} projects={[]} />);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  localStorage.clear();
  sessionStorage.clear();
  fetchMock.mockReset();
  serve(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
  Element.prototype.scrollIntoView = vi.fn();  // not implemented by jsdom
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps an unsent draft across a page refresh", async () => {
  mount();
  fireEvent.change(input(), { target: { value: "Half-written question" } });
  cleanup();
  mount();
  expect(input()).toHaveValue("Half-written question");
});

it("reopens the conversation that was open before a refresh, with its history", async () => {
  mount();
  fireEvent.click(await screen.findByText("Pricing plan"));
  expect(await screen.findByText("Start from your costs.")).toBeInTheDocument();
  cleanup();
  mount();
  expect(await screen.findByText("Start from your costs.")).toBeInTheDocument();
});

it("sends once when Enter is pressed twice before React re-renders", async () => {
  const s = controllableStream();
  serve(async () => s.response);
  mount();
  fireEvent.change(input(), { target: { value: "Hello" } });
  act(() => {
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.keyDown(input(), { key: "Enter" });
  });
  await waitFor(() => expect(streamCalls().length).toBeGreaterThan(0));
  expect(streamCalls()).toHaveLength(1);
  await act(async () => { s.send({ type: "done" }); s.close(); });
});

it("gives the text back when the network is down, so nothing typed is lost", async () => {
  serve(() => Promise.reject(new TypeError("Failed to fetch")));
  mount();
  fireEvent.change(input(), { target: { value: "Important question" } });
  fireEvent.keyDown(input(), { key: "Enter" });
  expect(await screen.findByText(/Backend offline/)).toBeInTheDocument();
  expect(input()).toHaveValue("Important question");
});

it("marks a reply that was cut off mid-stream instead of showing it as complete", async () => {
  const s = controllableStream();
  serve(async () => s.response);
  mount();
  fireEvent.change(input(), { target: { value: "Explain" } });
  fireEvent.keyDown(input(), { key: "Enter" });
  await waitFor(() => expect(streamCalls()).toHaveLength(1));
  await act(async () => { s.send({ type: "delta", text: "Partial answer" }); });
  await act(async () => { s.fail(); });
  expect(await screen.findByText(/connection was lost/i)).toBeInTheDocument();
  expect(screen.getByText(/Partial answer/)).toBeInTheDocument();
});

it("treats a stream that closes without 'done' as interrupted", async () => {
  const s = controllableStream();
  serve(async () => s.response);
  mount();
  fireEvent.change(input(), { target: { value: "Explain" } });
  fireEvent.keyDown(input(), { key: "Enter" });
  await waitFor(() => expect(streamCalls()).toHaveLength(1));
  await act(async () => { s.send({ type: "delta", text: "Half" }); s.close(); });
  expect(await screen.findByText(/connection was lost/i)).toBeInTheDocument();
});

it("stops the request when the chat is closed mid-reply", async () => {
  const s = controllableStream();
  serve(async () => s.response);
  mount();
  fireEvent.change(input(), { target: { value: "Long task" } });
  fireEvent.keyDown(input(), { key: "Enter" });
  await waitFor(() => expect(streamCalls()).toHaveLength(1));
  const signal = (streamCalls()[0][1] as RequestInit).signal as AbortSignal;
  cleanup();
  expect(signal.aborted).toBe(true);
});
