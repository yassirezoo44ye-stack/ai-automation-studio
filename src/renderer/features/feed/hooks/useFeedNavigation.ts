import { useCallback, useEffect, useRef, useState } from "react";

interface UseFeedNavigationOptions {
  total: number;
}

export function useFeedNavigation({ total }: UseFeedNavigationOptions) {
  const [position, setActiveIndex] = useState(0);
  const activeIndex = Math.max(0, Math.min(position, total - 1));
  const containerRef = useRef<HTMLDivElement>(null);

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
      const target = e.target;
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey ||
        (target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select, button, a")))) return;
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

  // Native wheel/touch scrolling uses CSS scroll snap. Observe the resulting
  // position rather than advancing again on touchend (which can skip cards).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      if (el.clientHeight <= 0) return;
      setActiveIndex(Math.max(0, Math.min(Math.round(el.scrollTop / el.clientHeight), total - 1)));
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [total]);

  return { activeIndex, containerRef, scrollToIndex, goNext, goPrev };
}
