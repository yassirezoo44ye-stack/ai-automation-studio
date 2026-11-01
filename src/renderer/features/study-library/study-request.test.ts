import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../utils/api";
import { studyFetch } from "./study-request";

vi.mock("../../utils/api", () => ({ apiFetch: vi.fn() }));
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });
describe("study request cancellation", () => {
  it("explains a connection timeout instead of leaving a button busy forever", async () => {
    vi.useFakeTimers();
    vi.mocked(apiFetch).mockImplementation((_path, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const result = expect(studyFetch("/api/study-library/catalog")).rejects.toThrow(/استغرق الاتصال وقتًا طويلًا/);
    await vi.advanceTimersByTimeAsync(30000);
    await result;
  });
  it("cancels an in-flight request when its page is left", async () => {
    const parent = new AbortController();
    vi.mocked(apiFetch).mockImplementation((_path, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const result = expect(studyFetch("/api/study-library/catalog", { signal: parent.signal })).rejects.toMatchObject({ name: "AbortError" });
    parent.abort(); await result;
  });
});
