/** Helpers of the company calendar (no Vue, easy to test). */
import { monthGrid, type Month } from "@/components/calendar";
import type { CalendarItem } from "@/components/calendarItems";
import { addDays, startOfWeek, zonedDay } from "@/lib/dates";

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
 * `?event=` for an item: the event's id, plus the occurrence's day for a repeating one
 * ("agenda.events:12-20261027" → "12-20261027"), so the drawer shows the date that was clicked.
 */
export function eventParam(entry: Pick<CalendarEntry, "id" | "kind">): string | null {
  const id = eventIdOf(entry);
  if (!id) return null;
  const match = /-(\d{8})$/.exec(entry.id);
  return match ? `${id}-${match[1]}` : String(id);
}

/** `?event=12` or `?event=12-20261027` → the event's id and the occurrence's day ("2026-10-27"). */
export function parseEventParam(raw: string | null | undefined): { id: number; day: string | null } | null {
  const match = /^(\d+)(?:-(\d{4})(\d{2})(\d{2}))?$/.exec(raw ?? "");
  if (!match) return null;
  const id = Number(match[1]);
  if (!(id > 0)) return null;
  return { id, day: match[2] ? `${match[2]}-${match[3]}-${match[4]}` : null };
}

/**
 * The order calendars take on a crowded day: the company's own events and holidays first, money
 * and milestones next, then who is away and the day's tasks; shifts (every day, every branch) last.
 * A calendar this list doesn't know yet goes just before the tasks.
 */
export const SOURCE_ORDER: readonly string[] = [
  "agenda.events",
  "timeoff.holidays",
  "projects.milestones",
  "finance.debts_due",
  "timeoff.time_off",
  "tasks.due",
  "attendance.shifts",
];

export function sourceRank(source: string): number {
  const index = SOURCE_ORDER.indexOf(source);
  return index >= 0 ? index : SOURCE_ORDER.indexOf("tasks.due") - 0.5;
}

/** Entries in calendar order, then all-day before timed, then by start and title (a new array). */
export function byPriority<T extends Pick<CalendarEntry, "source" | "start" | "all_day" | "title">>(entries: readonly T[]): T[] {
  const instant = (entry: T) => (entry.all_day ? 0 : Date.parse(entry.start) || 0);
  return [...entries].sort(
    (a, b) =>
      sourceRank(a.source) - sourceRank(b.source) ||
      Number(b.all_day) - Number(a.all_day) ||
      instant(a) - instant(b) ||
      a.start.localeCompare(b.start) ||
      a.title.localeCompare(b.title),
  );
}

/** What a month chip shows: its time (timed dates), its title, and the entry it stands for. */
export interface MonthChip {
  time: string | null;
  title: string;
  origin: string;
}

/**
 * The month grid's chips, one per day: a multi-day date (a week of time off) gets a labelled chip
 * on each of its days instead of an unlabelled bar, and timed dates sit in the day's list in
 * calendar order (a 09:00 meeting before the day's shifts), with their time in `meta`. Days
 * outside `from`–`to` are left out.
 */
export function monthChips(
  entries: readonly CalendarEntry[],
  range: { from: string; to: string },
  timeZone: string,
  timeOf: (iso: string) => string,
): { items: CalendarItem[]; meta: Map<string, MonthChip> } {
  const items: CalendarItem[] = [];
  const meta = new Map<string, MonthChip>();
  for (const entry of byPriority(entries)) {
    const base = { kind: entry.kind, color: tokenColor(entry.color), url: entry.url, all_day: true, end: null };
    if (!entry.all_day) {
      const id = entry.id;
      const time = timeOf(entry.start);
      items.push({ ...base, id, title: `${time} · ${entry.title}`, start: zonedDay(entry.start, timeZone) });
      meta.set(id, { time, title: entry.title, origin: entry.id });
      continue;
    }
    const first = entry.start.slice(0, 10);
    const last = entry.end && entry.end.slice(0, 10) > first ? entry.end.slice(0, 10) : first;
    for (let day = first < range.from ? range.from : first; day <= last && day <= range.to; day = addDays(day, 1)) {
      const id = first === last ? entry.id : `${entry.id}@${day}`;
      items.push({ ...base, id, title: entry.title, start: day });
      meta.set(id, { time: null, title: entry.title, origin: entry.id });
    }
  }
  return { items, meta };
}

/**
 * A calendar's colour in its toggle chip. Calendars colour single dates by what they mean (a late
 * day of tasks is red, a payment owed to you green), so the chip takes the calendar's own colour
 * where it has one, else the colour most of its dates in view have.
 */
const SOURCE_TOKENS: Readonly<Record<string, string>> = {
  "tasks.due": "accent",
  "timeoff.time_off": "chart-3",
  "timeoff.holidays": "chart-1",
  "attendance.shifts": "chart-6",
};

export function sourceColor(key: string, entries: readonly Pick<CalendarEntry, "source" | "color">[]): string | null {
  const fixed = SOURCE_TOKENS[key];
  if (fixed) return tokenColor(fixed);
  const counts = new Map<string, number>();
  for (const entry of entries) if (entry.source === key && CALENDAR_TOKENS.has(entry.color)) counts.set(entry.color, (counts.get(entry.color) ?? 0) + 1);
  let best: string | null = null;
  for (const [color, count] of counts) if (best === null || count > counts.get(best)!) best = color;
  return best ? tokenColor(best) : null;
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
