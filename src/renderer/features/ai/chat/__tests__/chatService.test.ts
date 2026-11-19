import { afterEach, expect, it, vi } from "vitest";
import { deleteConversation, updateTaskStatus } from "../chatService";
afterEach(() => vi.unstubAllGlobals());
it("rejects failed deletion instead of allowing the UI to remove a saved conversation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("",{status:403})));
  await expect(deleteConversation("private-conversation")).rejects.toThrow("deletion rejected");
});
it("rejects a task status that the server did not save", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("",{status:500})));
  await expect(updateTaskStatus("task","done")).rejects.toThrow("update rejected");
});
