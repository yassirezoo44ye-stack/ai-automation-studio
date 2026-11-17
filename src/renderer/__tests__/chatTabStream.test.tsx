import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach, afterEach } from "vitest";
import { ChatTab } from "../features/ai/tabs/ChatTab";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: { message?: string }) => opts?.message ? `${key}:${opts.message}` : key }),
}));
vi.mock("../contexts/toast", () => ({ useToast: () => vi.fn() }));

const CONV_ID = "11111111-1111-1111-1111-111111111111";
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
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/run/stream")) return new Response(sseStream(), { status: 200 });
    if (url.includes(`/api/conversations/${CONV_ID}/messages`)) {
      messagesFetched();
      return json([{ id: "m1", role: "user", content: "hello" }]);
    }
    if (url.includes("/api/conversations")) return json([]);
    if (url.includes("/api/agents/skills")) return json({ skills: [] });
    return json([]);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

async function send(text: string) {
  render(<ChatTab agents={[]} projects={[]} />);
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
