import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceDetails } from "./WorkspaceDetails";

describe("optional workspace context", () => {
  it("keeps optional controls and their data work unmounted until requested", () => {
    const load = vi.fn();
    function Setup() { load(); return <button>Configure follow-up</button>; }
    render(<WorkspaceDetails kind="setup"><Setup /></WorkspaceDetails>);
    expect(load).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Configure follow-up" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Workspace setup"));
    expect(load).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Configure follow-up" })).toBeInTheDocument();
  });
  it("preserves a draft while its section is collapsed", () => {
    render(<WorkspaceDetails kind="setup"><input aria-label="Draft" /></WorkspaceDetails>);
    fireEvent.click(screen.getByText("Workspace setup"));
    fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep my work" } });
    fireEvent.click(screen.getByText("Workspace setup"));
    expect(screen.queryByRole("textbox", { name: "Draft" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Workspace setup"));
    expect(screen.getByLabelText("Draft")).toHaveValue("Keep my work");
  });
  it("can open optional forms from a primary navigation action", () => {
    const changed = vi.fn();
    const { rerender } = render(<WorkspaceDetails kind="setup" expanded={false} onExpandedChange={changed}><input aria-label="Profile" /></WorkspaceDetails>);
    expect(screen.queryByLabelText("Profile")).not.toBeInTheDocument();
    rerender(<WorkspaceDetails kind="setup" expanded onExpandedChange={changed}><input aria-label="Profile" /></WorkspaceDetails>);
    expect(screen.getByLabelText("Profile")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Workspace setup"));
    expect(changed).toHaveBeenCalledWith(false);
  });
});
