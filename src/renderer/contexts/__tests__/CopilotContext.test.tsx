import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CopilotProvider } from "../CopilotContext";
import { useCopilot } from "../copilot";

vi.mock("../app", () => ({
  useAppContext: () => ({ page: "billing" }),
}));
vi.mock("../OrgContext", () => ({
  useOrg: () => ({ currentOrg: { id: "org1", name: "Acme Inc" } }),
}));

function sseFrame(obj: unknown) {
  return `data: ${JSON.stringify(obj)}\n\n`;
}

function mockStreamResponse(frames: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (i < frames.length) {
            const chunk = encoder.encode(frames[i]);
            i++;
            return { done: false, value: chunk };
          }
          return { done: true, value: undefined };
        },
      }),
    },
  };
}

function mockChatResponse(frames: string[]) {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((_url: string, init?: RequestInit) => Promise.resolve(
    init?.method === "POST" ? mockStreamResponse(frames) : { ok: true, json: async () => [] },
  ));
}

function Consumer() {
  const { messages, streaming, error, suggestedAction, send } = useCopilot();
  return (
    <div>
      <div data-testid="streaming">{String(streaming)}</div>
      <div data-testid="error">{error ?? ""}</div>
      <div data-testid="action">{suggestedAction?.page ?? ""}</div>
      {messages.map(m => <div key={m.id} data-testid={`msg-${m.role}`}>{m.content}</div>)}
      <button onClick={() => send("Explain this page")}>ask</button>
      <button onClick={() => send("open billing")}>ask-action</button>
      <button onClick={() => send("")}>ask-empty</button>
      <button onClick={() => send("  العربية\r\n  const x = 1;\n  ")}>ask-exact</button>
      <button onClick={() => send("x".repeat(8000))}>ask-long</button>
      <button onClick={() => send("x".repeat(32001))}>ask-over-limit</button>
    </div>
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
});

describe("CopilotProvider", () => {
  it("streams an assistant reply and injects page/org context into the sent prompt", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    mockChatResponse([
      sseFrame({ type: "conv_id", conv_id: "c1" }),
      sseFrame({ type: "delta", text: "Billing " }),
      sseFrame({ type: "delta", text: "shows your plan." }),
      sseFrame({ type: "done" }),
    ]);

    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask"));

    await waitFor(() => expect(screen.getByTestId("msg-assistant")).toHaveTextContent("Billing shows your plan."));
    expect(screen.getByTestId("msg-user")).toHaveTextContent("Explain this page");
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");

    const [, init] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST")!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.prompt).toContain("Billing");
    expect(body.prompt).toContain("Acme Inc");
    expect(body.prompt).toContain("Explain this page");
  });

  it("sends display_text as the raw user text and prompt with context annotation", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    mockChatResponse([
      sseFrame({ type: "conv_id", conv_id: "c2" }),
      sseFrame({ type: "done" }),
    ]);

    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask"));

    await waitFor(() => expect(screen.getByTestId("streaming")).toHaveTextContent("false"));

    const [, init] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST")!;
    const body = JSON.parse((init as RequestInit).body as string);
    // display_text must be the raw user text — no [Context: ...] prefix
    expect(body.display_text).toBe("Explain this page");
    expect(body.display_text).not.toContain("[Context:");
    // prompt must include the context annotation for the model
    expect(body.prompt).toContain("[Context:");
    expect(body.prompt).toContain("Explain this page");
    // UI user bubble shows the clean text, not the annotated prompt
    expect(screen.getByTestId("msg-user")).toHaveTextContent("Explain this page");
    expect(screen.getByTestId("msg-user")).not.toHaveTextContent("[Context:");
  });

  it("routes copilot messages to the dedicated copilot project, not the demo project", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    mockChatResponse([
      sseFrame({ type: "conv_id", conv_id: "c3" }),
      sseFrame({ type: "done" }),
    ]);

    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask"));

    await waitFor(() => expect(screen.getByTestId("streaming")).toHaveTextContent("false"));

    const [, init] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST")!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.project_id).toBe("copilot");
  });

  it("surfaces a stream error instead of leaving the UI silently stuck", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    mockChatResponse([
      sseFrame({ type: "error", message: "Server is at capacity — please retry shortly." }),
    ]);

    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask"));

    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent("capacity"));
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");
  });

  it("suggests a safe navigation action for an explicit open command, without auto-navigating", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    mockChatResponse([
      sseFrame({ type: "conv_id", conv_id: "c1" }),
      sseFrame({ type: "delta", text: "Sure, heading there." }),
      sseFrame({ type: "done" }),
    ]);

    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask-action"));

    await waitFor(() => expect(screen.getByTestId("action")).toHaveTextContent("billing"));
  });

  it("ignores empty input while loading server history", () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask-empty"));
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST")).toHaveLength(0);
  });
});

describe("Copilot prompt contract", () => {
  it("preserves exact Unicode, whitespace and code in display_text", async () => {
    mockChatResponse([sseFrame({type:"conv_id",conv_id:"exact"}),sseFrame({type:"done"})]);
    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask-exact"));
    await waitFor(() => expect(screen.getByTestId("streaming")).toHaveTextContent("false"));
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST")!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.display_text).toBe("  العربية\r\n  const x = 1;\n  ");
    expect(body.prompt.endsWith(body.display_text)).toBe(true);
    expect(body.prompt).toContain("inside Flow.");
  });

  it("accepts a prompt beyond the former 4000-character cap", async () => {
    mockChatResponse([sseFrame({type:"conv_id",conv_id:"long"}),sseFrame({type:"done"})]);
    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask-long"));
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST")).toHaveLength(1));
    const [, init] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST")!;
    expect(JSON.parse((init as RequestInit).body as string).display_text).toHaveLength(8000);
  });

  it("rejects oversized annotated requests before POST or optimistic messages", () => {
    render(<CopilotProvider><Consumer /></CopilotProvider>);
    fireEvent.click(screen.getByText("ask-over-limit"));
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST")).toHaveLength(0);
    expect(screen.getByTestId("error")).toHaveTextContent("32000");
    expect(screen.queryByTestId("msg-user")).not.toBeInTheDocument();
  });
});
