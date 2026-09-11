/**
 * Business Lab — frontend smoke tests.
 * Tests the page renders and the service mock integration.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BusinessLabPage } from "../BusinessLabPage";

// Mock the service
vi.mock("../services/businessService", () => ({
  businessService: {
    listPlans:      vi.fn().mockResolvedValue([]),
    createPlan:     vi.fn().mockResolvedValue({
      id: "plan-1", title: "Test Plan", idea_raw: "Test idea",
      industry: "Tech", stage: "IDEA", status: "DRAFT",
      readiness_score: null, workflow_run_id: null,
      created_at: "2026-01-01", updated_at: "2026-01-01",
    }),
    getPlan:        vi.fn().mockResolvedValue({
      plan: {
        id: "plan-1", title: "Test Plan", idea_raw: "Test idea",
        industry: "Tech", stage: "IDEA", status: "COMPLETED",
        readiness_score: 72, workflow_run_id: null,
        created_at: "2026-01-01", updated_at: "2026-01-01",
      },
      sections: [
        {
          id: "s1", plan_id: "plan-1", section_key: "intake",
          title: "فكرة العمل", content: "محتوى القسم",
          status: "COMPLETED", agent_name: "idea_intake",
          model_used: null, tokens_used: 100, elapsed_ms: 2000,
          retry_count: 0, error_msg: null, updated_at: "2026-01-01",
        },
      ],
      facts: [
        {
          id: "f1", plan_id: "plan-1", fact_key: "problem_statement",
          value: "عدم وجود حل بسيط", source_type: "USER",
          source_url: null, source_note: null,
          status: "UNVERIFIED", confidence: 0.8,
          section: "intake", created_by: "idea_intake", created_at: "2026-01-01",
        },
      ],
      competitors: [],
      score: {
        overall_score: 72, breakdown: { idea_clarity: 8, market_evidence: 14 },
        evidence_count: 5, assumption_count: 2, missing_count: 1,
        computed_at: "2026-01-01",
      },
    }),
    retrySections:    vi.fn().mockResolvedValue({ message: "ok" }),
    cancelPlan:       vi.fn().mockResolvedValue({ message: "ok" }),
    recomputeScore:   vi.fn().mockResolvedValue({ overall_score: 75 }),
    exportPlan:       vi.fn().mockResolvedValue(undefined),
    deletePlan:       vi.fn().mockResolvedValue(undefined),
    streamStatus:     vi.fn().mockReturnValue(() => {}),
  },
}));

describe("BusinessLabPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the empty state", async () => {
    render(<BusinessLabPage />);
    await screen.findByText(/مختبر الأعمال/);
    expect(screen.getByText(/اختر خطة أو أنشئ واحدة جديدة/)).toBeInTheDocument();
  });

  it("shows 'New Plan' button", async () => {
    render(<BusinessLabPage />);
    expect(await screen.findByText(/\+ خطة جديدة/)).toBeInTheDocument();
  });

  it("opens new plan form when clicking the button", async () => {
    render(<BusinessLabPage />);
    const btn = await screen.findByText(/\+ خطة جديدة/);
    fireEvent.click(btn);
    expect(screen.getByText(/خطة عمل جديدة/)).toBeInTheDocument();
    expect(screen.getByText(/ابدأ التحليل/)).toBeInTheDocument();
  });

  it("shows validation error for short idea", async () => {
    render(<BusinessLabPage />);
    fireEvent.click(await screen.findByText(/\+ خطة جديدة/));
    fireEvent.click(screen.getByText(/ابدأ التحليل/));
    await waitFor(() =>
      expect(screen.getByText(/صف فكرتك بجملتين على الأقل/)).toBeInTheDocument()
    );
  });

  it("loads plan list on mount", async () => {
    const { businessService } = await import("../services/businessService");
    render(<BusinessLabPage />);
    await waitFor(() => expect(businessService.listPlans).toHaveBeenCalledOnce());
  });

  it("shows plan detail when a plan is loaded", async () => {
    const { businessService } = await import("../services/businessService");
    // Simulate a plan in the list
    vi.mocked(businessService.listPlans).mockResolvedValue([{
      id: "plan-1", title: "Test Plan", idea_raw: "Test idea",
      industry: "Tech", stage: "IDEA", status: "COMPLETED",
      readiness_score: 72, workflow_run_id: null,
      created_at: "2026-01-01", updated_at: "2026-01-01",
    }]);

    render(<BusinessLabPage />);
    const item = await screen.findByText("Test Plan");
    fireEvent.click(item);

    await waitFor(() => expect(businessService.getPlan).toHaveBeenCalledWith("plan-1"));
    await screen.findByText(/نظرة عامة/);
  });

  it("shows score ring when score is available", async () => {
    const { businessService } = await import("../services/businessService");
    vi.mocked(businessService.listPlans).mockResolvedValue([{
      id: "plan-1", title: "Test Plan", idea_raw: "Test idea",
      industry: null, stage: "IDEA", status: "COMPLETED",
      readiness_score: 72, workflow_run_id: null,
      created_at: "2026-01-01", updated_at: "2026-01-01",
    }]);

    render(<BusinessLabPage />);
    fireEvent.click(await screen.findByText("Test Plan"));

    // After load, score ring should show
    await waitFor(() => expect(screen.getByText("72")).toBeInTheDocument());
  });
});
