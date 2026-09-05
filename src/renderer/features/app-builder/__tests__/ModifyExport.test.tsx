/**
 * MODIFY + EXPORT GATE tests — Cases N through Q
 *
 * Cases covered:
 *   N-1. Modify action → streamBuild called (not /api/ai/chat)
 *   N-2. Generate action → streamBuild called (not /api/ai/chat)
 *   O-1. Topbar export button → calls /api/projects/{id}/download
 *   O-2. Done-banner export button → same endpoint
 *   O-3. Sidebar export button → same endpoint
 *   O-4. No project id → download silently aborts (no apiFetch)
 *   P-1. isDownloading guard → at most one in-flight request
 *   Q-1. 500 error → Arabic خطأ error shown in DOM
 */
import {
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
  type Mock,
} from "vitest";
import type { BuildEvent } from "../services/builderService";
import { AppBuilderPage } from "../AppBuilderPage";

vi.setConfig({ testTimeout: 60_000 });

HTMLElement.prototype.scrollIntoView = vi.fn();

/* ── Global mocks ─────────────────────────────────────────────── */

vi.mock("../../../contexts/app", () => ({
  useAppContext: () => ({ setPage: vi.fn() }),
}));

vi.mock("../../../contexts/toast", () => ({
  useToast: () => vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "ar" },
  }),
}));

/* builderService — spy directly; vi.mock ensures module is resolvable */
import * as builderService from "../services/builderService";

/**
 * Mock the shared API module that AppBuilderPage + AICopilotPanel import.
 * Path is relative to this test file, resolving to src/renderer/utils/api.
 */
vi.mock("../../../utils/api", async (importOriginal) => {
  const mod = (await importOriginal()) as Record<string, unknown>;
  return {
    ...mod,
    apiFetch: vi.fn(),
    parseJSON: vi.fn(),
  };
});

import { apiFetch } from "../../../utils/api";
const apiFetchMock = apiFetch as Mock;

/* ── AsyncIterable helpers ────────────────────────────────────── */

function makeEventStream(events: BuildEvent[]): AsyncIterable<BuildEvent> {
  return {
    [Symbol.asyncIterator](): AsyncIterator<BuildEvent> {
      let i = 0;
      return {
        next(): Promise<IteratorResult<BuildEvent>> {
          if (i < events.length) {
            return Promise.resolve({ value: events[i++], done: false });
          }
          return Promise.resolve({
            value: undefined as unknown as BuildEvent,
            done: true,
          });
        },
      };
    },
  };
}

function doneBuildStream(): AsyncIterable<BuildEvent> {
  return makeEventStream([
    { type: "status", message: "Starting…" },
    {
      type: "done",
      description: "ok",
      files: ["index.ts"],
      run_command: "",
      language: "TypeScript",
    },
  ]);
}

/* ── Shared setup ─────────────────────────────────────────────── */

let streamBuildSpy: Mock;

beforeEach(() => {
  vi.spyOn(builderService, "createProject").mockResolvedValue({
    id: "proj-1",
    name: "Test App",
    description: "",
    created_at: "",
    updated_at: "",
    user_id: "",
    status: "active",
  } as never);

  vi.spyOn(builderService, "getProject").mockRejectedValue(
    new Error("not found"),
  );

  streamBuildSpy = vi.spyOn(builderService, "streamBuild");

  // Default: /api/build/plan rejects → handleStartBuild falls through to handleBuild
  apiFetchMock.mockRejectedValue(new Error("plan unavailable"));

  sessionStorage.removeItem("flow_active_project");
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.removeItem("flow_active_project");
});

/* ── Helpers ──────────────────────────────────────────────────── */

function submitEntryPrompt(text: string) {
  const textarea = screen.getByRole("textbox");
  fireEvent.change(textarea, { target: { value: text } });
  fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
}

/**
 * Renders AppBuilderPage and drives a successful build so the
 * 3-panel workspace (with AICopilotPanel + export buttons) is shown.
 * Returns after the topbar export button is in the DOM.
 */
async function reachWorkspace(): Promise<void> {
  streamBuildSpy.mockReturnValue(doneBuildStream());

  render(<AppBuilderPage />);
  submitEntryPrompt("Build a test app");

  // Wait until the workspace is rendered — the topbar export button is
  // our reliable signal that buildDone=true and the 3-panel layout is live.
  await waitFor(
    () => expect(screen.getByTestId("topbar-export-btn")).toBeInTheDocument(),
    { timeout: 12_000 },
  );
}

/* ═══════════════════════════════════════════════════════════════
   Case N — Modify / Generate routes to build pipeline
   ═══════════════════════════════════════════════════════════════ */

describe("Case N — Modify action routes to build pipeline", () => {
  it("N-1: modify sends to streamBuild, NOT /api/ai/chat", async () => {
    await reachWorkspace();

    // After initial build, streamBuild was called once
    const callsBefore = streamBuildSpy.mock.calls.length;

    // Click "✏️ عدّل" action tab to switch to modify mode
    const modifyBtn = screen.getByRole("button", { name: "✏️ عدّل" });
    fireEvent.click(modifyBtn);

    // Set up the rebuild stream
    streamBuildSpy.mockReturnValueOnce(
      makeEventStream([
        { type: "status", message: "Modifying…" },
        {
          type: "done",
          description: "ok",
          files: ["login.ts"],
          run_command: "",
          language: "TypeScript",
        },
      ]),
    );

    // Clear apiFetch call history so we only see calls from now on
    apiFetchMock.mockClear();

    // Type in AICopilotPanel's textarea and send
    const copilotTextarea = screen.getByRole("textbox");
    fireEvent.change(copilotTextarea, { target: { value: "Add a login page" } });
    fireEvent.keyDown(copilotTextarea, { key: "Enter", shiftKey: false });

    // streamBuild must be called a 2nd time (for the modify rebuild)
    await waitFor(
      () => expect(streamBuildSpy.mock.calls.length).toBeGreaterThan(callsBefore),
      { timeout: 8_000 },
    );

    // apiFetch must NOT have been called with /api/ai/chat
    const chatCalls = apiFetchMock.mock.calls.filter(
      (args: unknown[]) =>
        typeof args[0] === "string" && (args[0] as string).includes("/api/ai/chat"),
    );
    expect(chatCalls).toHaveLength(0);
  });

  it("N-2: generate sends to streamBuild, NOT /api/ai/chat", async () => {
    await reachWorkspace();

    // Default action is "generate" — no tab click needed
    const callsBefore = streamBuildSpy.mock.calls.length;

    streamBuildSpy.mockReturnValueOnce(
      makeEventStream([
        {
          type: "done",
          description: "ok",
          files: ["dashboard.ts"],
          run_command: "",
          language: "TypeScript",
        },
      ]),
    );

    apiFetchMock.mockClear();

    const copilotTextarea = screen.getByRole("textbox");
    fireEvent.change(copilotTextarea, { target: { value: "Add a dashboard" } });
    fireEvent.keyDown(copilotTextarea, { key: "Enter", shiftKey: false });

    await waitFor(
      () => expect(streamBuildSpy.mock.calls.length).toBeGreaterThan(callsBefore),
      { timeout: 8_000 },
    );

    const chatCalls = apiFetchMock.mock.calls.filter(
      (args: unknown[]) =>
        typeof args[0] === "string" && (args[0] as string).includes("/api/ai/chat"),
    );
    expect(chatCalls).toHaveLength(0);
  });
});

/* ═══════════════════════════════════════════════════════════════
   Case O — Export buttons call correct download endpoint
   ═══════════════════════════════════════════════════════════════ */

describe("Case O — Download endpoint", () => {
  // jsdom does not implement URL.createObjectURL; mock it for download tests
  beforeEach(() => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  function mockSuccessfulDownload(): void {
    const mockBlob = new Blob(["zip content"], { type: "application/zip" });
    apiFetchMock.mockResolvedValueOnce({
      ok: true,
      blob: () => Promise.resolve(mockBlob),
      headers: { get: () => null },
    });
  }

  it("O-1: topbar export button calls /api/projects/{id}/download", async () => {
    await reachWorkspace();

    // createProject returned id "proj-1" → handleBuild stored it in sessionStorage
    expect(sessionStorage.getItem("flow_active_project")).toBe("proj-1");

    mockSuccessfulDownload();
    fireEvent.click(screen.getByTestId("topbar-export-btn"));

    await waitFor(
      () =>
        expect(apiFetchMock).toHaveBeenCalledWith(
          "/api/projects/proj-1/download",
        ),
      { timeout: 6_000 },
    );
  });

  it("O-2: done-banner export button calls correct endpoint", async () => {
    await reachWorkspace();

    // Done banner is rendered when buildDone=true
    const doneBannerBtn = screen.getByTestId("done-export-btn");
    expect(doneBannerBtn).toBeInTheDocument();

    mockSuccessfulDownload();
    fireEvent.click(doneBannerBtn);

    await waitFor(
      () =>
        expect(apiFetchMock).toHaveBeenCalledWith(
          "/api/projects/proj-1/download",
        ),
      { timeout: 6_000 },
    );
  });

  it("O-3: sidebar export button calls correct endpoint", async () => {
    await reachWorkspace();

    const sidebarBtn = screen.getByTestId("sidebar-export-btn");
    expect(sidebarBtn).toBeInTheDocument();

    mockSuccessfulDownload();
    fireEvent.click(sidebarBtn);

    await waitFor(
      () =>
        expect(apiFetchMock).toHaveBeenCalledWith(
          "/api/projects/proj-1/download",
        ),
      { timeout: 6_000 },
    );
  });

  it("O-4: no active project → download aborts without calling apiFetch", async () => {
    await reachWorkspace();

    // Remove project id
    sessionStorage.removeItem("flow_active_project");
    apiFetchMock.mockClear();

    fireEvent.click(screen.getByTestId("topbar-export-btn"));

    // No download endpoint should be hit
    expect(
      apiFetchMock.mock.calls.filter((args: unknown[]) =>
        typeof args[0] === "string" && (args[0] as string).includes("/download"),
      ),
    ).toHaveLength(0);
  });
});

/* ═══════════════════════════════════════════════════════════════
   Case P — Loading guard prevents duplicate requests
   ═══════════════════════════════════════════════════════════════ */

describe("Case P — Loading guard", () => {
  it("P-1: button is disabled while download is in flight", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    await reachWorkspace();

    // Make apiFetch hang indefinitely to keep isDownloading=true
    let resolveDownload!: (v: unknown) => void;
    const hangingPromise = new Promise(r => { resolveDownload = r; });
    apiFetchMock.mockReturnValueOnce(hangingPromise);

    const btn = screen.getByTestId("topbar-export-btn");
    fireEvent.click(btn);

    // After first click, button should become disabled (isDownloading=true)
    await waitFor(
      () => expect(screen.getByTestId("topbar-export-btn")).toBeDisabled(),
      { timeout: 5_000 },
    );

    // apiFetch called exactly once (guard prevented any duplicate)
    const downloadCalls = apiFetchMock.mock.calls.filter(
      (args: unknown[]) =>
        typeof args[0] === "string" && (args[0] as string).includes("/download"),
    );
    expect(downloadCalls).toHaveLength(1);

    // Resolve to clean up the hanging promise
    resolveDownload({ ok: false, text: () => Promise.resolve("") });
  });
});

/* ═══════════════════════════════════════════════════════════════
   Case Q — Error handling shows Arabic error in DOM
   ═══════════════════════════════════════════════════════════════ */

describe("Case Q — Download error shows Arabic error", () => {
  it("Q-1: 500 response shows خطأ 500 in the UI", async () => {
    await reachWorkspace();

    apiFetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: () => Promise.resolve("Internal Server Error"),
    });

    fireEvent.click(screen.getByTestId("topbar-export-btn"));

    await waitFor(
      () => expect(screen.getByText(/خطأ 500/)).toBeInTheDocument(),
      { timeout: 6_000 },
    );
  });

  it("Q-2: network error (throw) shows Arabic fallback message", async () => {
    await reachWorkspace();

    apiFetchMock.mockRejectedValueOnce(new Error("Network failure"));

    fireEvent.click(screen.getByTestId("topbar-export-btn"));

    await waitFor(
      () => expect(screen.getByText(/Network failure/)).toBeInTheDocument(),
      { timeout: 6_000 },
    );
  });
});
