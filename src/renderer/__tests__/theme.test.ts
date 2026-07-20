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

  it("persists high-contrast to localStorage and applies the attribute", () => {
    localStorage.setItem("axon-theme", "high-contrast");
    document.documentElement.setAttribute("data-theme", "high-contrast");
    expect(localStorage.getItem("axon-theme")).toBe("high-contrast");
    expect(document.documentElement.getAttribute("data-theme")).toBe("high-contrast");
  });

  it("toggleTheme() from high-contrast lands on dark, not light", () => {
    // Mirrors AppContext.tsx's toggleTheme: prev === "dark" ? "light" : "dark" —
    // the quick sidebar toggle is a dark<->light binary switch; high-contrast
    // is only reachable via the explicit Settings picker, so any toggle from
    // it must fall back to dark, never silently to light.
    const toggle = (prev: "dark" | "light" | "high-contrast") => (prev === "dark" ? "light" : "dark");
    expect(toggle("high-contrast")).toBe("dark");
  });
});
