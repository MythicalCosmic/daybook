/**
 * Charts draw on a canvas, which can't read CSS variables. `useCssColor()` turns "var(--c-success)"
 * into the browser's color for the current theme and follows light/dark switches, so chart series
 * keep using the design tokens.
 */
import { nextTick, ref, watch } from "vue";

import { useUiStore } from "@/stores/ui";

export function resolveCssColor(value: string): string {
  if (!value.startsWith("var(") || typeof document === "undefined" || !document.body) return value;
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = value;
  document.body.appendChild(probe);
  try {
    const color = getComputedStyle(probe).color;
    return color && !color.startsWith("var(") ? color : value;
  } finally {
    probe.remove();
  }
}

export function useCssColor(): (value: string) => string {
  const ui = useUiStore();
  const version = ref(0);
  const cache = new Map<string, string>();
  watch(
    () => ui.theme,
    () =>
      void nextTick(() => {
        cache.clear();
        version.value += 1;
      }),
  );
  return (value: string) => {
    void version.value;
    let color = cache.get(value);
    if (color === undefined) {
      color = resolveCssColor(value);
      cache.set(value, color);
    }
    return color;
  };
}
