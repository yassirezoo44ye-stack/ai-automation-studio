/**
 * ChatTab — a streamed reply in a brand-new conversation stays visible.
 *
 * Regression: the stream's conv_id event switches activeConv, which loads the
 * conversation's messages. The server has only the user message at that point
 * (the reply is saved when the stream ends), and that load used to replace the
 * on-screen messages — wiping the streaming reply until the conversation was
 * reopened.
 */
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import i18n from "../../../../i18n";
import { ToastCtx } from "../../../../contexts/toast";

const apiJSON = vi.fn();
vi.mock("../../../../utils/api", () => ({
  apiJSON: (...args: unknown[]) => apiJSON(...args),
  apiFetch: vi.fn(),
  authH: () => ({ "Content-Type": "application/json" }),
  API: "",
  APIError: class extends Error {},
}));

import { ChatTab } from "../ChatTab";

function sse(...events: unknown[]) {
  const body = events.map(e => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

let resolveLoad: (v: unknown) => void = () => {};

beforeEach(async () => {
  await i18n.changeLanguage("en");
  sessionStorage.clear();
  apiJSON.mockReset();
  apiJSON.mockImplementation((path: string) => {
    if (path.startsWith("/api/conversations?")) return Promise.resolve([]);
    if (path.endsWith("/messages")) {
      // The server copy has only the user message; resolve it after the
      // reply has streamed in, as in production.
      return new Promise(resolve => { resolveLoad = resolve; });
    }
    return Promise.resolve({});
  });
  vi.stubGlobal("fetch", vi.fn(async () => sse(
    { type: "conv_id", conv_id: "c-1" },
    { type: "delta", text: "Here is the weekly plan." },
    { type: "done" },
  )));
});

afterEach(() => vi.unstubAllGlobals());

describe("ChatTab — streaming into a new conversation", () => {
  it("keeps the streamed reply after the conversation's messages load", async () => {
    render(<ToastCtx.Provider value={vi.fn()}><ChatTab agents={[]} projects={[]} /></ToastCtx.Provider>);
    fireEvent.change(screen.getByLabelText(/^Message…/), { target: { value: "Plan the week" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("Here is the weekly plan.");
    await waitFor(() => expect(apiJSON).toHaveBeenCalledWith("/api/conversations/c-1/messages"));

    await act(async () => {
      resolveLoad([{ id: "u-1", role: "user", content: "Plan the week" }]);
      await Promise.resolve();
    });

    expect(screen.getByText("Here is the weekly plan.")).toBeInTheDocument();
    expect(screen.getByText("Plan the week")).toBeInTheDocument();
  });
});
