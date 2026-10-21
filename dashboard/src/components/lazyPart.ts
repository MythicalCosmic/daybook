/**
 * A component kept out of the first load (README "Budgets"): loaded the first time it is needed, or
 * ahead of that by `preloadWhenIdle` once the first page has painted. Its menus and their positioning
 * (reka-ui, floating-ui) are about 25 KB gzipped that no first paint needs.
 *
 *   const menu = lazyPart(() => import("./DropdownMenuPanel.vue"));
 *   menu.current      // the component once loaded, else null
 *   await menu.load() // loads it once; later calls share the promise
 */
import type { Component } from "vue";

export interface LazyPart {
  readonly current: Component | null;
  load(): Promise<Component>;
}

export function lazyPart(importer: () => Promise<{ default: Component }>): LazyPart {
  let current: Component | null = null;
  let pending: Promise<Component> | null = null;
  return {
    get current() {
      return current;
    },
    load() {
      pending ??= importer()
        .then((module) => (current = module.default))
        .catch((error: unknown) => {
          pending = null;
          throw error;
        });
      return pending;
    },
  };
}

/** DropdownMenu's menu (reka-ui). */
export const menuPanel = lazyPart(() => import("./DropdownMenuPanel.vue"));

/**
 * Loads `parts` once the browser has nothing else to do, so the first opening of a menu is
 * instant. Returns a function that cancels it.
 */
export function preloadWhenIdle(parts: readonly LazyPart[]): () => void {
  const run = () => parts.forEach((part) => void part.load().catch(() => undefined));
  if (typeof window === "undefined") return () => undefined;
  if ("requestIdleCallback" in window) {
    const handle = window.requestIdleCallback(run, { timeout: 4000 });
    return () => window.cancelIdleCallback(handle);
  }
  const handle = setTimeout(run, 1500);
  return () => clearTimeout(handle);
}
