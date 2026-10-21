/** Helpers of the company calendar (no Vue, easy to test). */
import { monthGrid, type Month } from "@/components/calendar";
import type { CalendarItem } from "@/components/calendarItems";
import { addDays, startOfWeek } from "@/lib/dates";

import type { CalendarEntry, CalendarSource, CalendarView, EventKind } from "./types";

/**
 * The colour tokens calendar sources send (the backend's `console.registry.CALENDAR_COLORS`) and
 * the dashboard's CSS variable for each, so every source follows the theme in light and dark.
 */
export const CALENDAR_TOKENS: ReadonlyMap<string, string> = new Map([
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => [`chart-${n}`, `var(--c-chart-${n})`] as const),
  ["danger", "var(--c-danger)"],
  ["warning", "var(--c-warning)"],
  ["success", "var(--c-success)"],
  ["info", "var(--c-info)"],
  ["accent", "var(--c-primary)"],
]);

const warned = new Set<string>();

/**
 * A source's colour token ("chart-3", "danger") as CSS. Anything else (a hex, a CSS variable, an
 * unknown name) is ignored with one console warning per value, so the caller uses its default.
 */
export function tokenColor(color: string | null | undefined): string | null {
  if (!color) return null;
  const css = CALENDAR_TOKENS.get(color);
  if (css) return css;
  if (!warned.has(color)) {
    warned.add(color);
    console.warn(`[calendar] ${JSON.stringify(color)} isn't a colour token; using the default colour`);
  }
  return null;
}

export const KIND_TOKENS: Record<EventKind, string> = {
  meeting: "chart-3",
  training: "chart-6",
  inventory: "chart-4",
  celebration: "chart-5",
  deadline: "danger",
  other: "chart-8",
};

export const EVENT_KINDS: readonly EventKind[] = ["meeting", "training", "inventory", "celebration", "deadline", "other"];

/** Reminder choices, in minutes (null: none). */
export const REMIND_OPTIONS: ReadonlyArray<number | null> = [null, 0, 10, 30, 60, 120, 1440, 4320];

/** The company event an item stands for ("agenda.events:12-20261027" → 12), or null. */
export function eventIdOf(entry: Pick<CalendarEntry, "id" | "kind">): number | null {
  if (entry.kind !== "agenda.event") return null;
  const raw = entry.id.split(":", 2)[1] ?? "";
  const id = Number(raw.split("-", 1)[0]);
  return Number.isFinite(id) && id > 0 ? id : null;
}

/**
 * An API item as CalendarMonth / CalendarWeek draw it: a company event's place, or the name of
 * the calendar a date comes from, on the second line.
 */
/** A source's name: the calendar's own events are named here, so they follow the UI language. */
export function sourceLabel(source: CalendarSource, t: (key: string) => string): string {
  return source.key === "agenda.events" ? t("agenda.sources.own") : source.label;
}

export function toCalendarItem(entry: CalendarEntry, sourceLabel?: string): CalendarItem {
  return {
    id: entry.id,
    kind: entry.kind,
    title: entry.title,
    start: entry.start,
    end: entry.end,
    all_day: entry.all_day,
    color: tokenColor(entry.color),
    url: entry.url,
    subtitle: entry.source === "agenda.events" ? entry.subtitle || undefined : sourceLabel,
  };
}

/** The days a view needs: six weeks for a month, seven days for a week, thirty for the agenda. */
export function windowFor(view: CalendarView, anchor: string): { from: string; to: string } {
  if (view === "month") {
    const weeks = monthGrid(anchor.slice(0, 7) as Month);
    return { from: weeks[0]![0]!, to: weeks[5]![6]! };
  }
  if (view === "week") {
    const monday = startOfWeek(anchor);
    return { from: monday, to: addDays(monday, 6) };
  }
  return { from: anchor, to: addDays(anchor, 29) };
}

/** Minutes as "30 min", "1 h", "1 day" keys for the reminder labels. */
export function remindKey(minutes: number | null): { key: string; n?: number } {
  if (minutes === null) return { key: "agenda.remind.none" };
  if (minutes === 0) return { key: "agenda.remind.atStart" };
  if (minutes % 1440 === 0) return { key: "agenda.remind.days", n: minutes / 1440 };
  if (minutes % 60 === 0) return { key: "agenda.remind.hours", n: minutes / 60 };
  return { key: "agenda.remind.minutes", n: minutes };
}
