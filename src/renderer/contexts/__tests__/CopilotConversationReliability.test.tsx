import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CopilotProvider } from "../CopilotContext";
import { useCopilot } from "../copilot";

vi.mock("../app", () => ({ useAppContext: () => ({ page: "billing" }) }));
vi.mock("../OrgContext", () => ({ useOrg: () => ({ currentOrg: null }) }));

function stream(frames: unknown[]) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    body: { getReader: () => ({ read: async () => index < frames.length
      ? { done: false, value: encoder.encode(`data: ${JSON.stringify(frames[index++])}\n\n`) }
      : { done: true, value: undefined } }) },
  };
}

function Harness() {
  const { messages, conversations, send, openConversation } = useCopilot();
  return <>
    <button onClick={() => void send("hello")}>send</button>
    <button onClick={() => void openConversation("owned-conversation")}>open saved</button>
    <div data-testid="messages">{messages.map(m => `${m.role}:${m.content}`).join("|")}</div>
    <div data-testid="history">{conversations.map(c => c.title).join("|")}</div>
  </>;
}

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

describe("Copilot conversation reliability", () => {
  it("restores the latest server conversation and its messages on provider mount", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [{ id: "saved-1", title: "Saved", updated_at: "now" }] });
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [{ id: "u1", role: "user", content: "persisted prompt" }] });
    render(<CopilotProvider><Harness /></CopilotProvider>);

    await waitFor(() => expect(screen.getByTestId("messages")).toHaveTextContent("user:persisted prompt"));
    expect(fetchMock.mock.calls[0][0]).toContain("/api/conversations?project_id=copilot");
    expect(fetchMock.mock.calls[1][0]).toContain("/api/conversations/saved-1/messages");
  });

  it("does not restore messages when the server rejects ownership of the conversation", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [{ id: "foreign", title: "Foreign", updated_at: "now" }] });
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
    render(<CopilotProvider><Harness /></CopilotProvider>);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("messages")).toBeEmptyDOMElement();
  });

  it("keeps the previous history from replacing a newly streamed answer", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    let releaseHistory!: (value: unknown) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { releaseHistory = resolve; }));
    fetchMock.mockResolvedValueOnce(stream([
      { type: "conv_id", conv_id: "new-conv" },
      { type: "delta", text: "fresh answer" },
      { type: "done" },
    ]));
    render(<CopilotProvider><Harness /></CopilotProvider>);
    fireEvent.click(screen.getByText("send"));
    await waitFor(() => expect(screen.getByTestId("messages")).toHaveTextContent("assistant:fresh answer"));
    await act(async () => releaseHistory({ ok: true, json: async () => [{ id: "old", title: "Old", updated_at: "earlier" }] }));
    expect(screen.getByTestId("messages")).toHaveTextContent("assistant:fresh answer");
  });

  it("does not mix a switched conversation with the previous stream", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [] });
    let resolveStream!: (value: unknown) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { resolveStream = resolve; }));
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [{ id: "other-user", role: "user", content: "other chat" }] });
    render(<CopilotProvider><Harness /></CopilotProvider>);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("send"));
    fireEvent.click(screen.getByText("open saved"));
    await waitFor(() => expect(screen.getByTestId("messages")).toHaveTextContent("user:other chat"));
    await act(async () => resolveStream(stream([{ type: "delta", text: "leak" }, { type: "done" }])));
    expect(screen.getByTestId("messages")).not.toHaveTextContent("leak");
  });

  it("allows only one simultaneous send and leaves failed requests retryable", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [] });
    let resolveRequest!: (value: unknown) => void;
    fetchMock.mockReturnValueOnce(new Promise(resolve => { resolveRequest = resolve; }));
    render(<CopilotProvider><Harness /></CopilotProvider>);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await act(async () => {
      fireEvent.click(screen.getByText("send"));
      fireEvent.click(screen.getByText("send"));
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => resolveRequest({ ok: false, status: 503 }));
    await waitFor(() => expect(screen.getByTestId("messages")).toHaveTextContent("assistant:Request failed (503)"));
  });
});
