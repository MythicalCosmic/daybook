/**
 * Opening the app at a given screen.
 *
 * Two ways in, one vocabulary of names:
 * - a web app button or menu button URL: `/app/?screen=payslip:12` (`<name>:<arg>`, the form
 *   `inbox.Notification.app_screen` and `bot_menu.register_menu_button(web_app_screen=…)` store);
 * - a `t.me/<bot>/<app>?startapp=payslip-12` link: Telegram only allows A–Z, a–z, 0–9, `_` and
 *   `-` there, so the argument follows the first `-` instead of a colon, and `__` stands for the
 *   dot of `<feature>.<page>` (`startapp=wallet__payslip-12`).
 *
 * Built-in names: `home`, `tasks` (`tasks:review` picks a tab), `task:<id>`, `activity`,
 * `profile`, `team`, `add`, `timeOff`, `language`. Feature folders add theirs through `routes`,
 * and `<feature>.<page>:<id>` reaches any feature page.
 */

import { routeTarget, type BuiltIn, type Feature } from "../features/registry";
import { startParam } from "../telegram";
import { CORE, taskPage, type NavigationInit, type TasksTab } from "./navigation";

export type ScreenLink = { name: string; arg: string | null };

const TASKS_TABS: readonly string[] = ["daily", "assigned", "personal", "review"] satisfies TasksTab[];

/** "payslip:12" → {payslip, "12"}; "payslip-12" (startapp form) → the same; "home" → {home, null}. */
export function parseScreen(raw: string, form: "screen" | "startapp" = "screen"): ScreenLink | null {
  const text = raw.trim();
  if (!text) return null;
  const separator = form === "screen" && text.includes(":") ? ":" : form === "startapp" ? "-" : null;
  const at = separator ? text.indexOf(separator) : -1;
  const head = at >= 0 ? text.slice(0, at) : text;
  // Telegram allows no "." in startapp either: "wallet__payslip-12" means "wallet.payslip:12".
  const name = form === "startapp" ? head.replaceAll("__", ".") : head;
  const arg = at >= 0 ? safeDecode(text.slice(at + 1)) : null;
  if (!/^[A-Za-z][\w.]*$/.test(name)) return null;
  return { name, arg: arg === "" ? null : arg };
}

function safeDecode(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

type Source = { search: string; hash: string };

/**
 * The screen the app was opened for, if any: `?screen=` first, then a `startapp` parameter
 * (`?startapp=`, `tgWebAppStartParam` in the URL, or Telegram's `start_param`).
 */
export function readScreenLink(source: Source = window.location, telegramStart: string | null = startParam()): ScreenLink | null {
  const search = new URLSearchParams(source.search);
  const hash = new URLSearchParams(source.hash.replace(/^#/, ""));
  const screen = search.get("screen") ?? hash.get("screen");
  if (screen) return parseScreen(screen, "screen");
  const start = search.get("startapp") ?? search.get("tgWebAppStartParam") ?? hash.get("tgWebAppStartParam") ?? telegramStart;
  return start ? parseScreen(start, "startapp") : null;
}

function builtIn({ name, arg }: ScreenLink): NavigationInit | null {
  const id = arg !== null && /^\d{1,15}$/.test(arg) ? Number(arg) : null;
  switch (name) {
    case "home":
      return { tab: "home" };
    case "tasks":
      return arg && TASKS_TABS.includes(arg) ? { tab: "tasks", tasksTab: arg as TasksTab } : { tab: "tasks" };
    case "task":
      return id !== null ? { tab: "home", stack: [taskPage(id)] } : null;
    case "activity":
      return { tab: "activity" };
    case "profile":
    case "me":
      return { tab: "profile" };
    case "team":
      return { tab: "profile", stack: [{ feature: CORE, page: "team" }] };
    case "add":
      return { tab: "home", sheet: { kind: "add" } };
    case "timeOff":
      return { tab: "profile", sheet: { kind: "timeOff" } };
    case "language":
      return { tab: "profile", sheet: { kind: "language" } };
    default:
      return null;
  }
}

/** Built-in screen names that lead to an entry a feature may take over (`replaces`). */
const TAKEN_OVER: Partial<Record<string, BuiltIn>> = { timeOff: "timeOff", team: "teamResults" };

/** Where a screen link leads, or null for the normal start (unknown names are ignored). */
export function resolveScreen(link: ScreenLink | null, features: readonly Feature[]): NavigationInit | null {
  if (!link) return null;
  try {
    // When a feature takes over a built-in entry, its own route of the same name wins.
    const entry = TAKEN_OVER[link.name];
    if (entry && features.some((feature) => feature.replaces?.includes(entry))) {
      const replacement = routeTarget(features, link.name, link.arg);
      if (replacement) return replacement;
    }
    return builtIn(link) ?? routeTarget(features, link.name, link.arg);
  } catch (error) {
    // A broken feature route must not stop the app from opening.
    console.error("Deep link failed", link, error);
    return null;
  }
}

/** The navigation the app starts with, read from the launch URL. */
export function initialFromLaunch(features: readonly Feature[]): NavigationInit | null {
  return resolveScreen(readScreenLink(), features);
}
