import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentsTab } from "./AgentsTab";
import { apiFetch } from "../../../utils/api";
import type * as ApiModule from "../../../utils/api";
import i18n from "../../../i18n";
import type { Agent } from "../../../types";
const toast = vi.hoisted(() => vi.fn());
vi.mock("../../../contexts/toast", () => ({ useToast: () => toast }));
vi.mock("../../../utils/api", async original => ({ ...await original<typeof ApiModule>(), apiFetch: vi.fn() }));
beforeEach(async () => { vi.resetAllMocks(); vi.spyOn(window, "confirm").mockReturnValue(true); await i18n.changeLanguage("en"); });
it("reports rejected agent deletion without claiming success or refreshing away the agent", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(null, { status: 403 }));
  const refresh = vi.fn();
  render(<AgentsTab agents={[{ id: "agent-1", name: "Example Agent", avatar: "🤖", model: "example", created_at: "2026-11-01T08:00:00Z" } as Agent]} loading={false} onRefresh={refresh} onChatWith={vi.fn()} />);
  fireEvent.click(screen.getByTitle("Delete"));
  await waitFor(() => expect(toast).toHaveBeenCalledWith("Could not delete the agent.", "err"));
  expect(refresh).not.toHaveBeenCalled(); expect(screen.getByText("Example Agent")).toBeInTheDocument();
});
