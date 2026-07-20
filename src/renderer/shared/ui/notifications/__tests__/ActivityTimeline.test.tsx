import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ActivityTimeline, type TimelineEntry } from "../ActivityTimeline";

const GROUPS = [
  { id: "security", label: "Security" },
  { id: "organization", label: "Organization" },
];

function entry(overrides: Partial<TimelineEntry> = {}): TimelineEntry {
  return { id: "e1", action: "login", sub: "127.0.0.1", created_at: new Date().toISOString(), group: "security", ...overrides };
}

describe("ActivityTimeline", () => {
  it("shows a loading spinner while status is loading", () => {
    render(<ActivityTimeline entries={[]} groups={GROUPS} status="loading" />);
    expect(screen.getByText(/loading activity/i)).toBeInTheDocument();
  });

  it("shows an error state with retry when status is error", () => {
    const onRetry = vi.fn();
    render(<ActivityTimeline entries={[]} groups={GROUPS} status="error" error="boom" onRetry={onRetry} />);
    expect(screen.getByText("boom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state when there are no entries", () => {
    render(<ActivityTimeline entries={[]} groups={GROUPS} status="success" emptyMessage="Nothing to see" />);
    expect(screen.getByText("Nothing to see")).toBeInTheDocument();
  });

  it("groups entries under Today when created just now", () => {
    render(<ActivityTimeline entries={[entry()]} groups={GROUPS} status="success" />);
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("login")).toBeInTheDocument();
  });

  it("filters entries by group when a chip is clicked", () => {
    const entries = [
      entry({ id: "e1", action: "login", group: "security" }),
      entry({ id: "e2", action: "member.invited", group: "organization" }),
    ];
    render(<ActivityTimeline entries={entries} groups={GROUPS} status="success" />);
    expect(screen.getByText("login")).toBeInTheDocument();
    expect(screen.getByText("member.invited")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Security" }));
    expect(screen.getByText("login")).toBeInTheDocument();
    expect(screen.queryByText("member.invited")).not.toBeInTheDocument();
  });
});
