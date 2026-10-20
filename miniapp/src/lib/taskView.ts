/** How tasks read on screen: glyphs, one-line meta, groups. Pure functions of the API data. */

import type { Task } from "../api/types";
import type { Translate } from "../i18n";
import { clock, daysFromToday, weekdayLong, weekdayShort } from "./time";

export type Glyph = "todo" | "late" | "progress" | "review" | "done";

export type ViewContext = { t: Translate; timeZone: string; locale: string; now: Date };

const OPEN = new Set(["todo", "in_progress", "returned"]);

export function isOpen(task: Task): boolean {
  return OPEN.has(task.status);
}

export function isLate(task: Task, now: Date): boolean {
  return isOpen(task) && task.due_at !== null && new Date(task.due_at) < now;
}

/** Late, or sent back: either way it needs the person's attention first. */
export function needsAttention(task: Task, now: Date): boolean {
  return isLate(task, now) || task.status === "returned";
}

export function glyph(task: Task, now: Date): Glyph {
  if (task.status === "done") return "done";
  if (task.status === "review") return "review";
  if (needsAttention(task, now)) return "late";
  if (task.status === "in_progress") return "progress";
  return "todo";
}

export function lateBy(task: Task, now: Date): number {
  return task.due_at ? Math.max(0, Math.floor((+now - +new Date(task.due_at)) / 60_000)) : 0;
}

export function duration(minutes: number, t: Translate): string {
  if (minutes < 60) return t("duration.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("duration.hours", { hours, minutes: minutes % 60 });
  return t("duration.days", { days: Math.floor(hours / 24), hours: hours % 24 });
}

/** 0 = Monday … 6 = Sunday, as the API sends them. */
export function repeatLabel(weekdays: number[] | null, ctx: ViewContext): string | null {
  if (!weekdays || weekdays.length === 0) return null;
  const days = [...weekdays].sort();
  if (days.length === 7) return ctx.t("repeat.daily");
  if (days.join() === "0,1,2,3,4") return ctx.t("repeat.weekdays");
  // 5 Jan 2026 was a Monday: offset from it to name each weekday in the right language.
  const named = days.map((day) => weekdayName(day, ctx, days.length === 1 ? "long" : "short"));
  return days.length === 1 ? ctx.t("repeat.weekly", { day: named[0] }) : named.join(", ");
}

function weekdayName(day: number, ctx: ViewContext, style: "long" | "short"): string {
  const monday = new Date(Date.UTC(2026, 0, 5 + day, 12));
  return style === "long"
    ? weekdayLong(monday, "UTC", ctx.locale)
    : weekdayShort(monday, "UTC", ctx.locale);
}

/** The short line under a task's title in lists. */
export function rowMeta(task: Task, ctx: ViewContext): string {
  const { t, timeZone, locale, now } = ctx;
  if (task.status === "done") {
    const at = clock(task.confirmed_at ?? task.completed_at ?? task.created_at, timeZone, locale);
    return task.confirmed_by
      ? t("meta.checkedBy", { name: task.confirmed_by.name, time: at })
      : t("meta.doneAt", { time: at });
  }
  if (task.status === "review") {
    return task.kind === "assigned" && task.created_by
      ? t("meta.waitingFor", { name: task.created_by.name })
      : t("meta.waitingCheck");
  }
  if (task.status === "returned") return t("meta.sentBack");
  if (isLate(task, now)) return t("meta.late", { duration: duration(lateBy(task, now), t) });
  const repeat = repeatLabel(task.repeat_weekdays, ctx);
  if (task.kind === "assigned" && task.created_by) return t("meta.from", { name: task.created_by.name });
  if (task.kind === "daily") return repeat ?? t("meta.daily");
  return repeat ?? t("meta.own");
}

/** The time chip on the right of a row: today's time, or the day it's due. */
export function rowRight(task: Task, ctx: ViewContext): string {
  if (!task.due_at) return "";
  const days = daysFromToday(task.due_at, ctx.now, ctx.timeZone);
  if (days === 0) return clock(task.due_at, ctx.timeZone, ctx.locale);
  if (days === 1) return ctx.t("day.tomorrow");
  return weekdayShort(task.due_at, ctx.timeZone, ctx.locale);
}

export function isDueToday(task: Task, ctx: ViewContext): boolean {
  return task.due_at !== null && daysFromToday(task.due_at, ctx.now, ctx.timeZone) === 0;
}

export type Group = { key: "attention" | "todo" | "review" | "done"; tasks: Task[] };

/** Sort by deadline, undated last. */
export function byDue(a: Task, b: Task): number {
  const left = a.due_at ? +new Date(a.due_at) : Number.MAX_SAFE_INTEGER;
  const right = b.due_at ? +new Date(b.due_at) : Number.MAX_SAFE_INTEGER;
  return left - right || a.id - b.id;
}

export function groupTasks(tasks: Task[], now: Date): Group[] {
  const groups: Group[] = [
    { key: "attention", tasks: tasks.filter((task) => needsAttention(task, now)) },
    {
      key: "todo",
      tasks: tasks.filter((task) => isOpen(task) && !needsAttention(task, now)),
    },
    { key: "review", tasks: tasks.filter((task) => task.status === "review") },
    { key: "done", tasks: tasks.filter((task) => task.status === "done") },
  ];
  return groups
    .map((group) => ({ ...group, tasks: [...group.tasks].sort(byDue) }))
    .filter((group) => group.tasks.length > 0);
}
