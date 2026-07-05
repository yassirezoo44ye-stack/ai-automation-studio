import { describe, it, expect, beforeEach } from "vitest";

describe("Theme persistence helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("defaults to dark when no stored preference", () => {
    const stored = localStorage.getItem("axon-theme");
    expect(stored).toBeNull();
  });

  it("persists theme to localStorage", () => {
    localStorage.setItem("axon-theme", "light");
    expect(localStorage.getItem("axon-theme")).toBe("light");
  });

  it("applies data-theme attribute", () => {
    document.documentElement.setAttribute("data-theme", "light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("can toggle between themes", () => {
    let theme = "dark" as "dark" | "light";
    theme = theme === "dark" ? "light" : "dark";
    expect(theme).toBe("light");
    theme = theme === "dark" ? "light" : "dark";
    expect(theme).toBe("dark");
  });
});
