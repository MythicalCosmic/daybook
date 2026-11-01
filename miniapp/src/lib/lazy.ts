import { lazy, type ComponentType, type LazyExoticComponent } from "react";

/** A screen loaded on first use, whose code can be fetched before that (`preload`). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- the same bound as React.lazy's
export type Preloadable<T extends ComponentType<any>> = LazyExoticComponent<T> & { preload: () => Promise<unknown> };

/**
 * `React.lazy` with a way to start loading early: a screen the person is likely to open next
 * (a task, Me) is fetched while the browser is idle, so opening it shows no placeholder.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- the same bound as React.lazy's
export function lazyScreen<T extends ComponentType<any>>(load: () => Promise<{ default: T }>): Preloadable<T> {
  let loading: Promise<{ default: T }> | null = null;
  const start = () => (loading ??= load());
  return Object.assign(lazy(start), { preload: start });
}

/** Run `work` once the browser has nothing better to do (or after `timeout` ms at the latest). */
export function whenIdle(work: () => void, timeout = 2000): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(work, { timeout });
    return () => window.cancelIdleCallback(handle);
  }
  const timer = window.setTimeout(work, 600);
  return () => window.clearTimeout(timer);
}
