import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { RuntimePanel } from "../components/RuntimePanel";
import { isolatedPreviewUrl } from "../services/previewUrl";
import { stopProject } from "../services/runnerService";
import { apiFetch } from "../../../shared/utils/api";

vi.mock("../../../shared/utils/api", () => ({ apiFetch: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const url = "https://preview-example.vercel.run/_flow_preview/short-lived-capability";
const props = {
  runtimeState: "running" as const, previewUrl: url, previewType: "isolated" as const,
  runtimeError: null, buildDone: true, projectName: "Example", startupMessages: [],
  onRun: vi.fn(), onStop: vi.fn(), onRestart: vi.fn(), onExplainError: vi.fn(),
};

describe("isolated preview", () => {
  it("embeds only a separate origin and suppresses referrers", () => {
    render(<RuntimePanel {...props} />);
    const iframe = screen.getByTitle("App Preview");
    expect(iframe).toHaveAttribute("src", url);
    expect(iframe).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts allow-forms allow-same-origin");
    expect(screen.queryByText(url)).not.toBeInTheDocument();
    cleanup();
  });

  it.each(["/api/projects/p/proxy/", "http://x.vercel.run", "https://x.vercel.run.attacker.test",
    "https://user:secret@x.vercel.run", "https://x.vercel.run:9999", "javascript:alert(1)"])(
    "rejects untrusted navigation %s", value => expect(() => isolatedPreviewUrl(value)).toThrow(),
  );

  it("opens a preview without an opener or referrer", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<RuntimePanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));
    expect(open).toHaveBeenCalledWith(url, "_blank", "noopener,noreferrer");
    open.mockRestore();
    cleanup();
  });

  it("keeps Stop available when remote deletion needs a retry", () => {
    const onStop = vi.fn();
    render(<RuntimePanel {...props} runtimeState="failed" onStop={onStop}
      runtimeError={{ category: "network", message: "Could not stop", fix: ["Retry Stop"] }} />);
    fireEvent.click(screen.getByRole("button", { name: /■ Stop/ }));
    expect(onStop).toHaveBeenCalledOnce();
    cleanup();
  });

  it("reports HTTP stop failures instead of claiming success", async () => {
    vi.mocked(apiFetch).mockResolvedValue(new Response("unavailable", { status: 503 }));
    await expect(stopProject("project")).rejects.toThrow("503");
  });

  it("reports network stop failures instead of claiming success", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
    await expect(stopProject("project")).rejects.toThrow("offline");
  });
});
