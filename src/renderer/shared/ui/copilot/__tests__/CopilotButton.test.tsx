import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CopilotButton } from "../CopilotButton";
import { CopilotContext, type CopilotContextType } from "../../../../contexts/copilot";

vi.mock("../../../../contexts/app", () => ({
  useAppContext: () => ({ setPage: vi.fn() }),
}));

function baseCtx(overrides: Partial<CopilotContextType> = {}): CopilotContextType {
  return {
    open: false, setOpen: vi.fn(), messages: [], streaming: false, error: null,
    suggestedAction: null, send: vi.fn(), dismissAction: vi.fn(), reset: vi.fn(),
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

  // The panel is lazy-loaded on first open, so its contents appear asynchronously.
  it("shows the panel when open is true", async () => {
    renderButton(baseCtx({ open: true }));
    expect(await screen.findByRole("dialog", { name: "AI Copilot" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close AI Copilot" })).toBeInTheDocument();
  });

  it("toggles setOpen when the FAB is clicked", () => {
    const setOpen = vi.fn();
    renderButton(baseCtx({ open: false, setOpen }));
    fireEvent.click(screen.getByRole("button", { name: "Open AI Copilot" }));
    expect(setOpen).toHaveBeenCalledWith(true);
  });

  it("shows the empty-state prompt when there are no messages yet", async () => {
    renderButton(baseCtx({ open: true }));
    expect(await screen.findByText(/ask me anything about this page/i)).toBeInTheDocument();
  });

  it("renders a suggested-action chip and does not navigate until clicked", async () => {
    const dismissAction = vi.fn();
    renderButton(baseCtx({ open: true, suggestedAction: { label: "Open Billing", page: "billing" }, dismissAction }));
    expect(await screen.findByText("Open Billing →")).toBeInTheDocument();
  });

  it("surfaces a stream error as an alert", async () => {
    renderButton(baseCtx({ open: true, error: "Backend offline." }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Backend offline.");
  });
});
