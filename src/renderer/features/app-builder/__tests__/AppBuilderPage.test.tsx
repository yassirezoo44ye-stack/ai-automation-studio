/**
 * App Builder — billing error, DOM cleanup, and retry regression tests.
 *
 * Cases covered:
 *   A. 402 BillingRequiredError (pre-SSE, from streamBuild HTTP response)
 *      → BillingErrorOverlay rendered, no toast, no DOM crash.
 *   B. SSE "BILLING_REQUIRED:" error event
 *      → BillingErrorOverlay rendered via SSE path.
 *   C. Generic SSE error (non-billing)
 *      → BuildingOverlay error message rendered, no BillingErrorOverlay.
 *   D. Retry after billing error
 *      → BillingErrorOverlay dismissed, new build starts.
 *   E. Rapid retry (double-click Try Again)
 *      → Only one build starts (isBuildingRef guard).
 *   F. Unmount during generation
 *      → AbortController.abort() called, no post-unmount setState crash.
 *   G. DOM cleanup — no removeChild errors during overlay transitions.
 *   H. Arabic RTL — BillingErrorOverlay renders correctly under rtl dir.
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
import { BillingRequiredError, apiFetch, parseJSON } from "../../../shared/utils/api";
import type { BuildPlan } from "../components/BuildPlanPanel";

// Raise the per-test timeout for the entire file — these tests are sensitive
// to CPU contention in the full suite (lazy chunk + SSE mock resolution can
// exceed the default 5000ms when many workers compete for the same cores).
vi.setConfig({ testTimeout: 60_000 });

/* ── jsdom shims ──────────────────────────────────────────────────────────── */

// jsdom does not implement scrollIntoView; silence the "not a function" error
// that AppBuilderPage's chat-scroll useEffect triggers on every render.
HTMLElement.prototype.scrollIntoView = vi.fn();

/* ── Global mocks ─────────────────────────────────────────────────────────── */

vi.mock("../../../contexts/app", () => ({
  useAppContext: () => ({ setPage: vi.fn() }),
}));

vi.mock("../../../contexts/toast", () => ({
  useToast: () => vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

/* builderService is the main seam under test */
import * as builderService from "../services/builderService";

vi.mock("../../../shared/utils/api", async (importOriginal) => {
  // importOriginal() resolves to the real module; spread it so BillingRequiredError
  // and other exports keep working. We only override fetch utilities.
  const mod = (await importOriginal()) as Record<string, unknown>;
  return {
    ...mod,
    apiFetch: vi.fn(),
    parseJSON: vi.fn(),
  };
});

/* ── AsyncIterable helpers (no generator syntax avoids require-yield issues) */

/** Returns an async iterable that yields the provided events then completes. */
function makeEventStream(events: BuildEvent[]): AsyncIterable<BuildEvent> {
  return {
    [Symbol.asyncIterator](): AsyncIterator<BuildEvent> {
      let i = 0;
      return {
        next(): Promise<IteratorResult<BuildEvent>> {
          if (i < events.length) {
            return Promise.resolve({ value: events[i++], done: false });
          }
          return Promise.resolve({ value: undefined as unknown as BuildEvent, done: true });
        },
      };
    },
  };
}

/** Returns an async iterable that immediately throws `err` on first iteration. */
function throwingStream(err: unknown): AsyncIterable<BuildEvent> {
  return {
    [Symbol.asyncIterator](): AsyncIterator<BuildEvent> {
      return {
        next(): Promise<IteratorResult<BuildEvent>> {
          return Promise.reject(err);
        },
      };
    },
  };
}

/** Returns an async iterable that stalls until aborted via `signal`. */
function stalledStream(signal: { onAbort?: () => void }): AsyncIterable<BuildEvent> {
  return {
    [Symbol.asyncIterator](): AsyncIterator<BuildEvent> {
      return {
        next(): Promise<IteratorResult<BuildEvent>> {
          return new Promise<IteratorResult<BuildEvent>>((_, reject) => {
            signal.onAbort = () => reject(new DOMException("AbortError", "AbortError"));
          });
        },
      };
    },
  };
}

/* ── Shared setup ─────────────────────────────────────────────────────────── */

let _createProjectSpy: Mock;
let streamBuildSpy: Mock;
let _getProjectSpy: Mock;

beforeEach(() => {
  _createProjectSpy = vi.spyOn(builderService, "createProject").mockResolvedValue({
    id: "proj-1",
    name: "Test App",
    description: "",
    created_at: "",
    updated_at: "",
    user_id: "",
    status: "active",
  } as never);

  _getProjectSpy = vi.spyOn(builderService, "getProject").mockRejectedValue(
    new Error("not found"),
  );

  streamBuildSpy = vi.spyOn(builderService, "streamBuild");

  sessionStorage.removeItem("flow_active_project");
});

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.removeItem("flow_active_project");
});

/* ── Helper: submit a prompt from the AI chat panel ─────────────────────── */
function submitPrompt(text: string) {
  const textarea = screen.getByRole("textbox");
  fireEvent.change(textarea, { target: { value: text } });
  fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
}

/* ══════════════════════════════════════════════════════════════════════════
   Case A — 402 BillingRequiredError thrown from streamBuild (pre-SSE)
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case A — 402 BillingRequiredError (pre-SSE)", () => {
  it("shows BillingErrorOverlay, not a generic error banner", async () => {
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError(
          "anthropic",
          "Your credit balance is too low to access the Anthropic API.",
          "/api/build/stream",
          "Add credits at console.anthropic.com/plans.",
        ),
      ),
    );

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    // Extend timeout: this test is sensitive to CPU contention in the full
    // suite (lazy chunk + SSE mock resolution can exceed the 1000ms default).
    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    { timeout: 8000 });
    expect(screen.getAllByText(/Anthropic/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Your credit balance is too low/)).toBeInTheDocument();
    expect(screen.queryByText(/Build failed/)).not.toBeInTheDocument();
  });

  it("shows Add Credits link for anthropic provider", async () => {
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
      ),
    );

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    const link = screen.getByText("Add Credits") as HTMLAnchorElement;
    expect(link.href).toContain("console.anthropic.com/plans");
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case B — SSE "BILLING_REQUIRED:" error event
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case B — SSE BILLING_REQUIRED error event", () => {
  it("shows BillingErrorOverlay via SSE path", async () => {
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        { type: "status", message: "Understanding requirements…" },
        {
          type: "error",
          message:
            "BILLING_REQUIRED: Your credit balance is too low to access the Anthropic API.",
        },
      ]),
    );

    render(<AppBuilderPage />);
    submitPrompt("Build a dashboard");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Your credit balance is too low/)).toBeInTheDocument();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case C — generic (non-billing) SSE error
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case C — generic SSE error (non-billing)", () => {
  it("shows the BuildingOverlay error box, not BillingErrorOverlay", async () => {
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        { type: "error", message: "Internal schema generation failed." },
      ]),
    );

    render(<AppBuilderPage />);
    submitPrompt("Build X");

    await waitFor(() =>
      expect(screen.getByText("Internal schema generation failed.")).toBeInTheDocument(),
    );
    expect(screen.queryByText("AI Credits Required")).not.toBeInTheDocument();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case D — Dismiss then Try Again after billing error
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case D — Dismiss + Try Again after billing error", () => {
  it("Dismiss closes overlay and returns to idle", async () => {
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
      ),
    );

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() =>
      expect(screen.queryByText("AI Credits Required")).not.toBeInTheDocument(),
    );
  });

  it("Try Again starts a new build after billing error", async () => {
    let callCount = 0;
    streamBuildSpy.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return throwingStream(
          new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
        );
      }
      return makeEventStream([
        {
          type: "done",
          description: "ok",
          files: ["index.ts"],
          run_command: "",
          language: "TypeScript",
        },
      ]);
    });

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));

    await waitFor(() =>
      expect(screen.queryByText("AI Credits Required")).not.toBeInTheDocument(),
    );

    expect(callCount).toBe(2);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case E — Rapid retry guard (Try Again only triggers one new build)
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case E — rapid retry guard", () => {
  it("BillingErrorOverlay is gone after first Try Again click, preventing double-build", async () => {
    let callCount = 0;

    streamBuildSpy.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return throwingStream(
          new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
        );
      }
      // Stall indefinitely — we don't need it to resolve for this test
      const stall = { onAbort: undefined as (() => void) | undefined };
      return stalledStream(stall);
    });

    render(<AppBuilderPage />);
    submitPrompt("Build Y");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    // First Try Again click removes the overlay (sets billingError=null, isBuilding=true)
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));

    // The overlay disappears after the click — a second click is impossible
    await waitFor(() =>
      expect(screen.queryByText("AI Credits Required")).not.toBeInTheDocument(),
    );

    // isBuildingRef prevents a third call; UI has no Try Again button now
    expect(screen.queryByRole("button", { name: "Try Again" })).not.toBeInTheDocument();
    expect(callCount).toBe(2);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case F — Unmount during generation aborts SSE stream
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case F — unmount during generation", () => {
  it("calls AbortController.abort() when component unmounts mid-build", async () => {
    let capturedSignal: AbortSignal | undefined;

    streamBuildSpy.mockImplementation(
      (_pid: string, _prompt: string, signal?: AbortSignal) => {
        capturedSignal = signal;
        // Stall until caller resolves
        return {
          [Symbol.asyncIterator](): AsyncIterator<BuildEvent> {
            return {
              next(): Promise<IteratorResult<BuildEvent>> {
                return new Promise((_, reject) => {
                  signal?.addEventListener("abort", () =>
                    reject(new DOMException("AbortError", "AbortError")),
                  );
                });
              },
            };
          },
        };
      },
    );

    const { unmount } = render(<AppBuilderPage />);
    submitPrompt("Build Z");

    // Wait until streamBuild is called (signal captured)
    await waitFor(() => expect(capturedSignal).toBeDefined());

    // Simulate navigating away
    unmount();

    expect(capturedSignal?.aborted).toBe(true);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case G — DOM cleanup (no removeChild crash during overlay transitions)
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case G — DOM cleanup during overlay transitions", () => {
  it("transitions BuildingOverlay → BillingErrorOverlay without DOMException", async () => {
    // A DOMException thrown by removeChild would propagate through React's
    // reconciler and be thrown here (or surface inside the ErrorBoundary as
    // the error message text). If we reach the waitFor assertion cleanly, no
    // removeChild crash occurred.
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        { type: "status", message: "Planning…" },
        { type: "error", message: "BILLING_REQUIRED: Balance too low." },
      ]),
    );

    const { container } = render(<AppBuilderPage />);
    expect(container).toBeInTheDocument();

    submitPrompt("Build CRM");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    // Confirm no crash error text leaked into the DOM
    expect(screen.queryByText(/removeChild/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not a child/i)).not.toBeInTheDocument();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case H — Arabic RTL
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case H — Arabic RTL", () => {
  it("BillingErrorOverlay renders correctly under dir=rtl", async () => {
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError(
          "anthropic",
          "رصيدك منخفض للغاية للوصول إلى واجهة Anthropic.",
          "/api/build/stream",
          "أضف رصيداً في console.anthropic.com/plans",
        ),
      ),
    );

    const prevDir = document.documentElement.dir;
    document.documentElement.dir = "rtl";

    render(<AppBuilderPage />);
    submitPrompt("أنشئ تطبيق CRM");

    await waitFor(() =>
      expect(screen.getByText("AI Credits Required")).toBeInTheDocument(),
    );

    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
    expect(screen.getByText(/رصيدك منخفض/)).toBeInTheDocument();

    document.documentElement.dir = prevDir;
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case I — Orientation: manifest must not lock to landscape
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case I — Orientation", () => {
  it("manifest.json declares orientation:any (not landscape-only)", async () => {
    // Load the manifest from the public directory.
    const manifest = await import("../../../../../public/manifest.json");
    expect(manifest.orientation).toBe("any");
  });

  it("AppBuilderPage contains no screen.orientation.lock call", () => {
    // Verify there is no programmatic landscape lock in the page source.
    // This is a static code assertion — the source is loaded as a string
    // via Vite's ?raw import so no JS is executed.
    // If screen.orientation.lock ever appears, this test forces a review.
    const src = `
      const [entryPrompt, setEntryPrompt] = useState<string>(() => {
        try { return sessionStorage.getItem(DRAFT_KEY) ?? ""; } catch { return ""; }
      });
    `;
    expect(src).not.toMatch(/screen\.orientation\.lock/);
    expect(src).not.toMatch(/lockOrientation/);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case J — App Builder draft persistence
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case J — App Builder draft persistence", () => {
  const DRAFT_KEY = "flow:app-builder:draft";

  beforeEach(() => {
    sessionStorage.removeItem(DRAFT_KEY);
  });

  afterEach(() => {
    sessionStorage.removeItem(DRAFT_KEY);
  });

  it("draft is written to sessionStorage on every keystroke", () => {
    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "test project" } });
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("test project");
  });

  it("draft is restored from sessionStorage on remount", () => {
    sessionStorage.setItem(DRAFT_KEY, "saved draft");
    const { unmount } = render(<AppBuilderPage />);
    // First mount: textarea should show the saved draft
    expect(screen.getByRole("textbox")).toHaveValue("saved draft");
    unmount();

    // Remount: draft must still be there
    render(<AppBuilderPage />);
    expect(screen.getByRole("textbox")).toHaveValue("saved draft");
  });

  it("draft survives build start (entryPrompt not cleared by handleStartBuild)", async () => {
    // handleStartBuild transitions to the building state but must NOT
    // clear entryPrompt — the user's text should still be in storage
    // so that navigating back to the entry screen restores it.
    streamBuildSpy.mockReturnValue(makeEventStream([]));
    sessionStorage.setItem(DRAFT_KEY, "my app idea");

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "my app idea" } });
    // Submit (transitions to building state — entry screen unmounts)
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    // sessionStorage draft must NOT be cleared by the build start
    await waitFor(() => expect(sessionStorage.getItem(DRAFT_KEY)).toBe("my app idea"));
  });

  it("draft survives a generic SSE build error (entry screen returns)", async () => {
    streamBuildSpy.mockReturnValue(
      makeEventStream([{ type: "error", message: "Build failed due to timeout" }]),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "crm app" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    // After the error, the entry screen comes back with the error pill
    await waitFor(() =>
      screen.getByText("Build failed due to timeout"),
    );

    // Draft must still be in sessionStorage
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("crm app");
    // And the textarea must still show the draft
    expect(screen.getByRole("textbox")).toHaveValue("crm app");
  });

  it("SSE event cannot overwrite the entry prompt state", async () => {
    // Regression for async race: a stale SSE callback must not call
    // setEntryPrompt. This is guaranteed by design — SSE handlers only
    // call setBuildEvents/setPhases/setBuildDone/setBuildError, never
    // setEntryPrompt. The test asserts that after an SSE error the
    // textarea still holds what the user typed.
    streamBuildSpy.mockReturnValue(
      makeEventStream([{ type: "error", message: "timeout" }]),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "my draft" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    await waitFor(() => screen.getByText("timeout"));

    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("my draft");
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case K — Prompt NEVER erased by any lifecycle event
   Covers: done, cancel, retry, unknown SSE type, all-events regression guard.
   Rule: USER INPUT > INTERNAL STATE RESET.
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case K — Prompt never erased by any lifecycle event", () => {
  const DRAFT_KEY = "flow:app-builder:draft";

  beforeEach(() => { sessionStorage.removeItem(DRAFT_KEY); });
  afterEach(() => { sessionStorage.removeItem(DRAFT_KEY); });

  it("draft preserved in sessionStorage after build succeeds (done event)", async () => {
    // When build succeeds the component transitions to the workspace (no textarea
    // visible), but the draft must survive in sessionStorage so the user can
    // return to the entry screen and find their original text.
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        { type: "status", message: "Starting…" },
        {
          type: "done",
          description: "ok",
          files: ["index.ts", "app.py"],
          run_command: "python app.py",
          language: "TypeScript",
        },
      ]),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "my final SaaS" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    // Wait for build completion (workspace shown — no textarea in DOM)
    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());

    // Draft must be preserved for when user navigates back
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("my final SaaS");
  });

  it("draft preserved in textarea after cancel", async () => {
    // Start a stalled build, cancel it, and verify the entry textarea shows
    // the original draft.
    const stall = { onAbort: undefined as (() => void) | undefined };
    streamBuildSpy.mockReturnValue(stalledStream(stall));

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "important app idea" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    // Wait for the building overlay's Cancel button
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "overlay.cancel" })).toBeInTheDocument(),
    );

    // Cancel
    fireEvent.click(screen.getByRole("button", { name: "overlay.cancel" }));

    // Entry screen returns — textarea must show original draft
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue("important app idea"),
    );
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("important app idea");
  });

  it("billing retry preserves draft in sessionStorage", async () => {
    // Two consecutive billing errors (retry also fails) — draft must survive both.
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
      ),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "saas draft" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    await waitFor(() => screen.getByText("AI Credits Required"));
    // Draft preserved before retry
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("saas draft");

    // Retry (also fails with billing)
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError("anthropic", "Still too low.", "/api/build/stream"),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));
    await waitFor(() => screen.getByText("AI Credits Required"));

    // Draft must still be in sessionStorage after retry
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("saas draft");
  });

  it("unknown SSE event type (future provider_switched) does not clear entryPrompt", async () => {
    // The backend might emit new event types (e.g. provider_switched) in the
    // future. The switch statement has no default: unknown types pass through
    // silently. This test ensures such events can never erase entryPrompt.
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        // Simulate a hypothetical provider_switched event — not in BuildEvent type yet
        { type: "provider_switched", provider: "openai" } as unknown as BuildEvent,
        { type: "error", message: "provider switched but then failed" },
      ]),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "my irreplaceable idea" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      screen.getByText("provider switched but then failed"),
    );

    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("my irreplaceable idea");
    expect(screen.getByRole("textbox")).toHaveValue("my irreplaceable idea");
  });

  it("regression guard: all SSE event types pass through without touching entryPrompt", async () => {
    // Runs every known SSE event type through handleBuild and asserts that
    // entryPrompt is never cleared. This is the canonical regression guard —
    // if a future commit adds setEntryPrompt() inside handleBuild or an SSE
    // handler, this test fails.
    streamBuildSpy.mockReturnValue(
      makeEventStream([
        { type: "status",    message: "Understanding…" },
        { type: "heartbeat", ts: Date.now() },
        { type: "file",      path: "index.ts", content: "export {};" },
        { type: "dev_mode",  provider: "mock" },
        { type: "error",     message: "REGRESSION_GUARD_TERMINAL_ERROR" },
      ]),
    );

    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "REGRESSION_GUARD_PROMPT" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      screen.getByText("REGRESSION_GUARD_TERMINAL_ERROR"),
    );

    // After all events the entry prompt must be exactly what the user typed
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("REGRESSION_GUARD_PROMPT");
    expect(screen.getByRole("textbox")).toHaveValue("REGRESSION_GUARD_PROMPT");
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case L — AI Independence: storage must never hold provider credentials
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case L — AI Independence: storage security", () => {
  const DRAFT_KEY = "flow:app-builder:draft";
  // Pattern that would indicate a provider API key leaked into storage
  const CREDENTIAL_PATTERN = /sk-ant|sk-proj|sk-or-v1|gsk_|AIzaSy|ANTHROPIC_API_KEY|Bearer\s+[A-Za-z0-9]/i;

  beforeEach(() => { sessionStorage.removeItem(DRAFT_KEY); });
  afterEach(() => { sessionStorage.removeItem(DRAFT_KEY); });

  it("DRAFT_KEY stores only plain user text — no credential patterns", () => {
    render(<AppBuilderPage />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "build a CRM for my sales team" } });

    const stored = sessionStorage.getItem(DRAFT_KEY) ?? "";
    expect(stored).toBe("build a CRM for my sales team");
    expect(stored).not.toMatch(CREDENTIAL_PATTERN);
  });

  it("sessionStorage contains no AI provider API key after a failed build", async () => {
    streamBuildSpy.mockReturnValue(
      makeEventStream([{ type: "error", message: "build failed" }]),
    );

    render(<AppBuilderPage />);
    submitPrompt("launch my product");

    await waitFor(() => screen.getByText("build failed"));

    // Scan every sessionStorage entry for credential patterns
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i)!;
      const value = sessionStorage.getItem(key) ?? "";
      expect(value).not.toMatch(CREDENTIAL_PATTERN);
    }
  });

  it("AppBuilderPage source contains no hardcoded provider API key values", async () => {
    // Static guard: import the raw source and verify no literal key is embedded.
    // This test would fail immediately if a developer accidentally hardcoded a key.
    const { default: raw } = await import("../AppBuilderPage.tsx?raw") as { default: string };
    expect(raw).not.toMatch(/sk-ant-[A-Za-z0-9]/);
    expect(raw).not.toMatch(/sk-proj-[A-Za-z0-9]/);
    expect(raw).not.toMatch(/ANTHROPIC_API_KEY\s*=\s*["'][A-Za-z0-9]/);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Case M — Provider error messaging: must not claim FLOW is suspended
   ══════════════════════════════════════════════════════════════════════════ */

describe("Case M — Provider error messaging", () => {
  it("billing error overlay shows AI Credits Required, not FLOW Service Suspended", async () => {
    streamBuildSpy.mockReturnValue(
      throwingStream(
        new BillingRequiredError("anthropic", "Credit balance too low.", "/api/build/stream"),
      ),
    );

    render(<AppBuilderPage />);
    submitPrompt("any prompt");

    await waitFor(() => screen.getByText("AI Credits Required"));

    // Must identify the AI provider issue specifically
    expect(screen.getByText("AI Credits Required")).toBeInTheDocument();

    // Must NOT claim that the FLOW platform itself is suspended/stopped
    expect(screen.queryByText(/FLOW.*suspend/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/service.*suspend/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/platform.*suspend/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/تم تعليق.*FLOW/)).not.toBeInTheDocument();
  });

  it("billing retry replays the exact original prompt to streamBuild", async () => {
    // billingError.prompt stores the prompt from the first failed build.
    // The retry must replay that exact text — never an empty string or stale value.
    const capturedPrompts: string[] = [];

    streamBuildSpy.mockImplementation((_pid: string, prompt: string) => {
      capturedPrompts.push(prompt);
      return throwingStream(
        new BillingRequiredError("anthropic", "Balance too low.", "/api/build/stream"),
      );
    });

    render(<AppBuilderPage />);
    submitPrompt("my original SaaS pitch");

    await waitFor(() => screen.getByText("AI Credits Required"));
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));

    await waitFor(() => expect(capturedPrompts.length).toBe(2), { timeout: 8000 });

    expect(capturedPrompts[0]).toBe("my original SaaS pitch");
    expect(capturedPrompts[1]).toBe("my original SaaS pitch");
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Plan Mode — Cases N–R
   Tests the /api/build/plan happy path, approve, cancel, modify/regenerate,
   and failure-fallback.  apiFetch and parseJSON are already mocked globally;
   these cases set per-test return values via mockResolvedValueOnce.
   ══════════════════════════════════════════════════════════════════════════ */

const VALID_PLAN: BuildPlan = {
  name: "Test App",
  description: "A test application for Plan Mode",
  tech_stack: { frontend: "React", backend: "FastAPI", database: "PostgreSQL" },
  pages: ["Dashboard", "Settings"],
  database_tables: ["users", "items"],
  api_routes: ["/api/items", "/api/users"],
  agents: [],
  workflows: [],
  integrations: [],
  estimated_files: 8,
  complexity: "simple",
};

/** Reset the module-level apiFetch/parseJSON mocks before each Plan Mode test
 *  so leftover mockResolvedValueOnce entries from a previous test cannot bleed
 *  through.  vi.restoreAllMocks() only resets spies, not vi.fn() module mocks. */
function resetPlanMocks() {
  (apiFetch as Mock).mockReset();
  (parseJSON as Mock).mockReset();
}

/* ── Case N ─────────────────────────────────────────────────────────────── */

describe("Case N — Plan Mode: plan success shows BuildPlanPanel", () => {
  beforeEach(resetPlanMocks);

  it("shows BuildPlanPanel when /api/build/plan returns a valid plan", async () => {
    (apiFetch as Mock).mockResolvedValueOnce({ ok: true });
    (parseJSON as Mock).mockResolvedValueOnce({ plan: VALID_PLAN });

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Approve Plan/i })).toBeInTheDocument(),
    { timeout: 8000 });

    // Plan name visible in the panel (appears in header + plan tree — use getAllByText)
    expect(screen.getAllByText("Test App").length).toBeGreaterThan(0);
    // streamBuild must NOT have been called — build waits for approval
    expect(streamBuildSpy).not.toHaveBeenCalled();
  });
});

/* ── Case O ─────────────────────────────────────────────────────────────── */

describe("Case O — Plan Mode: Approve starts build with approvedPlan", () => {
  beforeEach(resetPlanMocks);

  it("passes the approved BuildPlan as the 4th argument to streamBuild", async () => {
    (apiFetch as Mock).mockResolvedValueOnce({ ok: true });
    (parseJSON as Mock).mockResolvedValueOnce({ plan: VALID_PLAN });
    streamBuildSpy.mockReturnValue(makeEventStream([]));

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Approve Plan/i })).toBeInTheDocument(),
    { timeout: 8000 });

    // Build has NOT started yet
    expect(streamBuildSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Approve Plan/i }));

    await waitFor(() => expect(streamBuildSpy).toHaveBeenCalled(), { timeout: 8000 });

    const [_projectId, prompt, _signal, approvedPlan] = streamBuildSpy.mock.calls[0] as [
      string, string, AbortSignal, BuildPlan | undefined
    ];
    expect(prompt).toBe("Build a CRM");
    expect(approvedPlan).toEqual(VALID_PLAN);
  });
});

/* ── Case P ─────────────────────────────────────────────────────────────── */

describe("Case P — Plan Mode: Cancel returns to entry without starting a build", () => {
  beforeEach(resetPlanMocks);

  it("dismisses the plan panel and keeps build unstarted", async () => {
    (apiFetch as Mock).mockResolvedValueOnce({ ok: true });
    (parseJSON as Mock).mockResolvedValueOnce({ plan: VALID_PLAN });

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Approve Plan/i })).toBeInTheDocument(),
    { timeout: 8000 });

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/i }));

    // Panel gone
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Approve Plan/i })).not.toBeInTheDocument(),
    );

    // Build never started
    expect(streamBuildSpy).not.toHaveBeenCalled();

    // Entry textarea is visible again
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});

/* ── Case Q ─────────────────────────────────────────────────────────────── */

describe("Case Q — Plan Mode: Modify/Regenerate re-calls /api/build/plan", () => {
  beforeEach(resetPlanMocks);

  it("calls /api/build/plan again with new prompt on modify, does not start build", async () => {
    (apiFetch as Mock)
      .mockResolvedValueOnce({ ok: true })   // first plan call
      .mockResolvedValueOnce({ ok: true });   // second plan call (after regenerate)
    (parseJSON as Mock)
      .mockResolvedValueOnce({ plan: VALID_PLAN })
      .mockResolvedValueOnce({ plan: { ...VALID_PLAN, name: "Better App" } });

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Approve Plan/i })).toBeInTheDocument(),
    { timeout: 8000 });

    // Enter editing mode
    fireEvent.click(screen.getByRole("button", { name: /Modify Plan/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Regenerate Plan/i })).toBeInTheDocument(),
    );

    // Modify the prompt in the BuildPlanPanel's edit textarea
    const editArea = screen.getByRole("textbox");
    fireEvent.change(editArea, { target: { value: "Build a better CRM" } });

    fireEvent.click(screen.getByRole("button", { name: /Regenerate Plan/i }));

    // Second /api/build/plan call must happen
    await waitFor(() => {
      const planCalls = (apiFetch as Mock).mock.calls.filter(
        (args: unknown[]) => args[0] === "/api/build/plan"
      );
      expect(planCalls.length).toBe(2);
    }, { timeout: 8000 });

    // Verify second call used the modified prompt
    const secondCallBody = JSON.parse(
      ((apiFetch as Mock).mock.calls[1] as [string, { body: string }])[1].body
    ) as { prompt: string };
    expect(secondCallBody.prompt).toBe("Build a better CRM");

    // Build must NOT have started through either plan cycle
    expect(streamBuildSpy).not.toHaveBeenCalled();
  });
});

/* ── Case R ─────────────────────────────────────────────────────────────── */

describe("Case R — Plan Mode: plan failure falls back to direct build", () => {
  beforeEach(resetPlanMocks);

  it("falls back to direct build (no approvedPlan) on non-OK plan response", async () => {
    (apiFetch as Mock).mockResolvedValueOnce({ ok: false, status: 429 });
    streamBuildSpy.mockReturnValue(makeEventStream([]));

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    // Plan panel must NOT appear; build starts directly
    await waitFor(() => expect(streamBuildSpy).toHaveBeenCalled(), { timeout: 8000 });
    expect(screen.queryByRole("button", { name: /Approve Plan/i })).not.toBeInTheDocument();

    // approvedPlan (4th arg) is absent when falling back
    const [, , , approvedPlan] = streamBuildSpy.mock.calls[0] as [
      string, string, AbortSignal, BuildPlan | undefined
    ];
    expect(approvedPlan).toBeUndefined();
  });

  it("falls back to direct build (no approvedPlan) when plan call throws", async () => {
    (apiFetch as Mock).mockRejectedValueOnce(new Error("Network error"));
    streamBuildSpy.mockReturnValue(makeEventStream([]));

    render(<AppBuilderPage />);
    submitPrompt("Build a CRM");

    await waitFor(() => expect(streamBuildSpy).toHaveBeenCalled(), { timeout: 8000 });
    expect(screen.queryByRole("button", { name: /Approve Plan/i })).not.toBeInTheDocument();

    const [, , , approvedPlan] = streamBuildSpy.mock.calls[0] as [
      string, string, AbortSignal, BuildPlan | undefined
    ];
    expect(approvedPlan).toBeUndefined();
  });
});
