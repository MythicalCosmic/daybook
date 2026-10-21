/**
 * `v-truncate-title` on a text cut short with an ellipsis (`truncate`, `line-clamp-*`): when it
 * doesn't fit, it shows whole in a tooltip. Measured when the pointer arrives, so nothing is
 * measured until someone looks, and a text that fits gets no tooltip repeating it.
 *
 *   <span v-truncate-title class="truncate">{{ text }}</span>
 */
import type { Directive } from "vue";

export function syncTruncateTitle(el: HTMLElement): void {
  const cut = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
  const text = el.textContent?.trim() ?? "";
  if (cut && text) el.title = text;
  else el.removeAttribute("title");
}

const onEnter = (event: Event) => syncTruncateTitle(event.currentTarget as HTMLElement);

export const vTruncateTitle: Directive<HTMLElement> = {
  mounted(el) {
    el.addEventListener("pointerenter", onEnter);
  },
  beforeUnmount(el) {
    el.removeEventListener("pointerenter", onEnter);
  },
};
