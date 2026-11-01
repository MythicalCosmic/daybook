import { colorScheme, paintChrome } from "./telegram";

export type ThemeMode = "auto" | "light" | "dark";

const STORAGE_KEY = "daybook.theme";
// The ground color in each theme, as Telegram's header API wants a plain hex.
const GROUND = { light: "#f5ead8", dark: "#24221d" };

export function savedThemeMode(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : "auto";
  } catch {
    return "auto";
  }
}

export function saveThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Private mode or blocked storage: the choice just won't survive a reload.
  }
}

const repainters = new Set<() => void>();

/**
 * Run `repaint` whenever the theme changes (Telegram switched to night mode, or Me's theme was
 * picked): what draws with the theme's colours outside CSS, such as Telegram's own buttons, takes
 * the new ones. Returns the function that stops it.
 */
export function onThemeApplied(repaint: () => void): () => void {
  repainters.add(repaint);
  return () => repainters.delete(repaint);
}

export function applyTheme(mode: ThemeMode): void {
  const dark = mode === "dark" || (mode === "auto" && colorScheme() === "dark");
  const theme = dark ? "dark" : "light";
  const changed = document.documentElement.dataset.theme !== theme;
  document.documentElement.dataset.theme = theme;
  paintChrome(GROUND[theme]);
  if (changed) repainters.forEach((repaint) => repaint());
}

// Telegram's native buttons take plain hex too: the accent and surface of each theme.
const ACCENT = "#c67139";
const SURFACE = { light: "#ebddc5", dark: "#2e2b25" };
const TEXT = { light: "#201e1d", dark: "#f5ead8" };

/** Colors for Telegram's main and secondary buttons, matching the in-page primary and secondary ones. */
export function nativeButtonColors(kind: "main" | "secondary"): { color: string; textColor: string } {
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  return kind === "main" ? { color: ACCENT, textColor: GROUND[theme] } : { color: SURFACE[theme], textColor: TEXT[theme] };
}
