import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CopilotButton } from "../CopilotButton";
import { CopilotContext, type CopilotContextType } from "../../../../contexts/copilot";

vi.mock("../../../../contexts/app", () => ({
  useAppContext: () => ({ setPage: vi.fn() }),
}));

function baseCtx(overrides: Partial<CopilotContextType> = {}): CopilotContextType {
  return {
    open: false, setOpen: vi.fn(), messages: [], conversations: [], conversationId: null,
    loadingHistory: false, openConversation: vi.fn().mockResolvedValue(undefined),
    streaming: false, error: null,
    suggestedAction: null, send: vi.fn().mockResolvedValue(false), dismissAction: vi.fn(), reset: vi.fn(),
    ...overrides,
  };
}

function renderButton(ctx: CopilotContextType) {
  return render(
    <CopilotContext.Provider value={ctx}>
      <CopilotButton />
    </CopilotContext.Provider>,
  );
}

describe("CopilotButton", () => {
  it("renders closed by default with no panel", () => {
    renderButton(baseCtx());
    expect(screen.getByRole("button", { name: "Open AI Copilot" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "AI Copilot" })).not.toBeInTheDocument();
  });

  it("shows the panel when open is true", () => {
    renderButton(baseCtx({ open: true }));
    expect(screen.getByRole("dialog", { name: "AI Copilot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close AI Copilot" })).toBeInTheDocument();
  });

  it("toggles setOpen when the FAB is clicked", () => {
    const setOpen = vi.fn();
    renderButton(baseCtx({ open: false, setOpen }));
    fireEvent.click(screen.getByRole("button", { name: "Open AI Copilot" }));
    expect(setOpen).toHaveBeenCalledWith(true);
  });

  it("shows the empty-state prompt when there are no messages yet", () => {
    renderButton(baseCtx({ open: true }));
    expect(screen.getByText(/ask me anything about this page/i)).toBeInTheDocument();
  });

  it("renders a suggested-action chip and does not navigate until clicked", () => {
    const dismissAction = vi.fn();
    renderButton(baseCtx({ open: true, suggestedAction: { label: "Open Billing", page: "billing" }, dismissAction }));
    expect(screen.getByText("Open Billing →")).toBeInTheDocument();
  });

  it("surfaces a stream error as an alert", () => {
    renderButton(baseCtx({ open: true, error: "Backend offline." }));
    expect(screen.getByRole("alert")).toHaveTextContent("Backend offline.");
  });
});

describe("Copilot composer recovery", () => {
  it("keeps the exact long draft when sending is rejected", async () => {
    const send = vi.fn().mockResolvedValue(false);
    renderButton(baseCtx({ open: true, send, error: "Server limit: 4000 characters" }));
    const draft = "  العربية\r\n  CREATE TABLE example (id INT);\n" + "x".repeat(4100);
    const input = screen.getByRole("textbox", { name: "Ask the copilot" });
    fireEvent.change(input, { target: { value: draft } });
    fireEvent.click(screen.getByRole("button", { name: "Send", exact: true }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(draft));
    expect(input).toHaveValue(draft);
    expect(screen.getByRole("alert")).toHaveTextContent("4000");
  });

  it("clears the submitted draft only after successful completion", async () => {
    const send = vi.fn().mockResolvedValue(true);
    renderButton(baseCtx({ open: true, send }));
    const input = screen.getByRole("textbox", { name: "Ask the copilot" });
    fireEvent.change(input, { target: { value: "build a page" } });
    fireEvent.click(screen.getByRole("button", { name: "Send", exact: true }));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(send).toHaveBeenCalledWith("build a page");
  });

  it("does not erase a newer draft when an older send resolves", async () => {
    let finish!: (value: boolean) => void;
    const send = vi.fn().mockImplementation(() => new Promise<boolean>(resolve => { finish = resolve; }));
    renderButton(baseCtx({ open: true, send }));
    const input = screen.getByRole("textbox", { name: "Ask the copilot" });
    fireEvent.change(input, { target: { value: "first request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send", exact: true }));
    fireEvent.change(input, { target: { value: "next request" } });
    await act(async () => { finish(true); });
    expect(input).toHaveValue("next request");
    expect(send).toHaveBeenCalledTimes(1);
  });
});
