/**
 * BottomTabBar — tab navigation, RuntimeConsole, and build tab tests.
 *
 * Cases covered:
 *   Tab navigation: Build (default), Runtime, Logs
 *   Tab badges: error "!", done "✓", event count
 *   Build tab: empty hint, Building… indicator, Build complete message
 *   RuntimeConsole: filter buttons, search, clear, pause/live toggle, empty states
 *   Keyboard accessibility: drag-handle ArrowUp / ArrowDown calls onResize
 *
 * react-i18next is mocked so t(key) === key; assertions are key-based.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BottomTabBar } from "../components/BottomTabBar";
import type { BuildEventItem, RuntimeEventItem } from "../components/BottomTabBar";

HTMLElement.prototype.scrollIntoView = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const noop = vi.fn();

function makeProps(overrides: Partial<Parameters<typeof BottomTabBar>[0]> = {}) {
  return {
    buildEvents: [] as BuildEventItem[],
    buildDone: false,
    buildError: null,
    isBuilding: false,
    fileCount: 0,
    language: "",
    projectId: "proj-1",
    plan: null,
    height: 240,
    onResize: noop,
    runtimeEvents: [] as RuntimeEventItem[],
    runtimeState: "idle" as const,
    ...overrides,
  };
}

function makeRuntimeEvent(overrides: Partial<RuntimeEventItem> = {}): RuntimeEventItem {
  return {
    timestamp: Date.now(),
    type: "log",
    message: "hello",
    stream: "stdout",
    ...overrides,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

/* ── Tab navigation ──────────────────────────────────────────────────────── */

describe("tab navigation", () => {
  it("builds tab is active by default and shows empty hint", () => {
    render(<BottomTabBar {...makeProps()} />);
    expect(screen.getByText("bottomTabBar.build.emptyHint")).toBeInTheDocument();
  });

  it("renders three visible tabs", () => {
    render(<BottomTabBar {...makeProps()} />);
    expect(screen.getByText("bottomTabBar.tabs.build")).toBeInTheDocument();
    expect(screen.getByText("bottomTabBar.tabs.runtime")).toBeInTheDocument();
    expect(screen.getByText("bottomTabBar.tabs.logs")).toBeInTheDocument();
  });

  it("clicking Runtime tab shows RuntimeConsole filter buttons", () => {
    render(<BottomTabBar {...makeProps()} />);
    fireEvent.click(screen.getByText("bottomTabBar.tabs.runtime"));
    expect(screen.getByText("bottomTabBar.console.filterAll")).toBeInTheDocument();
  });

  it("clicking Logs tab shows raw log output area", () => {
    const events: BuildEventItem[] = [
      { timestamp: 1000, type: "status", message: "Starting build" },
    ];
    render(<BottomTabBar {...makeProps({ buildEvents: events })} />);
    fireEvent.click(screen.getByText("bottomTabBar.tabs.logs"));
    expect(screen.getByText(/Starting build/)).toBeInTheDocument();
  });
});

/* ── Tab badges ──────────────────────────────────────────────────────────── */

describe("tab badges", () => {
  it("shows '!' badge on build tab when buildError is set", () => {
    render(<BottomTabBar {...makeProps({ buildError: "Something failed" })} />);
    expect(screen.getByText("!")).toBeInTheDocument();
  });

  it("shows '✓' badge on build tab when buildDone", () => {
    render(<BottomTabBar {...makeProps({ buildDone: true })} />);
    // "✓" appears both in the tab badge and in the build-complete message
    expect(screen.getAllByText("✓").length).toBeGreaterThanOrEqual(1);
  });

  it("shows runtime event count as badge on runtime tab", () => {
    const events = [makeRuntimeEvent(), makeRuntimeEvent(), makeRuntimeEvent()];
    render(<BottomTabBar {...makeProps({ runtimeEvents: events })} />);
    expect(screen.getByText("3")).toBeInTheDocument();
  });
});

/* ── Build tab content ───────────────────────────────────────────────────── */

describe("build tab content", () => {
  it("shows Building… indicator when isBuilding=true", () => {
    render(<BottomTabBar {...makeProps({ isBuilding: true })} />);
    expect(screen.getByText("bottomTabBar.build.building")).toBeInTheDocument();
  });

  it("shows buildComplete key when buildDone and fileCount > 0", () => {
    render(<BottomTabBar {...makeProps({ buildDone: true, fileCount: 5 })} />);
    expect(screen.getByText("bottomTabBar.build.buildComplete")).toBeInTheDocument();
  });

  it("shows buildCompleteNoCount when buildDone and fileCount is 0", () => {
    render(<BottomTabBar {...makeProps({ buildDone: true, fileCount: 0 })} />);
    expect(screen.getByText("bottomTabBar.build.buildCompleteNoCount")).toBeInTheDocument();
  });

  it("shows build event messages in the timeline", () => {
    const events: BuildEventItem[] = [
      { timestamp: 1000, type: "file", message: "Writing index.html" },
    ];
    render(<BottomTabBar {...makeProps({ buildEvents: events })} />);
    expect(screen.getByText("Writing index.html")).toBeInTheDocument();
  });
});

/* ── RuntimeConsole ──────────────────────────────────────────────────────── */

describe("RuntimeConsole", () => {
  function renderConsole(overrides: Partial<Parameters<typeof BottomTabBar>[0]> = {}) {
    render(<BottomTabBar {...makeProps(overrides)} />);
    fireEvent.click(screen.getByText("bottomTabBar.tabs.runtime"));
  }

  it("shows all four filter buttons", () => {
    renderConsole();
    expect(screen.getByText("bottomTabBar.console.filterAll")).toBeInTheDocument();
    expect(screen.getByText("bottomTabBar.console.filterStdout")).toBeInTheDocument();
    expect(screen.getByText("bottomTabBar.console.filterStderr")).toBeInTheDocument();
    expect(screen.getByText("bottomTabBar.console.filterErrors")).toBeInTheDocument();
  });

  it("shows emptyIdle message when no events and runtimeState is idle", () => {
    renderConsole({ runtimeEvents: [], runtimeState: "idle" });
    expect(screen.getByText("bottomTabBar.console.emptyIdle")).toBeInTheDocument();
  });

  it("shows emptyWaiting message when no events and runtimeState is starting", () => {
    renderConsole({ runtimeEvents: [], runtimeState: "starting" });
    expect(screen.getByText("bottomTabBar.console.emptyWaiting")).toBeInTheDocument();
  });

  it("renders log event messages", () => {
    const events = [makeRuntimeEvent({ message: "Server started on port 3000" })];
    renderConsole({ runtimeEvents: events });
    expect(screen.getByText("Server started on port 3000")).toBeInTheDocument();
  });

  it("search input hides non-matching events", () => {
    const events = [
      makeRuntimeEvent({ message: "Server started" }),
      makeRuntimeEvent({ message: "Client connected" }),
    ];
    renderConsole({ runtimeEvents: events });
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Server" } });
    // "Client connected" must be hidden; "Server started" is split by <mark> so
    // check for the unmatched suffix text node instead of the full string.
    expect(screen.queryByText("Client connected")).not.toBeInTheDocument();
    // highlight() wraps the matched term in <mark>; verify the mark element is rendered
    expect(screen.getByText("Server")).toBeInTheDocument();
  });

  it("search with no matches shows noMatches key", () => {
    const events = [makeRuntimeEvent({ message: "Server started" })];
    renderConsole({ runtimeEvents: events });
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "xyz_no_match" } });
    expect(screen.getByText("bottomTabBar.console.noMatches")).toBeInTheDocument();
  });

  it("pause button shows paused key when clicked", () => {
    renderConsole({ runtimeEvents: [makeRuntimeEvent()] });
    const pauseBtn = screen.getByRole("button", { name: "bottomTabBar.console.pauseAriaLabel" });
    fireEvent.click(pauseBtn);
    expect(screen.getByText("bottomTabBar.console.paused")).toBeInTheDocument();
  });

  it("clear button hides prior events", () => {
    const events = [makeRuntimeEvent({ message: "Old log line" })];
    renderConsole({ runtimeEvents: events });
    expect(screen.getByText("Old log line")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "bottomTabBar.console.clearAriaLabel" }));
    expect(screen.queryByText("Old log line")).not.toBeInTheDocument();
  });

  it("stderr filter hides stdout events", () => {
    const events = [
      makeRuntimeEvent({ message: "stdout line", stream: "stdout" }),
      makeRuntimeEvent({ message: "stderr line", stream: "stderr", type: "log" }),
    ];
    renderConsole({ runtimeEvents: events });
    fireEvent.click(screen.getByText("bottomTabBar.console.filterStderr"));
    expect(screen.queryByText("stdout line")).not.toBeInTheDocument();
    expect(screen.getByText("stderr line")).toBeInTheDocument();
  });

  it("errors filter shows only error-type events", () => {
    const events = [
      makeRuntimeEvent({ message: "normal log", type: "log" }),
      makeRuntimeEvent({ message: "runtime error", type: "error" }),
    ];
    renderConsole({ runtimeEvents: events });
    fireEvent.click(screen.getByText("bottomTabBar.console.filterErrors"));
    expect(screen.queryByText("normal log")).not.toBeInTheDocument();
    expect(screen.getByText("runtime error")).toBeInTheDocument();
  });
});

/* ── Keyboard accessibility on drag handle ───────────────────────────────── */

describe("drag handle keyboard resize", () => {
  it("ArrowUp calls onResize with height + 20", () => {
    const onResize = vi.fn();
    render(<BottomTabBar {...makeProps({ height: 240, onResize })} />);
    const handle = screen.getByRole("button", { name: "bottomTabBar.dragAriaLabel" });
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(onResize).toHaveBeenCalledWith(260);
  });

  it("ArrowDown calls onResize with height - 20", () => {
    const onResize = vi.fn();
    render(<BottomTabBar {...makeProps({ height: 240, onResize })} />);
    const handle = screen.getByRole("button", { name: "bottomTabBar.dragAriaLabel" });
    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(onResize).toHaveBeenCalledWith(220);
  });

  it("ArrowUp clamps to max 480", () => {
    const onResize = vi.fn();
    render(<BottomTabBar {...makeProps({ height: 475, onResize })} />);
    const handle = screen.getByRole("button", { name: "bottomTabBar.dragAriaLabel" });
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(onResize).toHaveBeenCalledWith(480);
  });

  it("ArrowDown clamps to min 120", () => {
    const onResize = vi.fn();
    render(<BottomTabBar {...makeProps({ height: 125, onResize })} />);
    const handle = screen.getByRole("button", { name: "bottomTabBar.dragAriaLabel" });
    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(onResize).toHaveBeenCalledWith(120);
  });
});
