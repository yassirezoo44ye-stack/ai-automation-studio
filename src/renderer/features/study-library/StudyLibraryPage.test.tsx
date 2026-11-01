import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StudyLibraryPage } from "./StudyLibraryPage";
import { apiFetch } from "../../utils/api";

const auth = vi.hoisted(() => ({ user: null as null | { id: string; email: string; email_verified: boolean } }));
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../contexts/OrgContext", () => ({ useOrg: () => ({ currentOrgId: null }) }));
vi.mock("../../utils/api", () => ({ API: "", apiFetch: vi.fn() }));
const lesson = { slug: "fractions", title: "الكسور ببساطة", subject: "math", description: "مثال وتمارين للكسور.", pages: 2, published_at: "2026-10-26T08:00:00Z" };
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }
function respond(access: unknown = { has_access: false, is_admin: false }, status = 200) {
  vi.mocked(apiFetch).mockImplementation(async path => path.includes("/catalog")
    ? json({ lessons: [lesson], checkout_url: "https://payhip.com/b/Study42" })
    : path.endsWith("/access") ? json(access, status) : json({}, 403));
}
beforeEach(() => { vi.resetAllMocks(); auth.user = null; window.history.replaceState(null, "", "/study-library"); });

describe("Study Library purchase boundary", () => {
  it("preserves an administrator's open upload form while access is rechecked", async () => {
    auth.user = { id: "admin", email: "admin@example.com", email_verified: true };
    respond({ has_access: true, is_admin: true }); render(<StudyLibraryPage />);
    fireEvent.click(await screen.findByText("إدارة المكتبة · إضافة ملخص"));
    fireEvent.change(screen.getByLabelText("العنوان"), { target: { value: "ملخص لم أحفظه بعد" } });
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    await screen.findByText("تم التحقق: صلاحية دخول المكتبة فعّالة.");
    expect(screen.getByLabelText("العنوان")).toHaveValue("ملخص لم أحفظه بعد");
    expect(screen.getByLabelText("العنوان")).toBeVisible();
  });

  it("clears the lesson link, text query and subject when showing all summaries", async () => {
    window.history.replaceState(null, "", "/study-library?lesson=fractions&q=كسور");
    respond(); render(<StudyLibraryPage />); await screen.findByText(lesson.title);
    fireEvent.click(screen.getByRole("button", { name: "الرياضيات" }));
    fireEvent.click(screen.getByRole("button", { name: "عرض كل الملخصات" }));
    await waitFor(() => {
      const calls = vi.mocked(apiFetch).mock.calls.filter(([path]) => path.includes("/catalog"));
      const params = new URL(calls.at(-1)![0], "https://test.local").searchParams;
      expect(params.get("q")).toBe(""); expect(params.has("slug")).toBe(false); expect(params.has("subject")).toBe(false);
    });
    expect(window.location.search).toBe("");
    expect(screen.getByRole("textbox", { name: "ابحث عن ملخص" })).toHaveValue("");
  });

  it("confirms rechecking access and explains why next is disabled", async () => {
    auth.user = { id: "buyer", email: "reader@example.com", email_verified: true };
    respond({ has_access: true, is_admin: false }); render(<StudyLibraryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "إعادة التحقق" }));
    await screen.findByText("تم التحقق: صلاحية دخول المكتبة فعّالة.");
    expect(screen.getByRole("button", { name: "التالي" })).toBeDisabled();
    expect(screen.getByText(/لا توجد صفحة تالية/)).toBeInTheDocument();
  });
  it("clears a search with no matches and restores the full catalog", async () => {
    vi.mocked(apiFetch).mockImplementation(async path => {
      const q = new URL(path, "https://test.local").searchParams.get("q");
      return json({ lessons: q ? [] : [lesson], checkout_url: null });
    });
    render(<StudyLibraryPage />);
    await screen.findByText(lesson.title);
    fireEvent.change(screen.getByRole("textbox", { name: "ابحث عن ملخص" }), { target: { value: "التجاره" } });
    fireEvent.click(screen.getByRole("button", { name: /^بحث$/ }));
    fireEvent.click(await screen.findByRole("button", { name: "مسح البحث وعرض كل الملخصات" }));
    await screen.findByText(lesson.title);
    expect(screen.getByRole("textbox", { name: "ابحث عن ملخص" })).toHaveValue("");
  });
  it("shows the public catalog and sign-in without allowing anonymous downloads", async () => {
    respond(); const signIn = vi.fn(); render(<StudyLibraryPage onSignIn={signIn} />);
    await screen.findByText(lesson.title);
    expect(screen.getByRole("button", { name: "يتطلب دخول المكتبة" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "تسجيل الدخول" }));
    expect(signIn).toHaveBeenCalledOnce();
    expect(vi.mocked(apiFetch).mock.calls.every(([p]) => !p.endsWith("/access"))).toBe(true);
  });

  it("offers checkout to a verified nonbuyer and keeps file controls locked", async () => {
    auth.user = { id: "buyer", email: "reader@example.com", email_verified: true }; respond();
    render(<StudyLibraryPage />);
    expect(await screen.findByRole("link", { name: /شراء دخول المكتبة/ })).toHaveAttribute("href", "https://payhip.com/b/Study42");
    expect(screen.getByRole("button", { name: "يتطلب دخول المكتبة" })).toBeDisabled();
  });

  it("does not treat an access-check failure as a reason to purchase again", async () => {
    auth.user = { id: "buyer", email: "reader@example.com", email_verified: true }; respond({}, 503);
    render(<StudyLibraryPage />);
    await screen.findByText(/تعذّر التحقق من صلاحية الدخول الآن/);
    expect(screen.queryByRole("link", { name: /شراء دخول المكتبة/ })).not.toBeInTheDocument();
  });

  it("requires email verification before looking up a purchase", async () => {
    auth.user = { id: "buyer", email: "reader@example.com", email_verified: false }; respond();
    render(<StudyLibraryPage />); await screen.findByText(lesson.title);
    expect(screen.getByText(/وثّق بريد حسابك أولًا/)).toBeInTheDocument();
    expect(vi.mocked(apiFetch).mock.calls.every(([p]) => !p.endsWith("/access"))).toBe(true);
  });

  it("rechecks server permission on download and relocks a refunded purchase", async () => {
    auth.user = { id: "buyer", email: "reader@example.com", email_verified: true };
    respond({ has_access: true, is_admin: false }); render(<StudyLibraryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "تنزيل الملخص ↓" }));
    await screen.findByText(/لم تتأكد صلاحية الشراء/);
    expect(screen.getByRole("button", { name: "يتطلب دخول المكتبة" })).toBeDisabled();
    expect(apiFetch).toHaveBeenCalledWith("/api/study-library/lessons/fractions/download", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("passes the selected subject and search query to the catalog", async () => {
    respond(); render(<StudyLibraryPage />); await screen.findByText(lesson.title);
    fireEvent.click(screen.getByRole("button", { name: "الرياضيات" }));
    fireEvent.change(screen.getByRole("textbox", { name: "ابحث عن ملخص" }), { target: { value: "كسور" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([p]) => {
      const params = new URL(p, "http://test").searchParams;
      return params.get("subject") === "math" && params.get("q") === "كسور";
    })).toBe(true));
  });
});
