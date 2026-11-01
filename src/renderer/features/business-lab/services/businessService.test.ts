import { beforeEach, describe, expect, it, vi } from "vitest";
import { businessService } from "./businessService";
import { apiFetch } from "../../../shared/utils/api";
vi.mock("../../../shared/utils/api", () => ({ API: "https://api.example.test", apiFetch: vi.fn() }));
describe("Business Lab requests", () => {
  beforeEach(() => vi.clearAllMocks());
  it("uses shared authenticated requests for creating plans", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ id: "p" }), { status: 201 }));
    await businessService.createPlan({ idea_raw: "A valid business idea" });
    expect(apiFetch).toHaveBeenCalledWith("/api/business/plans", expect.objectContaining({ method: "POST", body: JSON.stringify({ idea_raw: "A valid business idea" }) }));
  });
  it("shows readable validation errors instead of raw JSON", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ detail: [{ msg: "too long" }] }), { status: 422 }));
    await expect(businessService.createPlan({ idea_raw: "x" })).rejects.toThrow("10 إلى 4000");
  });
  it("does not display server internals for failures", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ detail: "private database exception" }), { status: 500 }));
    await expect(businessService.listPlans()).rejects.toThrow("تعذر إكمال الطلب (500)");
  });
});
