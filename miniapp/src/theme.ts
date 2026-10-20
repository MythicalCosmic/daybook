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

export function applyTheme(mode: ThemeMode): void {
  const dark = mode === "dark" || (mode === "auto" && colorScheme() === "dark");
  const theme = dark ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  paintChrome(GROUND[theme]);
}
