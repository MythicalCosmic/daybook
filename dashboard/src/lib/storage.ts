/**
 * Per-browser conveniences (theme, sidebar, density, last company). Storage can be missing or throw
 * (private mode, blocked site data, Telegram webviews), so every access is guarded and the app
 * works the same without it.
 */
const PREFIX = "daybook.console.";

export function readStored<T>(key: string, fallback: T, guard?: (value: unknown) => value is T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const value = JSON.parse(raw) as unknown;
    if (guard && !guard(value)) return fallback;
    return value as T;
  } catch {
    return fallback;
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    if (value === undefined || value === null) window.localStorage.removeItem(PREFIX + key);
    else window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Storage blocked: the choice simply won't survive a reload.
  }
}

export const isString = (value: unknown): value is string => typeof value === "string";
export const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
export const isBoolean = (value: unknown): value is boolean => typeof value === "boolean";
export const oneOf =
  <T extends string>(...allowed: readonly T[]) =>
  (value: unknown): value is T =>
    typeof value === "string" && (allowed as readonly string[]).includes(value);
