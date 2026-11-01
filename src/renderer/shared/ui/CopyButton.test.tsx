import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopyButton } from "./CopyButton";
import { copyText } from "../utils/clipboard";
import i18n from "../../i18n";
vi.mock("../utils/clipboard", () => ({ copyText: vi.fn() }));
beforeEach(async () => { vi.resetAllMocks(); await i18n.changeLanguage("en"); });
it("shows a failed copy and permits retry without submitting its containing form", async () => {
  vi.mocked(copyText).mockRejectedValueOnce(new Error("Denied")).mockResolvedValueOnce();
  const submit = vi.fn(event => event.preventDefault());
  render(<form onSubmit={submit}><CopyButton text="example" /></form>);
  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  fireEvent.click(await screen.findByRole("button", { name: /Could not copy/ }));
  await screen.findByRole("button", { name: "Copied" });
  expect(submit).not.toHaveBeenCalled();
});
