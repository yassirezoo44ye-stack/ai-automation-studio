import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { RunTab } from "../RunTab";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function Workspace() {
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<Parameters<typeof RunTab>[0]["runError"]>(null);
  return <RunTab projectId="owned-project" files={[{path:"main.py",content:"print('hello')"}]} hasFiles runCmd="python main.py" runOutput={output} running={running} runError={error} onCmd={vi.fn()} onOutput={setOutput} onRunning={setRunning} onError={setError} onPreviewUrl={vi.fn()} onSwitchTab={vi.fn()} currentPreviewUrl={null} />;
}
const json = (status: number) => new Response(JSON.stringify({saved: status === 200}), {status, headers:{"Content-Type":"application/json"}});
const sse = (text: string) => new Response(text, {headers:{"Content-Type":"text/event-stream"}});

beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("confirmed file synchronization before execution", () => {
  it("does not start a process when saving source files fails", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(500));
    render(<Workspace />);
    fireEvent.click(screen.getByText("runTab.runButton"));
    await waitFor(() => expect(screen.getByText(/✗/)).toHaveTextContent("Internal server error"));
    expect(fetch).toHaveBeenCalledOnce();
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toMatch(/\/sync$/);
    expect(screen.getByText("runTab.runButton")).toBeEnabled();
  });

  it("retains logs and exposes interrupted execution instead of a silent completion", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(200)).mockResolvedValueOnce(sse('data: {"type":"log","line":"started"}\n\n'));
    render(<Workspace />);
    fireEvent.click(screen.getByText("runTab.runButton"));
    await waitFor(() => expect(screen.getByText(/✗/)).toHaveTextContent("runTab.interrupted"));
    expect(screen.getByText(/started/)).toHaveTextContent("runTab.interrupted");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByText("runTab.runButton")).toBeEnabled();
  });

  it("accepts a confirmed final exit event without a trailing newline", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(json(200)).mockResolvedValueOnce(sse('data: {"type":"done","stdout":"hello","exit_code":0,"duration":1}'));
    render(<Workspace />);
    fireEvent.click(screen.getByText("runTab.runButton"));
    await waitFor(() => expect(screen.getByText(/hello/)).toHaveTextContent("exit 0"));
    expect(screen.queryByText(/✗/)).not.toBeInTheDocument();
    expect(screen.getByText("runTab.runButton")).toBeEnabled();
  });
});
