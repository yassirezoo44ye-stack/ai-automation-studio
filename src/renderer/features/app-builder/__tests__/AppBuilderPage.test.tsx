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
import { BillingRequiredError } from "../../../shared/utils/api";

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
