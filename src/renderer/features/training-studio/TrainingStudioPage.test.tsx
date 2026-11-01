import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TrainingStudioPage } from "./TrainingStudioPage";
import * as service from "./services/trainingService";
import i18n from "../../i18n";
const toast = vi.hoisted(() => vi.fn());
vi.mock("../../contexts/toast", () => ({ useToast: () => toast }));
vi.mock("./services/trainingService", () => ({ listCourses: vi.fn(), listLearners: vi.fn(), listJobs: vi.fn(), listLessons: vi.fn(), updateCourse: vi.fn(), createLesson: vi.fn() }));
const course = { id: "c1", title: "Example Course", description: "Practice", status: "draft", language: "en", updated_at: "2026-11-01T08:00:00Z" } as service.Course;
beforeEach(async () => {
  vi.resetAllMocks(); await i18n.changeLanguage("en");
  vi.mocked(service.listCourses).mockResolvedValue([course]);
  vi.mocked(service.listLearners).mockResolvedValue([]); vi.mocked(service.listJobs).mockResolvedValue([]); vi.mocked(service.listLessons).mockResolvedValue([]);
});
async function openCourse() {
  render(<TrainingStudioPage />);
  fireEvent.click(screen.getByRole("button", { name: /^Courses$/ }));
  fireEvent.click(await screen.findByText("Example Course"));
  await screen.findByRole("button", { name: /^Publish$/ });
}
it("updates publish and unpublish actions from the confirmed server status", async () => {
  vi.mocked(service.updateCourse).mockResolvedValueOnce({ ...course, status: "published" }).mockResolvedValueOnce(course);
  await openCourse(); fireEvent.click(screen.getByRole("button", { name: /^Publish$/ }));
  fireEvent.click(await screen.findByRole("button", { name: /^Unpublish$/ }));
  await screen.findByRole("button", { name: /^Publish$/ });
  expect(service.updateCourse).toHaveBeenNthCalledWith(1, "c1", { status: "published" });
  expect(service.updateCourse).toHaveBeenNthCalledWith(2, "c1", { status: "draft" });
});
it("reports rejected publishing and leaves the original action available", async () => {
  vi.mocked(service.updateCourse).mockRejectedValue(new Error("Denied"));
  await openCourse(); fireEvent.click(screen.getByRole("button", { name: /^Publish$/ }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Could not complete the action. Check the connection and try again.", "err"));
  expect(screen.getByRole("button", { name: /^Publish$/ })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /^Unpublish$/ })).not.toBeInTheDocument();
});
