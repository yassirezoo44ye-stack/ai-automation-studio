import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { streamBuild, type BuildEvent } from "../services/builderService";

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });
function response(events: object[], trailing = true) {
  return new Response(events.map(event => `data: ${JSON.stringify(event)}`).join("\n\n") + (trailing ? "\n\n" : ""), {headers:{"Content-Type":"text/event-stream"}});
}
it("preserves emitted source files but rejects a disconnected build without completion", async () => {
  const file = {type:"file",path:"main.py",content:"print('hello')"};
  vi.mocked(fetch).mockResolvedValueOnce(response([file]));
  const received: BuildEvent[] = [];
  await expect((async () => {for await (const event of streamBuild("owned-project","build")) received.push(event);})()).rejects.toThrow(/interrupted/);
  expect(received).toEqual([file]);
});
it("accepts an unpadded completion and never repeats generation after a stream disconnect", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([{type:"done",description:"complete",files:[],run_command:"",language:"python"}],false));
  const received: BuildEvent[] = [];
  for await (const event of streamBuild("owned-project","build")) received.push(event);
  expect(received[0].type).toBe("done");
  expect(fetch).toHaveBeenCalledOnce();
});
