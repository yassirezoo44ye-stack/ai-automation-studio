import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StudyFeedCard } from "../components/StudyFeedCard";
import { relativeDate } from "../components/relativeDate";
import type { FeedItem } from "../types/feed.types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) => (opts?.count !== undefined ? `${key}:${opts.count}` : key),
    i18n: { language: "en" },
  }),
}));

const lesson: FeedItem = {
  id: "study:pressure", type: "STUDY", title: "Pressure", description: "One force on two areas",
  creator: { id: "flow", name: "Flow", handle: "@flow" }, media: { type: "image", src: "/cover" },
  tags: ["physics"], likes: 0, comments: 0, shares: 0, saves: 0, ctaType: "use-template",
  targetPage: "study-library", sourceId: "pressure", pages: 3,
  publishedAt: new Date(Date.now() - 2 * 86400000).toISOString(),
};

describe("StudyFeedCard", () => {
  it("shows the subject, page count and publish date instead of a generic label", () => {
    render(<StudyFeedCard item={lesson} isActive />);
    expect(screen.getByText("study.subjects.physics")).toBeInTheDocument();
    expect(screen.getByText("study.pages:3 · 2 days ago")).toBeInTheDocument();
    expect(screen.queryByText("study.label")).not.toBeInTheDocument();
    // The cover is decorative, so the title is announced once, not twice.
    expect(screen.getAllByText("Pressure")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "study.open" })).toHaveAttribute("href", "/study-library?lesson=pressure");
  });
});

describe("relativeDate", () => {
  const now = Date.parse("2026-11-16T12:00:00Z");
  it("formats past dates in the UI language", () => {
    expect(relativeDate("2026-11-13T12:00:00Z", "en", now)).toBe("3 days ago");
    expect(relativeDate("2026-11-16T09:00:00Z", "en", now)).toBe("3 hours ago");
  });
  it("returns nothing for a missing or invalid date", () => {
    expect(relativeDate(undefined, "en", now)).toBe("");
    expect(relativeDate("not a date", "en", now)).toBe("");
  });
});
