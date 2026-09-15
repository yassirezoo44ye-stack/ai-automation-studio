import { useCallback, useEffect, useRef, useState } from "react";

interface UseFeedNavigationOptions {
  total: number;
}

export function useFeedNavigation({ total }: UseFeedNavigationOptions) {
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const isScrollingRef = useRef(false);

  const scrollToIndex = useCallback(
    (index: number) => {
      const clampedIndex = Math.max(0, Math.min(index, total - 1));
      setActiveIndex(clampedIndex);
      const el = containerRef.current;
      if (!el) return;
      const cardHeight = el.clientHeight;
      el.scrollTo({ top: clampedIndex * cardHeight, behavior: "smooth" });
    },
    [total]
  );

  const goNext = useCallback(() => {
    scrollToIndex(activeIndex + 1);
  }, [activeIndex, scrollToIndex]);

  const goPrev = useCallback(() => {
    scrollToIndex(activeIndex - 1);
  }, [activeIndex, scrollToIndex]);

  /* ── Keyboard navigation ───────────────────────────────────── */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        goNext();
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        goPrev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, goPrev]);

  /* ── Wheel / trackpad navigation ──────────────────────────── */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      if (isScrollingRef.current) return;
      isScrollingRef.current = true;
      if (e.deltaY > 0) goNext();
      else if (e.deltaY < 0) goPrev();
      // throttle to avoid multi-step jumps
      setTimeout(() => {
        isScrollingRef.current = false;
      }, 600);
    }

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [goNext, goPrev]);

  /* ── Touch swipe ───────────────────────────────────────────── */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let startY = 0;
    function onTouchStart(e: TouchEvent) {
      startY = e.touches[0].clientY;
    }
    function onTouchEnd(e: TouchEvent) {
      const delta = startY - e.changedTouches[0].clientY;
      if (Math.abs(delta) < 50) return; // ignore small swipes
      if (delta > 0) goNext();
      else goPrev();
    }

    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchend", onTouchEnd);
    };
  }, [goNext, goPrev]);

  return { activeIndex, containerRef, scrollToIndex, goNext, goPrev };
}
