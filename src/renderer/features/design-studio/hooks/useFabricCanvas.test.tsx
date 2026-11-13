import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useFabricCanvas } from "./useFabricCanvas";

vi.mock("fabric", () => ({
  Canvas: class {
    width = 1280; height = 720;
    viewportTransform = [1, 0, 0, 1, 0, 0];
    on() {} dispose() {}
    getZoom() { return this.viewportTransform[0]; }
    setZoom(zoom: number) { this.viewportTransform[0] = zoom; this.viewportTransform[3] = zoom; }
    setViewportTransform(value: number[]) { this.viewportTransform = value; }
    zoomToPoint(_point: unknown, zoom: number) { this.setZoom(zoom); }
  },
  Point: class { constructor(public x: number, public y: number) {} },
  Rect: class {}, Circle: class {}, Triangle: class {}, Line: class {},
  IText: class {}, FabricImage: class {}, PencilBrush: class {}, ActiveSelection: class {},
}));

it("fits a document to the available panel and reports actual zoom changes", () => {
  const onViewport = vi.fn();
  function Harness() {
    const canvas = useFabricCanvas(vi.fn(), vi.fn(), onViewport);
    return <>
      <div data-grid data-testid="panel"><canvas ref={canvas.canvasRef} /></div>
      <button onClick={canvas.zoomToFitCanvas}>Fit</button>
      <button onClick={canvas.zoomOut}>Zoom out</button>
      <button onClick={canvas.zoomReset}>Reset</button>
    </>;
  }
  render(<Harness />);
  const panel = screen.getByTestId("panel");
  Object.defineProperties(panel, { clientWidth: { value: 800 }, clientHeight: { value: 520 } });
  fireEvent.click(screen.getByText("Fit"));
  expect(onViewport).toHaveBeenLastCalledWith({ zoom: 0.5, panX: 320, panY: 180 });
  fireEvent.click(screen.getByText("Zoom out"));
  expect(onViewport.mock.lastCall![0].zoom).toBeCloseTo(0.5 / 1.2);
  fireEvent.click(screen.getByText("Reset"));
  expect(onViewport).toHaveBeenLastCalledWith({ zoom: 1, panX: 0, panY: 0 });
});
