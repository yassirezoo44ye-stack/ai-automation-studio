import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const execDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");
afterEach(() => {
  if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor); else Reflect.deleteProperty(navigator, "clipboard");
  if (execDescriptor) Object.defineProperty(document, "execCommand", execDescriptor); else Reflect.deleteProperty(document, "execCommand");
  document.body.innerHTML = "";
});
describe("confirmed clipboard writes", () => {
  it("waits for the browser to complete the copy", async () => {
    let done!: () => void;
    const writeText = vi.fn(() => new Promise<void>(resolve => { done = resolve; }));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    let confirmed = false;
    const pending = copyText("example").then(() => { confirmed = true; });
    await Promise.resolve(); expect(confirmed).toBe(false);
    done(); await pending; expect(confirmed).toBe(true); expect(writeText).toHaveBeenCalledWith("example");
  });
  it("falls back when clipboard permission is denied and restores focus", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error("Denied")) } });
    const exec = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { configurable: true, value: exec });
    const button = document.createElement("button"); document.body.appendChild(button); button.focus();
    await copyText("example");
    expect(exec).toHaveBeenCalledWith("copy"); expect(document.activeElement).toBe(button); expect(document.querySelector("textarea")).toBeNull();
  });
  it("rejects a false legacy result without leaving the copied text in the DOM", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    Object.defineProperty(document, "execCommand", { configurable: true, value: () => false });
    await expect(copyText("example")).rejects.toThrow("Copy failed");
    expect(document.querySelector("textarea")).toBeNull();
  });
});
