/**
 * Where a sliding underline or thumb sits under the active item of a strip (PageHeader tabs,
 * SavedViewsTabs, SegmentedControl).
 *
 * Items change width after the first paint: a count arrives ("To verify 4"), the language
 * switches, fonts load. Measuring only when the active item changes leaves the indicator under an
 * old position, so every item is watched for size changes as well; a wider item moves the ones
 * after it, and the active one's new place is measured then.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref, type WatchSource } from "vue";

export interface IndicatorBox {
  left: number;
  width: number;
}

export function useSlidingIndicator(
  container: Ref<HTMLElement | null>,
  options: {
    /** Selector of the active item inside `container`. */
    active: () => string;
    /** Selector of every item, each watched for size changes. */
    items: string;
    /** Re-measure (and re-watch the items) when these change: the active id, the items' labels and counts. */
    deps: WatchSource[];
    /**
     * The container scrolls sideways (tabs on a phone): keep the active item in view. Only the
     * strip scrolls, never the page, so a count arriving while you read further down moves nothing.
     */
    reveal?: boolean;
  },
) {
  const indicator = ref<IndicatorBox | null>(null);

  function reveal(el: HTMLElement): void {
    const strip = container.value;
    if (!strip || strip.scrollWidth <= strip.clientWidth) return;
    const pad = 16;
    const start = el.offsetLeft - pad;
    const end = el.offsetLeft + el.offsetWidth + pad;
    if (start < strip.scrollLeft) strip.scrollLeft = Math.max(0, start);
    else if (end > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = end - strip.clientWidth;
  }

  function measure(): void {
    const el = container.value?.querySelector<HTMLElement>(options.active());
    indicator.value = el ? { left: el.offsetLeft, width: el.offsetWidth } : null;
    if (el && options.reveal) reveal(el);
  }

  let observer: ResizeObserver | null = null;
  function observe(): void {
    observer?.disconnect();
    if (typeof ResizeObserver === "undefined" || !container.value) return;
    observer ??= new ResizeObserver(() => measure());
    for (const item of container.value.querySelectorAll<HTMLElement>(options.items)) observer.observe(item);
  }

  watch(options.deps, () =>
    nextTick(() => {
      measure();
      observe();
    }),
  );
  onMounted(() => {
    measure();
    observe();
    void document.fonts?.ready.then(measure);
  });
  onBeforeUnmount(() => observer?.disconnect());

  return { indicator, measure };
}
