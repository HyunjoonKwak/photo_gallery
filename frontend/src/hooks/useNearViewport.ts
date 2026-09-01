import { useEffect, useRef, useState, type RefObject } from "react";

/** Becomes true once an element is near its scroll viewport, then stays true.
 * Used to defer card-preview API calls without making already-seen cards flash
 * back to placeholders when the user scrolls away.
 */
export function useNearViewport<T extends Element>(
  rootRef?: RefObject<Element | null>,
  rootMargin = "500px 0px",
) {
  const targetRef = useRef<T | null>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (near) return;
    const target = targetRef.current;
    if (!target) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      {
        root: rootRef?.current ?? null,
        rootMargin,
        threshold: 0.01,
      },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [near, rootMargin, rootRef]);

  return [targetRef, near] as const;
}
