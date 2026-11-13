import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatTab } from "./ChatTab";
import { apiFetch, apiJSON } from "../../../utils/api";
import type * as ApiModule from "../../../utils/api";
import i18n from "../../../i18n";
vi.mock("../../../contexts/toast", () => ({ useToast: () => vi.fn() }));
vi.mock("../../../utils/api", async original => ({ ...await original<typeof ApiModule>(), apiJSON: vi.fn(), apiFetch: vi.fn() }));
beforeEach(async () => {
  vi.resetAllMocks(); await i18n.changeLanguage("en");
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

it("keeps the streamed reply visible without reloading old server history", async () => {
  vi.mocked(apiJSON).mockImplementation(async path => path.includes("/messages")
    ? [{ id: "old", role: "assistant", content: "Previous answer" }]
    : [{ id: "conv-1", title: "Saved chat", updated_at: new Date().toISOString() }] as never);
  const encoder = new TextEncoder();
  vi.mocked(apiFetch).mockResolvedValue(new Response(new ReadableStream({ start(controller) {
    for (const event of [{ type: "conv_id", conv_id: "conv-1" }, { type: "delta", text: "Fresh complete answer" }, { type: "done" }]) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
    controller.close();
  } })));
  render(<ChatTab agents={[]} projects={[]} />);
  await screen.findByText("Previous answer");
  const input = screen.getByRole("textbox", { name: "Message… (Enter to send, Shift+Enter for new line)" });
  fireEvent.change(input, { target: { value: "Continue the plan" } });
  fireEvent.click(screen.getByRole("button", { name: "Send ↑" }));
  await screen.findByText("Fresh complete answer");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send ↑" })).toBeInTheDocument());
  expect(vi.mocked(apiJSON).mock.calls.filter(([path]) => path.includes("/messages"))).toHaveLength(1);
  expect(screen.getByText("Fresh complete answer")).toBeInTheDocument();
});
