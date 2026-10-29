import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach } from "vitest";
import { FeedPage } from "../features/feed/FeedPage";
import { loadFeedItems } from "../features/feed/services/feedService";
import type { FeedItem } from "../features/feed/types/feed.types";
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
