import { loadStudyItems } from "../features/feed/services/studyFeedService";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach } from "vitest";
import { FeedPage } from "../features/feed/FeedPage";
import { loadFeedItems } from "../features/feed/services/feedService";
import type { FeedItem } from "../features/feed/types/feed.types";
vi.mock("../features/feed/services/studyFeedService", () => ({ loadStudyItems: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../features/feed/services/feedService", () => ({ loadFeedItems: vi.fn(), toggleLike: vi.fn(), toggleSave: vi.fn() }));
vi.mock("../features/feed/components/FeedCard", () => ({ FeedCard: ({ item }: { item: FeedItem }) => <article>{item.title}</article> }));
const lesson: FeedItem = { id: "study:networks", type: "STUDY", title: "Network basics", description: "Learn networks", creator: { id: "flow", name: "Flow", handle: "@flow" }, media: { type: "image", src: "/cover" }, tags: [], likes: 0, comments: 0, shares: 0, saves: 0, ctaType: "use-template", targetPage: "study-library", sourceId: "networks" };
beforeEach(() => {
  vi.resetAllMocks();
  Element.prototype.scrollTo = vi.fn();
});
it("shows real lesson links and filters creations without losing lessons", async () => {
  vi.mocked(loadFeedItems).mockResolvedValue({ items: [lesson, { ...lesson, id: "app", type: "APP", title: "Sales app" }], isMock: false, error: false });
  render(<FeedPage />);
  expect(await screen.findByRole("link", { name: "study.open" })).toHaveAttribute("href", "/study-library?lesson=networks");
  fireEvent.click(screen.getByRole("button", { name: "study.study" }));
  expect(screen.queryByText("Sales app")).not.toBeInTheDocument();
  expect(screen.getByText("Network basics")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "study.all" }));
  expect(screen.getByText("Sales app")).toBeInTheDocument();
});
it("retries failed loading and replaces the error with available content", async () => {
  vi.mocked(loadFeedItems).mockResolvedValueOnce({ items: [], error: true, isMock: false }).mockResolvedValueOnce({ items: [lesson], error: false, isMock: false });
  render(<FeedPage />);
  fireEvent.click(await screen.findByRole("button", { name: "error.retry" }));
  expect(await screen.findByText("Network basics")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});
it("combines study subject and text filtering and clears an empty result", async () => {
  vi.mocked(loadFeedItems).mockResolvedValue({ items: [{ ...lesson, tags: ["computing"] }, { ...lesson, id: "study:fractions", title: "Fractions", sourceId: "fractions", tags: ["math"] }], isMock: false, error: false });
  render(<FeedPage />);
  await screen.findByText("Network basics");
  fireEvent.click(screen.getByRole("button", { name: "study.study" }));
  fireEvent.change(screen.getByRole("combobox", { name: "study.subject" }), { target: { value: "math" } });
  expect(screen.queryByText("Network basics")).not.toBeInTheDocument();
  expect(screen.getByText("Fractions")).toBeInTheDocument();
  const search = screen.getByRole("searchbox", { name: "study.search" });
  const key = new KeyboardEvent("keydown", { key: "j", bubbles: true, cancelable: true });
  search.dispatchEvent(key);
  expect(key.defaultPrevented).toBe(false);
  fireEvent.change(search, { target: { value: "absent" } });
  expect(screen.getByText("study.noMatches")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "study.clear" }));
  expect(screen.getByText("Network basics")).toBeInTheDocument();
});

it("loads older summaries once, deduplicates overlap and stops on the last page", async () => {
  const first = Array.from({ length: 30 }, (_, i) => ({ ...lesson, id: `study:${i}`, title: `Lesson ${i}`, sourceId: String(i) }));
  vi.mocked(loadFeedItems).mockResolvedValue({ items: first, isMock: false, error: false });
  let resolvePage!: (items: FeedItem[]) => void;
  vi.mocked(loadStudyItems).mockReturnValueOnce(new Promise(resolve => { resolvePage = resolve; }));
  render(<FeedPage />);
  const button = await screen.findByRole("button", { name: "study.loadMore" });
  fireEvent.click(button); fireEvent.click(button);
  expect(loadStudyItems).toHaveBeenCalledTimes(1);
  expect(loadStudyItems).toHaveBeenCalledWith(30);
  resolvePage([first[29], { ...lesson, id: "study:older", title: "Older summary" }]);
  expect(await screen.findByText("Older summary")).toBeInTheDocument();
  expect(screen.getAllByText("Lesson 29")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "study.loadMore" })).not.toBeInTheDocument();
});
it("keeps previous summaries and retries the same offset after failure", async () => {
  vi.mocked(loadFeedItems).mockResolvedValue({ items: Array.from({ length: 30 }, (_, i) => ({ ...lesson, id: `study:${i}`, title: `Lesson ${i}` })), isMock: false, error: false });
  vi.mocked(loadStudyItems).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([]);
  render(<FeedPage />);
  fireEvent.click(await screen.findByRole("button", { name: "study.loadMore" }));
  fireEvent.click(await screen.findByRole("button", { name: "study.retryMore" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "study.loadingMore" })).not.toBeInTheDocument());
  expect(loadStudyItems).toHaveBeenNthCalledWith(1, 30);
  expect(loadStudyItems).toHaveBeenNthCalledWith(2, 30);
  expect(screen.getByText("Lesson 0")).toBeInTheDocument();
});
