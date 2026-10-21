/**
 * A soft fade at the edge of a scrolling box, only on the side that has more to show: none when
 * everything fits, the bottom edge at the top of a long list, both in the middle. Used by
 * WidgetCard's body, whose height the Overview grid caps.
 *
 *   const body = ref<HTMLElement | null>(null);
 *   const content = ref<HTMLElement | null>(null);
 *   const fade = useScrollFade(body, content);     // :style="fade"
 */
import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from "vue";

const EDGE = "14px";

/** The mask for a box scrolled `top` px out of `scrollHeight`, showing `clientHeight`. */
export function fadeMask(scrollTop: number, clientHeight: number, scrollHeight: number): string | null {
  const above = scrollTop > 1;
  const below = scrollTop + clientHeight < scrollHeight - 1;
  if (!above && !below) return null;
  return `linear-gradient(to bottom, ${above ? "transparent" : "#000"} 0, #000 ${EDGE}, #000 calc(100% - ${EDGE}), ${below ? "transparent" : "#000"} 100%)`;
}

/** Whether a box scrolled `scrollLeft` px can still scroll further right. */
export function moreToTheRight(scrollLeft: number, clientWidth: number, scrollWidth: number): boolean {
  return scrollLeft + clientWidth < scrollWidth - 1;
}

/**
 * True while a horizontally scrolling box (a wide table) has columns hidden past its right edge,
 * so the host can show a shadow there instead of a column cut off as if it ended.
 */
export function useMoreToTheRight(box: Ref<HTMLElement | null>, content?: Ref<HTMLElement | null>) {
  const more = ref(false);
  const update = () => {
    const el = box.value;
    more.value = el ? moreToTheRight(el.scrollLeft, el.clientWidth, el.scrollWidth) : false;
  };
  const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
  // The box may mount later than the host (a table that replaces phone cards): follow the ref.
  watch(
    [box, () => content?.value ?? null],
    ([el, inner], [previous]) => {
      previous?.removeEventListener("scroll", update);
      observer?.disconnect();
      if (el) {
        el.addEventListener("scroll", update, { passive: true });
        observer?.observe(el);
        if (inner) observer?.observe(inner);
      }
      update();
    },
    { flush: "post" },
  );
  onMounted(update);
  onBeforeUnmount(() => {
    box.value?.removeEventListener("scroll", update);
    observer?.disconnect();
  });
  return more;
}

export function useScrollFade(box: Ref<HTMLElement | null>, content?: Ref<HTMLElement | null>) {
  const mask = ref<string | null>(null);
  const update = () => {
    const el = box.value;
    mask.value = el ? fadeMask(el.scrollTop, el.clientHeight, el.scrollHeight) : null;
  };
  let observer: ResizeObserver | null = null;
  onMounted(() => {
    const el = box.value;
    if (!el) return;
    update();
    el.addEventListener("scroll", update, { passive: true });
    if (typeof ResizeObserver === "undefined") return;
    // The box keeps its size when a list arrives; its content doesn't.
    observer = new ResizeObserver(update);
    observer.observe(el);
    if (content?.value) observer.observe(content.value);
  });
  onBeforeUnmount(() => {
    box.value?.removeEventListener("scroll", update);
    observer?.disconnect();
  });
  return computed(() => (mask.value ? { maskImage: mask.value, WebkitMaskImage: mask.value } : undefined));
}
