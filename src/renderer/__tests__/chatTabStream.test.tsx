import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach, afterEach } from "vitest";
import { ChatTab } from "../features/ai/tabs/ChatTab";
import { AppContext } from "../contexts/app";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: { message?: string }) => opts?.message ? `${key}:${opts.message}` : key }),
}));
vi.mock("../contexts/toast", () => ({ useToast: () => vi.fn() }));
vi.mock("../contexts/AuthContext", () => ({ useAuth: () => ({ user: { name: "Yassir", email: "y@example.com" } }) }));

const CONV_ID = "11111111-1111-1111-1111-111111111111";
const TASK_ID = "22222222-2222-4222-8222-222222222222";
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

let messagesFetched: () => void;
let messagesFetchedPromise: Promise<void>;
let streamEvents: unknown[];

function sseStream(): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  const send = (ev: unknown) => enc.encode(`data: ${JSON.stringify(ev)}\n\n`);
  return new ReadableStream({
    async start(controller) {
      controller.enqueue(send({ type: "conv_id", conv_id: CONV_ID }));
      // The reply only starts arriving after the UI has (re)loaded the new
      // conversation's history — the race that used to wipe the reply.
      await Promise.race([messagesFetchedPromise, new Promise(r => setTimeout(r, 300))]);
      await new Promise(r => setTimeout(r, 20));
      for (const ev of streamEvents) controller.enqueue(send(ev));
      controller.close();
    },
  });
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  messagesFetchedPromise = new Promise(r => { messagesFetched = r; });
  streamEvents = [{ type: "delta", text: "Nice to meet you, Yassir!" }, { type: "done" }];
  setPage.mockReset();
  posted = [];
  try { localStorage.clear(); } catch { /* ignore */ }
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/run/stream")) {
      lastBody = JSON.parse(String(init?.body ?? "{}"));
      return new Response(sseStream(), { status: 200 });
    }
    if (url.includes(`/api/conversations/${CONV_ID}/messages`)) {
      messagesFetched();
      return json([{ id: "m1", role: "user", content: "hello" }]);
    }
    if (url.includes(`/api/tasks/${TASK_ID}`)) {
      if (init?.method === "PUT") { posted.push({ url, body: JSON.parse(String(init.body)) }); return json({ id: TASK_ID }); }
      return json({ id: TASK_ID, title: "Call supplier", status: "pending" });
    }
    if (url.includes("/api/tasks/") && !init?.method) return new Response(JSON.stringify({ detail: "Task not found" }), { status: 404 });
    if (url.includes("/api/tasks") && init?.method === "POST") {
      posted.push({ url, body: JSON.parse(String(init.body)) });
      return json({ id: "t1" });
    }
    if (url.includes("/api/conversations")) return json([]);
    if (url.includes("/api/agents/skills")) return json({ skills: [] });
    return json([]);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

const setPage = vi.fn();
let lastBody: Record<string, unknown> = {};
let posted: { url: string; body: Record<string, unknown> }[] = [];

async function send(text: string) {
  render(
    <AppContext.Provider value={{ setPage } as unknown as React.ContextType<typeof AppContext>}>
      <ChatTab agents={[]} projects={[]} />
    </AppContext.Provider>,
  );
  const box = screen.getByRole("textbox", { name: "chatTab.input.placeholder" });
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

it("keeps the streamed reply of a brand-new conversation on screen", async () => {
  await send("hello");
  expect(await screen.findByText("Nice to meet you, Yassir!", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(screen.getAllByText("hello")).toHaveLength(1);
});

it("shows a clear message instead of endless dots when the reply is empty", async () => {
  streamEvents = [{ type: "done" }];
  await send("hello");
  expect(await screen.findByText("chatTab.messages.emptyReply", {}, { timeout: 2000 })).toBeInTheDocument();
});

it("shows provider errors in place of the reply", async () => {
  streamEvents = [{ type: "error", message: "No AI provider is configured." }];
  await send("hello");
  await waitFor(() => expect(screen.getByText(/No AI provider is configured\./)).toBeInTheDocument(), { timeout: 2000 });
});

it("turns [[open:…]] markers into page buttons the user clicks", async () => {
  streamEvents = [{ type: "delta", text: "Your settings are here.\n\n[[open:settings]]" }, { type: "done" }];
  await send("where are my settings?");
  const btn = await screen.findByRole("button", { name: /chatTab.nav.open/ }, { timeout: 2000 });
  expect(screen.getByText("Your settings are here.")).toBeInTheDocument();
  expect(screen.queryByText(/\[\[open/)).not.toBeInTheDocument();
  expect(lastBody.navigation).toBe(true);
  expect(lastBody.workspace_data).toBe(true);
  expect(setPage).not.toHaveBeenCalled();
  fireEvent.click(btn);
  expect(setPage).toHaveBeenCalledWith("settings");
});

it("adds a page button when the user plainly asks to open a page", async () => {
  streamEvents = [{ type: "delta", text: "حسنًا." }, { type: "done" }];
  await send("افتح الفوترة");
  fireEvent.click(await screen.findByRole("button", { name: /chatTab.nav.open/ }, { timeout: 2000 }));
  expect(setPage).toHaveBeenCalledWith("billing");
});

it("runs a proposed action only after the user confirms it", async () => {
  streamEvents = [{ type: "delta", text: 'I can add it.\n[[action:create_task {"title": "Call supplier", "priority": "high"}]]' }, { type: "done" }];
  await send("add a task to call the supplier");
  const confirm = await screen.findByRole("button", { name: "chatTab.actions.confirm" }, { timeout: 2000 });
  expect(screen.getByText("Call supplier")).toBeInTheDocument();
  expect(posted).toHaveLength(0);
  fireEvent.click(confirm);
  await screen.findByText(/chatTab.actions.done/);
  expect(posted).toHaveLength(1);
  expect(posted[0].url).toContain("/api/tasks");
  expect(posted[0].body).toMatchObject({ title: "Call supplier", priority: "high", source: "assistant" });
});

it("dismissing a proposal sends nothing", async () => {
  streamEvents = [{ type: "delta", text: '[[action:create_task {"title": "X"}]]' }, { type: "done" }];
  await send("add task X");
  fireEvent.click(await screen.findByRole("button", { name: "chatTab.actions.dismiss" }, { timeout: 2000 }));
  expect(screen.queryByRole("button", { name: "chatTab.actions.confirm" })).not.toBeInTheDocument();
  expect(posted).toHaveLength(0);
});

it("shows the real task and its current status before a status change, then applies it on confirm", async () => {
  streamEvents = [{ type: "delta", text: `Marking it done.\n[[action:update_task_status {"id": "${TASK_ID}", "status": "done"}]]` }, { type: "done" }];
  await send("mark call supplier as done");
  const confirm = await screen.findByRole("button", { name: "chatTab.actions.confirm" }, { timeout: 2000 });
  expect(screen.getByText("Call supplier")).toBeInTheDocument();
  expect(screen.getByText("chatTab.actions.status.task.pending")).toBeInTheDocument();
  expect(screen.getByText("chatTab.actions.status.task.done")).toBeInTheDocument();
  expect(posted).toHaveLength(0);
  fireEvent.click(confirm);
  await screen.findByText(/chatTab.actions.done/);
  expect(posted).toEqual([{ url: expect.stringContaining(`/api/tasks/${TASK_ID}`), body: { status: "done" } }]);
});

it("an id the user cannot see offers nothing to confirm", async () => {
  streamEvents = [{ type: "delta", text: '[[action:update_task_status {"id": "33333333-3333-4333-8333-333333333333", "status": "done"}]]' }, { type: "done" }];
  await send("mark it done");
  expect(await screen.findByText("chatTab.actions.notFound", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "chatTab.actions.confirm" })).not.toBeInTheDocument();
  expect(posted).toHaveLength(0);
});
