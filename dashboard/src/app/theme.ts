/**
 * Applies the theme to <html data-theme>, density to <html data-density> and reduced motion to
 * <html data-motion>. A theme switch started from a click reveals the new theme in a circle from
 * the pointer (View Transitions), or just swaps where that isn't supported or motion is reduced.
 */
import { watch } from "vue";

import { useUiStore, type Theme, type ThemeMode } from "@/stores/ui";

const THEME_COLOR: Record<Theme, string> = { light: "#f7f3ec", dark: "#141210" };

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function paint(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) meta.content = THEME_COLOR[theme];
}

/** Keeps <html> in sync with the UI store. Call once at startup. */
export function installTheme(): void {
  const ui = useUiStore();
  const root = document.documentElement;
  watch(() => ui.theme, paint, { immediate: true });
  watch(() => ui.density, (density) => (root.dataset.density = density), { immediate: true });

  const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const applyMotion = () => (root.dataset.motion = motion?.matches ? "reduced" : "full");
  applyMotion();
  motion?.addEventListener?.("change", applyMotion);
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => { ready: Promise<void>; finished: Promise<void> };
};

/**
 * Switches theme mode; with a pointer position, the new theme grows from that point as a circle.
 */
export function switchTheme(mode: ThemeMode, origin?: { x: number; y: number }): void {
  const ui = useUiStore();
  const before = ui.theme;
  const doc = document as ViewTransitionDocument;
  const apply = () => {
    ui.setThemeMode(mode);
    paint(ui.theme);
  };
  const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const next: Theme = mode === "system" ? (ui.telegramTheme ?? (systemDark ? "dark" : "light")) : mode;
  if (!origin || next === before || !doc.startViewTransition || prefersReducedMotion()) {
    apply();
    return;
  }
  const transition = doc.startViewTransition(apply);
  const radius = Math.hypot(Math.max(origin.x, window.innerWidth - origin.x), Math.max(origin.y, window.innerHeight - origin.y));
  void transition.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${origin.x}px ${origin.y}px)`, `circle(${radius}px at ${origin.x}px ${origin.y}px)`] },
      { duration: 420, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)", pseudoElement: "::view-transition-new(root)" },
    );
  });
}

/** Flips between light and dark from wherever the click happened. */
export function toggleTheme(event?: MouseEvent): void {
  const ui = useUiStore();
  const next: ThemeMode = ui.theme === "dark" ? "light" : "dark";
  const origin = event && event.clientX + event.clientY > 0 ? { x: event.clientX, y: event.clientY } : undefined;
  switchTheme(next, origin);
}
