/**
 * RuntimePanel — state-machine rendering tests.
 *
 * Covers all 8 RuntimeState values and key interactive behaviors:
 *   idle (no build) → livePreview placeholder
 *   idle (buildDone) → readyToRun card + Run button
 *   ready_to_run → same readyToRun card
 *   starting → spinner + startup messages
 *   running → iframe + Restart / Stop controls
 *   stopping → spinner indicator
 *   stopped → runtimeStopped card + Run Again
 *   failed → error card + Retry + Explain with AI + Copy Error
 *
 * react-i18next is mocked so t(key) === key, making assertions key-based.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RuntimePanel } from "../components/RuntimePanel";
import type { RuntimeError } from "../components/RuntimePanel";

HTMLElement.prototype.scrollIntoView = vi.fn();
HTMLElement.prototype.scrollTo = vi.fn() as typeof HTMLElement.prototype.scrollTo;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const noop = vi.fn();

function make(overrides: Partial<Parameters<typeof RuntimePanel>[0]> = {}) {
  return {
    runtimeState: "idle" as const,
    previewUrl: null,
    previewType: null,
    runtimeError: null,
    buildDone: false,
    projectName: "My App",
    startupMessages: [],
    onRun: noop,
    onStop: noop,
    onRestart: noop,
    onExplainError: noop,
    ...overrides,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

/* ── idle: no build ───────────────────────────────────────────────────────── */

describe("idle — no build", () => {
  it("shows livePreview key", () => {
    render(<RuntimePanel {...make()} />);
    expect(screen.getByText("runtimePanel.livePreview")).toBeInTheDocument();
  });

  it("shows buildFirst hint", () => {
    render(<RuntimePanel {...make()} />);
    expect(screen.getByText("runtimePanel.buildFirst")).toBeInTheDocument();
  });

  it("does not show Run button", () => {
    render(<RuntimePanel {...make()} />);
    expect(screen.queryByText("runtimePanel.runProject")).not.toBeInTheDocument();
  });
});

/* ── idle: buildDone → readyToRun card ───────────────────────────────────── */

describe("idle — buildDone=true", () => {
  it("shows readyToRun heading", () => {
    render(<RuntimePanel {...make({ buildDone: true })} />);
    expect(screen.getByText("runtimePanel.readyToRun")).toBeInTheDocument();
  });

  it("shows appBuilt hint", () => {
    render(<RuntimePanel {...make({ buildDone: true })} />);
    expect(screen.getByText("runtimePanel.appBuilt")).toBeInTheDocument();
  });

  it("clicking Run Project calls onRun", () => {
    const onRun = vi.fn();
    render(<RuntimePanel {...make({ buildDone: true, onRun })} />);
    fireEvent.click(screen.getByText("runtimePanel.runProject"));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

/* ── ready_to_run ─────────────────────────────────────────────────────────── */

describe("ready_to_run", () => {
  it("shows readyToRun card", () => {
    render(<RuntimePanel {...make({ runtimeState: "ready_to_run" })} />);
    expect(screen.getByText("runtimePanel.readyToRun")).toBeInTheDocument();
  });

  it("clicking Run Project calls onRun", () => {
    const onRun = vi.fn();
    render(<RuntimePanel {...make({ runtimeState: "ready_to_run", onRun })} />);
    fireEvent.click(screen.getByText("runtimePanel.runProject"));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

/* ── starting ─────────────────────────────────────────────────────────────── */

describe("starting", () => {
  it("shows startingRuntime heading", () => {
    render(<RuntimePanel {...make({ runtimeState: "starting" })} />);
    expect(screen.getByText("runtimePanel.startingRuntime")).toBeInTheDocument();
  });

  it("shows detectingType when no startup messages", () => {
    render(<RuntimePanel {...make({ runtimeState: "starting", startupMessages: [] })} />);
    expect(screen.getByText("runtimePanel.detectingType")).toBeInTheDocument();
  });

  it("renders startup messages instead of detectingType", () => {
    render(<RuntimePanel {...make({ runtimeState: "starting", startupMessages: ["Installing deps…", "Starting server…"] })} />);
    expect(screen.getByText("Installing deps…")).toBeInTheDocument();
    expect(screen.getByText("Starting server…")).toBeInTheDocument();
    expect(screen.queryByText("runtimePanel.detectingType")).not.toBeInTheDocument();
  });
});

/* ── running ──────────────────────────────────────────────────────────────── */

describe("running", () => {
  const runningProps = make({
    runtimeState: "running",
    previewUrl: "/api/projects/p1/proxy/",
    previewType: "proxy",
  });

  it("renders an iframe", () => {
    const { container } = render(<RuntimePanel {...runningProps} />);
    const iframe = container.querySelector("iframe");
    expect(iframe).toBeInTheDocument();
  });

  it("clicking Restart calls onRestart", () => {
    const onRestart = vi.fn();
    render(<RuntimePanel {...runningProps} onRestart={onRestart} />);
    fireEvent.click(screen.getByText("runtimePanel.restart"));
    expect(onRestart).toHaveBeenCalledTimes(1);
  });

  it("clicking Stop calls onStop", () => {
    const onStop = vi.fn();
    render(<RuntimePanel {...runningProps} onStop={onStop} />);
    fireEvent.click(screen.getByText("runtimePanel.stop"));
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});

/* ── stopping ─────────────────────────────────────────────────────────────── */

describe("stopping", () => {
  it("shows stopping key", () => {
    render(<RuntimePanel {...make({ runtimeState: "stopping" })} />);
    expect(screen.getByText("runtimePanel.stopping")).toBeInTheDocument();
  });
});

/* ── stopped ──────────────────────────────────────────────────────────────── */

describe("stopped", () => {
  it("shows runtimeStopped heading", () => {
    render(<RuntimePanel {...make({ runtimeState: "stopped" })} />);
    expect(screen.getByText("runtimePanel.runtimeStopped")).toBeInTheDocument();
  });

  it("shows previewStopped hint", () => {
    render(<RuntimePanel {...make({ runtimeState: "stopped" })} />);
    expect(screen.getByText("runtimePanel.previewStopped")).toBeInTheDocument();
  });

  it("clicking Run Again calls onRun", () => {
    const onRun = vi.fn();
    render(<RuntimePanel {...make({ runtimeState: "stopped", onRun })} />);
    fireEvent.click(screen.getByText("runtimePanel.runAgain"));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

/* ── failed ───────────────────────────────────────────────────────────────── */

const testError: RuntimeError = {
  category: "startup",
  message: "Port 3000 already in use",
  fix: ["Kill the existing process.", "Change the port in your config."],
  severity: "high",
};

describe("failed", () => {
  const failedProps = make({ runtimeState: "failed", runtimeError: testError });

  it("shows the error message", () => {
    render(<RuntimePanel {...failedProps} />);
    expect(screen.getByText("Port 3000 already in use")).toBeInTheDocument();
  });

  it("renders fix steps", () => {
    render(<RuntimePanel {...failedProps} />);
    expect(screen.getByText("Kill the existing process.")).toBeInTheDocument();
    expect(screen.getByText("Change the port in your config.")).toBeInTheDocument();
  });

  it("shows runFailed heading", () => {
    render(<RuntimePanel {...failedProps} />);
    expect(screen.getByText("runtimePanel.runFailed")).toBeInTheDocument();
  });

  it("clicking Retry calls onRun", () => {
    const onRun = vi.fn();
    render(<RuntimePanel {...failedProps} onRun={onRun} />);
    fireEvent.click(screen.getByText(/runtimePanel\.retry/));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("clicking Explain with AI calls onExplainError with the error", () => {
    const onExplainError = vi.fn();
    render(<RuntimePanel {...failedProps} onExplainError={onExplainError} />);
    fireEvent.click(screen.getByText(/runtimePanel\.explainWithAI/));
    expect(onExplainError).toHaveBeenCalledWith(testError);
  });

  it("failed state not rendered when runtimeError is null", () => {
    render(<RuntimePanel {...make({ runtimeState: "failed", runtimeError: null })} />);
    expect(screen.queryByText("runtimePanel.runFailed")).not.toBeInTheDocument();
  });

  it("copy button toggles to copied state on click", async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    render(<RuntimePanel {...failedProps} />);
    const copyBtn = screen.getByRole("button", { name: "runtimePanel.copyError" });
    fireEvent.click(copyBtn);
    await waitFor(() =>
      expect(screen.getByText(/runtimePanel\.copied/)).toBeInTheDocument()
    );
  });
});
