/**
 * Items on CalendarMonth and CalendarWeek, in the shape of the company calendar API (plan §13.5:
 * `CalendarItem` = id, kind, title, start, end, all_day, color, url). All-day items carry days
 * ("2026-10-24", `end` inclusive); timed items carry ISO instants shown in the company timezone.
 */
import { addDays, zonedDay } from "@/lib/dates";
import { hashIndex } from "@/lib/format";

export interface CalendarItem {
  id: string | number;
  kind?: string;
  title: string;
  start: string;
  end?: string | null;
  all_day?: boolean;
  /** Any CSS color or token ("var(--c-chart-3)"); default picked from `kind`. */
  color?: string | null;
  url?: string | null;
  /** Second line in the week view and the agenda ("Chilonzor", "Dilnoza"). */
  subtitle?: string;
}

export interface PlacedItem {
  item: CalendarItem;
  /** Continues from the previous day / onto the next day (multi-day all-day items). */
  fromBefore: boolean;
  toAfter: boolean;
}

export function itemColor(item: CalendarItem): string {
  if (item.color) return item.color;
  return `var(--c-chart-${hashIndex(item.kind ?? item.title, 8) + 1})`;
}

/** First and last company-local day an item covers. */
export function itemDays(item: CalendarItem, tz: string): { first: string; last: string } {
  if (item.all_day || /^\d{4}-\d{2}-\d{2}$/.test(item.start)) {
    const first = item.start.slice(0, 10);
    const last = item.end ? item.end.slice(0, 10) : first;
    return { first, last: last < first ? first : last };
  }
  const first = zonedDay(item.start, tz);
  const last = item.end ? zonedDay(item.end, tz) : first;
  return { first, last: last < first ? first : last };
}

/** Items per day for the given days, all-day ones first, then by start time. */
export function itemsByDay(items: readonly CalendarItem[], days: readonly string[], tz: string): Map<string, PlacedItem[]> {
  const map = new Map<string, PlacedItem[]>(days.map((day) => [day, []]));
  const firstDay = days[0];
  const lastDay = days.at(-1);
  if (!firstDay || !lastDay) return map;
  for (const item of items) {
    const { first, last } = itemDays(item, tz);
    if (last < firstDay || first > lastDay) continue;
    for (let day = first < firstDay ? firstDay : first; day <= last && day <= lastDay; day = addDays(day, 1)) {
      map.get(day)?.push({ item, fromBefore: day > first, toAfter: day < last });
    }
  }
  const instant = (item: CalendarItem) => (item.all_day ? 0 : Date.parse(item.start) || 0);
  for (const list of map.values()) {
    list.sort((a, b) => {
      const allDay = Number(!!b.item.all_day) - Number(!!a.item.all_day);
      return allDay || instant(a.item) - instant(b.item);
    });
  }
  return map;
}

export interface TimedBox {
  item: CalendarItem;
  /** Minutes from midnight (company time). */
  start: number;
  end: number;
  column: number;
  columns: number;
}

/**
 * Side-by-side layout of one day's timed items: overlapping items share the width, each cluster of
 * overlaps gets as many columns as it needs at its busiest moment.
 */
export function layoutTimed(items: ReadonlyArray<{ item: CalendarItem; start: number; end: number }>): TimedBox[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.end - a.end);
  const boxes: TimedBox[] = [];
  let cluster: TimedBox[] = [];
  let clusterEnd = -1;
  const flush = () => {
    const columns = Math.max(1, ...cluster.map((box) => box.column + 1));
    for (const box of cluster) box.columns = columns;
    cluster = [];
  };
  for (const entry of sorted) {
    const end = Math.max(entry.end, entry.start + 15);
    if (entry.start >= clusterEnd) flush();
    const used = new Set(cluster.filter((box) => box.end > entry.start).map((box) => box.column));
    let column = 0;
    while (used.has(column)) column += 1;
    const box: TimedBox = { item: entry.item, start: entry.start, end, column, columns: 1 };
    cluster.push(box);
    boxes.push(box);
    clusterEnd = Math.max(clusterEnd, end);
  }
  flush();
  return boxes;
}
