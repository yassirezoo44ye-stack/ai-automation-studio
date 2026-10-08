import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NewProjectPage } from "../NewProjectPage";
import { APIError } from "../../../shared/utils/api";

/* ── Stable mock references (vi.hoisted ensures they exist before module init) */
const { mockSetPage, mockSetActiveProject } = vi.hoisted(() => ({
  mockSetPage:          vi.fn(),
  mockSetActiveProject: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../../contexts/app", () => ({
  useAppContext: () => ({
    setPage:          mockSetPage,
    setActiveProject: mockSetActiveProject,
  }),
}));

vi.mock("../../../icons", () => ({
  Icons: new Proxy({} as Record<string, () => null>, { get: () => () => null }),
}));

import * as builderService from "../../app-builder/services/builderService";
vi.mock("../../app-builder/services/builderService", () => ({
  createProject: vi.fn(),
}));

const VALID_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

function mockProject(id = VALID_UUID) {
  return { id, name: "Test", description: "", status: "active", created_at: "", updated_at: "" };
}

function makeApiError(status: number, cause: string) {
  return new APIError(cause, { url: "/api/projects", status, contentType: "application/json", probableCause: cause });
}

beforeEach(() => {
  vi.mocked(builderService.createProject).mockResolvedValue(mockProject() as never);
  vi.mocked(builderService.createProject).mockClear();
  mockSetPage.mockClear();
  mockSetActiveProject.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Rendering ─────────────────────────────────────────────────────────────────

describe("NewProjectPage — rendering", () => {
  it("renders all 5 project type cards", () => {
    render(<NewProjectPage />);
    // t() returns key — card titles are their i18n key strings
    expect(screen.getByText("newProject.types.business.title")).toBeInTheDocument();
    expect(screen.getByText("newProject.types.application.title")).toBeInTheDocument();
    expect(screen.getByText("newProject.types.saas.title")).toBeInTheDocument();
    expect(screen.getByText("newProject.types.design.title")).toBeInTheDocument();
    expect(screen.getByText("newProject.types.automation.title")).toBeInTheDocument();
  });

  it("renders no error message initially", () => {
    render(<NewProjectPage />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

// ── Business Lab (flat route, no project creation) ───────────────────────────

describe("NewProjectPage — business card", () => {
  it("calls setPage('business-lab') without createProject", async () => {
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.business.title").closest("button")!);
    expect(builderService.createProject).not.toHaveBeenCalled();
    expect(mockSetPage).toHaveBeenCalledWith("business-lab");
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });
});

// ── Successful creation ───────────────────────────────────────────────────────

describe("NewProjectPage — successful project creation", () => {
  it("application card: creates project then calls setActiveProject(uuid, 'build')", async () => {
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(mockSetActiveProject).toHaveBeenCalledWith(VALID_UUID, "build"));
    expect(builderService.createProject).toHaveBeenCalledWith(
      "newProject.types.application.title",
      "newProject.types.application.desc",
    );
    expect(mockSetPage).not.toHaveBeenCalled();
  });

  it("saas card: creates project then calls setActiveProject(uuid, 'build')", async () => {
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.saas.title").closest("button")!);
    await waitFor(() => expect(mockSetActiveProject).toHaveBeenCalledWith(VALID_UUID, "build"));
  });

  it("design card: creates project then calls setActiveProject(uuid, 'design')", async () => {
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.design.title").closest("button")!);
    await waitFor(() => expect(mockSetActiveProject).toHaveBeenCalledWith(VALID_UUID, "design"));
  });

  it("automation card: creates project then calls setActiveProject(uuid, 'automation')", async () => {
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.automation.title").closest("button")!);
    await waitFor(() => expect(mockSetActiveProject).toHaveBeenCalledWith(VALID_UUID, "automation"));
  });
});

// ── UUID validation ───────────────────────────────────────────────────────────

describe("NewProjectPage — UUID validation", () => {
  it("does not call setActiveProject when project.id is empty", async () => {
    vi.mocked(builderService.createProject).mockResolvedValue(mockProject("") as never);
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });

  it("does not call setActiveProject when project.id is not a valid UUID", async () => {
    vi.mocked(builderService.createProject).mockResolvedValue(mockProject("not-a-uuid") as never);
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });
});

// ── Error handling ────────────────────────────────────────────────────────────

describe("NewProjectPage — error handling", () => {
  it("shows inline error on 401, does not navigate", async () => {
    vi.mocked(builderService.createProject).mockRejectedValue(makeApiError(401, "Unauthorized"));
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Unauthorized");
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });

  it("shows inline error on 403, does not navigate", async () => {
    vi.mocked(builderService.createProject).mockRejectedValue(makeApiError(403, "Forbidden"));
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });

  it("shows inline error on 422, does not navigate", async () => {
    vi.mocked(builderService.createProject).mockRejectedValue(makeApiError(422, "Validation error"));
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });

  it("shows inline error on network failure (TypeError), does not navigate", async () => {
    vi.mocked(builderService.createProject).mockRejectedValue(new TypeError("Failed to fetch"));
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to fetch");
    expect(mockSetActiveProject).not.toHaveBeenCalled();
  });

  it("re-enables cards after an error", async () => {
    vi.mocked(builderService.createProject).mockRejectedValue(new Error("Boom"));
    render(<NewProjectPage />);
    const btn = screen.getByText("newProject.types.application.title").closest("button")!;
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(btn).not.toBeDisabled();
  });
});

// ── Loading / disabled state ──────────────────────────────────────────────────

describe("NewProjectPage — loading state", () => {
  it("shows 'Creating…' on the clicked card while request is in flight", async () => {
    let resolve!: (v: unknown) => void;
    vi.mocked(builderService.createProject).mockReturnValue(
      new Promise(r => { resolve = r; }) as never,
    );
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByText("Creating…")).toBeInTheDocument());
    // Clean up — resolve to avoid unhandled promise warning
    resolve(mockProject());
  });

  it("disables all cards while one is being created", async () => {
    let resolve!: (v: unknown) => void;
    vi.mocked(builderService.createProject).mockReturnValue(
      new Promise(r => { resolve = r; }) as never,
    );
    render(<NewProjectPage />);
    fireEvent.click(screen.getByText("newProject.types.application.title").closest("button")!);
    await waitFor(() => expect(screen.getByText("Creating…")).toBeInTheDocument());
    const buttons = screen.getAllByRole("button");
    for (const btn of buttons) {
      expect(btn).toBeDisabled();
    }
    resolve(mockProject());
  });
});

// ── Duplicate-click protection ────────────────────────────────────────────────

describe("NewProjectPage — duplicate click protection", () => {
  it("a second click while creating does not call createProject twice", async () => {
    let resolve!: (v: unknown) => void;
    vi.mocked(builderService.createProject).mockReturnValue(
      new Promise(r => { resolve = r; }) as never,
    );
    render(<NewProjectPage />);
    const btn = screen.getByText("newProject.types.application.title").closest("button")!;
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("Creating…")).toBeInTheDocument());
    // Button must be disabled — that's the protection contract.
    expect(btn).toBeDisabled();
    expect(builderService.createProject).toHaveBeenCalledTimes(1);
    resolve(mockProject());
  });
});
