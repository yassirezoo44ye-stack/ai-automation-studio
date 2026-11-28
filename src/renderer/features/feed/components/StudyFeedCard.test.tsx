import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StudyFeedCard } from "./StudyFeedCard";
import type { FeedItem } from "../types/feed.types";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const item: FeedItem = { id: "study:networks", type: "STUDY", title: "Network basics", description: "Learn networks", creator: { id: "flow", name: "Flow", handle: "@flow" }, media: { type: "image", src: "/cover" }, tags: ["computing"], likes: 0, comments: 0, shares: 0, saves: 0, ctaType: "use-template", targetPage: "study-library", sourceId: "networks" };
beforeEach(() => {
  Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
});
function openActions() { fireEvent.click(screen.getByText("study.more")); }
describe("study card actions", () => {
  it("copies the public lesson link and links to the same subject", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<StudyFeedCard item={item} isActive />); openActions();
    expect(screen.getByRole("link", { name: "study.related" })).toHaveAttribute("href", "/study-library?subject=computing");
    fireEvent.click(screen.getByRole("button", { name: "actions.share" }));
    await screen.findByText("study.copied");
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/study-library?lesson=networks`);
  });
  it("does not copy after cancelling the native share sheet", async () => {
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const share = vi.fn().mockRejectedValue(new DOMException("cancelled", "AbortError"));
    Object.defineProperty(navigator, "share", { value: share, configurable: true });
    render(<StudyFeedCard item={item} isActive />); openActions();
    fireEvent.click(screen.getByRole("button", { name: "actions.share" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "actions.share" })).toBeEnabled());
    expect(share).toHaveBeenCalledOnce(); expect(writeText).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it("offers a selectable public link when sharing and clipboard are unavailable", async () => {
    render(<StudyFeedCard item={item} isActive />); openActions();
    fireEvent.click(screen.getByRole("button", { name: "actions.share" }));
    expect(await screen.findByRole("textbox", { name: "study.copyLink" })).toHaveValue(`${window.location.origin}/study-library?lesson=networks`);
    expect(screen.queryByText("study.copied")).not.toBeInTheDocument();
  });
  it("keeps the lesson action usable after cover failure", () => {
    render(<StudyFeedCard item={item} isActive />);
    fireEvent.error(screen.getByRole("img", { name: item.title }));
    expect(screen.getByRole("img", { name: "study.coverUnavailable" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "study.open" })).toHaveAttribute("href", "/study-library?lesson=networks");
  });
});

it("reports native sharing success without copying a second time", async () => {
  const share = vi.fn().mockResolvedValue(undefined);
  const writeText = vi.fn();
  Object.defineProperty(navigator, "share", { value: share, configurable: true });
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  render(<StudyFeedCard item={item} isActive />); openActions();
  fireEvent.click(screen.getByRole("button", { name: "actions.share" }));
  await screen.findByText("study.shared");
  expect(share).toHaveBeenCalledWith({ title: item.title, url: `${window.location.origin}/study-library?lesson=networks` });
  expect(writeText).not.toHaveBeenCalled();
});
it("keeps a manual link when native sharing and clipboard both reject", async () => {
  Object.defineProperty(navigator, "share", { value: vi.fn().mockRejectedValue(new Error("unavailable")), configurable: true });
  Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
  render(<StudyFeedCard item={{ ...item, tags: ["unknown"] }} isActive />); openActions();
  fireEvent.click(screen.getByRole("button", { name: "actions.share" }));
  expect(await screen.findByRole("textbox", { name: "study.copyLink" })).toHaveAttribute("readonly");
  expect(screen.queryByRole("link", { name: "study.related" })).not.toBeInTheDocument();
});
