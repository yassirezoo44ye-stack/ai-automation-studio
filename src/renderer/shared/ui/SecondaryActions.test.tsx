import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SecondaryActions } from "./SecondaryActions";

describe("secondary actions", () => {
  it("hides secondary actions until expanded and keeps disabled actions disabled", () => {
    const remove = vi.fn();
    render(<SecondaryActions label="More"><button onClick={remove}>Delete</button><button disabled>Publish</button></SecondaryActions>);
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("More"));
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledOnce();
  });
  it("closes with Escape and restores focus to the disclosure", () => {
    render(<SecondaryActions label="المزيد"><button>تصدير</button></SecondaryActions>);
    const summary = screen.getByText("المزيد");
    fireEvent.click(summary);
    const action = screen.getByRole("button", { name: "تصدير" });
    action.focus();
    fireEvent.keyDown(action, { key: "Escape" });
    expect(summary).toHaveFocus();
    expect(screen.queryByRole("button", { name: "تصدير" })).not.toBeInTheDocument();
  });
  it("closes on an outside pointer without invoking an action", () => {
    const action = vi.fn();
    render(<><SecondaryActions label="More"><button onClick={action}>Export</button></SecondaryActions><button>Outside</button></>);
    fireEvent.click(screen.getByText("More"));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
    expect(action).not.toHaveBeenCalled();
  });
});
