/**
 * A soft fade at the edge of a scrolling box, only on the side that has more to show: none when
 * everything fits, the bottom edge at the top of a long list, both in the middle. Used by
 * WidgetCard's body, whose height the Overview grid caps.
 *
 *   const body = ref<HTMLElement | null>(null);
 *   const content = ref<HTMLElement | null>(null);
 *   const fade = useScrollFade(body, content);     // :style="fade"
 */
import { computed, onBeforeUnmount, onMounted, ref, type Ref } from "vue";

const EDGE = "14px";

/** The mask for a box scrolled `top` px out of `scrollHeight`, showing `clientHeight`. */
export function fadeMask(scrollTop: number, clientHeight: number, scrollHeight: number): string | null {
  const above = scrollTop > 1;
  const below = scrollTop + clientHeight < scrollHeight - 1;
  if (!above && !below) return null;
  return `linear-gradient(to bottom, ${above ? "transparent" : "#000"} 0, #000 ${EDGE}, #000 calc(100% - ${EDGE}), ${below ? "transparent" : "#000"} 100%)`;
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
