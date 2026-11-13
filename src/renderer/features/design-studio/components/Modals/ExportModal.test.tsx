import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Canvas } from "fabric";
import { ExportModal } from "./ExportModal";
import { exportCanvas } from "../../services/exportService";
import "../../../../i18n";
vi.mock("../../services/exportService", () => ({ exportCanvas: vi.fn() }));

it("keeps export options open on failure and permits retry", async () => {
  const onClose = vi.fn();
  vi.mocked(exportCanvas).mockImplementationOnce(() => { throw new Error("tainted"); });
  render(<ExportModal getCanvas={() => ({} as Canvas)} onClose={onClose} />);
  fireEvent.click(screen.getByRole("button", { name: "Export PNG" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be exported");
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Export PNG" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
});
