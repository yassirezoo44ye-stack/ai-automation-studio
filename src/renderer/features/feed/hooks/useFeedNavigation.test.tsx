import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useFeedNavigation } from "./useFeedNavigation";
function Harness({ total }: { total: number }) {
  const { activeIndex, containerRef } = useFeedNavigation({ total });
  return <><div ref={containerRef} data-testid="scroll" /><output>{activeIndex}</output></>;
}
it("tracks native scrolling and clamps the position when the list shrinks", () => {
  const { rerender } = render(<Harness total={4} />);
  const el = screen.getByTestId("scroll");
  Object.defineProperty(el, "clientHeight", { value: 600 });
  el.scrollTop = 1200; fireEvent.scroll(el);
  expect(screen.getByRole("status")).toHaveTextContent("2");
  rerender(<Harness total={1} />);
  expect(screen.getByRole("status")).toHaveTextContent("0");
});
it("allows native wheel and touch behavior without advancing a second time", () => {
  Element.prototype.scrollTo = vi.fn();
  render(<Harness total={4} />);
  const el = screen.getByTestId("scroll");
  const wheel = new WheelEvent("wheel", { deltaY: 600, cancelable: true });
  el.dispatchEvent(wheel);
  expect(wheel.defaultPrevented).toBe(false);
  fireEvent.touchStart(el, { touches: [{ clientY: 500 }] });
  fireEvent.touchEnd(el, { changedTouches: [{ clientY: 0 }] });
  expect(Element.prototype.scrollTo).not.toHaveBeenCalled();
});
