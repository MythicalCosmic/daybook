import { useCallback, useEffect, useRef } from "react";

/**
 * For a strip that scrolls sideways: marks the sides that hide more of it, `data-more="left"`,
 * `"right"` or `"both"`, so CSS fades those edges and a cut-off tab reads as "more this way"
 * rather than as a clipped label. Returns the ref for the strip and `update` for after changes.
 */
export function useScrollEdges<T extends HTMLElement>() {
  const node = useRef<T | null>(null);
  const update = useCallback(() => {
    const strip = node.current;
    if (!strip) return;
    const left = strip.scrollLeft > 1;
    const right = strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1;
    const more = left && right ? "both" : left ? "left" : right ? "right" : "";
    if (more) strip.dataset.more = more;
    else delete strip.dataset.more;
  }, []);

  useEffect(() => {
    const strip = node.current;
    if (!strip) return;
    update();
    strip.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      strip.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [update]);

  return { ref: node, update };
}
