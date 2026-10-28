import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StudyContentWorkflow } from "./StudyContentWorkflow";
import { apiFetch } from "../../utils/api";
const org = vi.hoisted(() => ({ currentOrgId: "org-a" as string | null }));
vi.mock("../../contexts/OrgContext", () => ({ useOrg: () => org }));
vi.mock("../../utils/api", () => ({ apiFetch: vi.fn() }));
const lesson = { slug: "lesson", title: "درس تجريبي", description: "شرح ومثال" };
const content = { voiceover: "النص", tiktok: "وصف تيك توك", instagram: "وصف إنستغرام", youtube: "وصف يوتيوب", video_url: "https://media.example.com/final.mp4" };
const root = "/api/study-library/workflows";
function json(data: unknown, status = 200) { return new Response(JSON.stringify(data), { status }); }
function mockWorkflow(state: "draft" | "reviewed" | "handed_off" = "draft") {
  vi.mocked(apiFetch).mockImplementation(async path => {
    if (path.endsWith("/connections")) return json({ platforms: [{ platform: "youtube", implemented: false, configured: false, accounts: [] }] });
    if (path.endsWith("/posts")) return json({ posts: [{ id: "post-id", platform: "tiktok", status: "draft" }] });
    return json({ workflows: [{ id: "work-id", title: lesson.title, lesson_slug: "lesson", revision: 2, state, content }] });
  });
}
async function open() {
  render(<StudyContentWorkflow lessons={[lesson]} />);
  fireEvent.click(screen.getByText("إدارة المحتوى · ربط المكتبة والمنصات"));
  await screen.findByText("من المكتبة إلى المنصات");
}
beforeEach(() => { vi.resetAllMocks(); org.currentOrgId = "org-a"; });
describe("linked study workflow", () => {
  it("requires a workspace without requesting workflow data", async () => {
    org.currentOrgId = null; render(<StudyContentWorkflow lessons={[lesson]} />);
    expect(screen.getByText(/اختر مساحة عمل أولًا/)).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });
  it("shows unsupported providers truthfully and requires saving before approval", async () => {
    mockWorkflow(); await open();
    await screen.findByText("مزوّد النشر غير متاح بعد");
    fireEvent.change(screen.getByLabelText("مسار محفوظ"), { target: { value: "work-id" } });
    expect(screen.getByRole("button", { name: "اعتماد هذه النسخة" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("راجعت الملخص والنص والفيديو وحقوق استخدامه"));
    expect(screen.getByRole("button", { name: "اعتماد هذه النسخة" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("وصف TikTok"), { target: { value: "تعديل جديد" } });
    expect(screen.getByRole("button", { name: "اعتماد هذه النسخة" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "إنشاء مسودات في ناشر المنصات" })).toBeDisabled();
  });
  it("hands off exactly the reviewed revision without calling publish", async () => {
    mockWorkflow("reviewed"); await open(); await screen.findByLabelText("مسار محفوظ");
    fireEvent.change(screen.getByLabelText("مسار محفوظ"), { target: { value: "work-id" } });
    fireEvent.click(screen.getByRole("button", { name: "إنشاء مسودات في ناشر المنصات" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith(`${root}/work-id/handoff`, { method: "POST", body: JSON.stringify({ revision: 2 }) }));
    expect(vi.mocked(apiFetch).mock.calls.some(([path]) => path.includes("/publish"))).toBe(false);
  });
  it("reads the real draft status after handoff", async () => {
    mockWorkflow("handed_off"); await open(); await screen.findByLabelText("مسار محفوظ");
    fireEvent.change(screen.getByLabelText("مسار محفوظ"), { target: { value: "work-id" } });
    fireEvent.click(screen.getByRole("button", { name: "تحديث حالة مسودات الناشر" }));
    await screen.findByText(/مسودة، لم تُنشر/);
    expect(apiFetch).toHaveBeenCalledWith(`${root}/work-id/posts`, undefined);
  });
});

it("starts account OAuth with an explicit top-level POST rather than a third-party cookie fetch", async () => {
  vi.mocked(apiFetch).mockImplementation(async path => {
    if (path.endsWith("/connections")) return json({ platforms: [{ platform: "tiktok", implemented: true, configured: true, accounts: [] }] });
    if (path.endsWith("/connect")) return json({ auth_url: "https://api.example/api/social/accounts/tiktok/authorize", ticket: "a".repeat(32) });
    return json({ workflows: [] });
  });
  await open(); fireEvent.click(await screen.findByRole("button", { name: "ربط حساب TikTok" }));
  const submit = await screen.findByRole("button", { name: /متابعة ربط TikTok/ });
  const form = submit.closest("form");
  expect(form).toHaveAttribute("method", "post");
  expect(form).toHaveAttribute("target", "_blank");
  expect(form).toHaveAttribute("rel", "noopener");
  expect(form).toHaveAttribute("action", "https://api.example/api/social/accounts/tiktok/authorize");
  expect(form?.querySelector('input[name="ticket"]')).toHaveValue("a".repeat(32));
});
