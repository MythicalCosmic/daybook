/** Small helpers of the calendar feature. */
import { addDays, clock, dayKey, weekdayLong } from "../../lib/time";
import type { CalendarEntry } from "./api";

const TOKENS = new Set(["chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "chart-6", "chart-7", "chart-8", "danger", "success", "primary", "warning", "info"]);

/** The colour class of a source's token ("chart-3" → "agm-c-chart-3"). */
export function colorClass(token: string): string {
  return TOKENS.has(token) ? `agm-c-${token}` : "agm-c-chart-1";
}

/** Monday of the week a day is in (weeks start on Monday, like the backend). */
export function mondayOf(key: string): string {
  const date = new Date(`${key}T12:00:00Z`);
  const shift = (date.getUTCDay() + 6) % 7;
  return addDays(key, -shift);
}

/** Days of the week starting at `monday`. */
export function weekDays(monday: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

/** Items per day for the given days (all-day ones first, then by time). */
export function byDay(items: readonly CalendarEntry[], days: readonly string[], timeZone: string): Map<string, CalendarEntry[]> {
  const map = new Map<string, CalendarEntry[]>(days.map((day) => [day, []]));
  for (const item of items) {
    const first = item.all_day ? item.start.slice(0, 10) : dayKey(item.start, timeZone);
    const last = item.all_day ? (item.end ?? item.start).slice(0, 10) : first;
    for (const day of days) if (day >= first && day <= last) map.get(day)!.push(item);
  }
  for (const list of map.values()) {
    list.sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
  }
  return map;
}

/** "09:00 – 09:30", or "All day". */
export function timeLabel(item: CalendarEntry, timeZone: string, locale: string, allDay: string): string {
  if (item.all_day) return allDay;
  const start = clock(item.start, timeZone, locale);
  return item.end ? `${start} – ${clock(item.end, timeZone, locale)}` : start;
}

/** A day's name for headers: "Today", "Tomorrow", or "Thursday". */
export function dayName(key: string, today: string, timeZone: string, locale: string, words: { today: string; tomorrow: string }): string {
  if (key === today) return words.today;
  if (key === addDays(today, 1)) return words.tomorrow;
  const name = weekdayLong(`${key}T12:00:00Z`, timeZone, locale);
  return name.charAt(0).toUpperCase() + name.slice(1);
}
