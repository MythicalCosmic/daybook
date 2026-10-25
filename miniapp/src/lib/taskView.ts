/** How tasks read on screen: glyphs, one-line meta, groups. Pure functions of the API data. */

import type { Task } from "../api/types";
import type { Translate } from "../i18n";
import { capitalise, clock, dayMonth, dayMonthLong, daysFromToday, weekdayLong, weekdayShort } from "./time";

export type Glyph = "todo" | "late" | "progress" | "review" | "done";

/** `currency`: the company's base currency, for rewards (UZS when not given). */
export type ViewContext = { t: Translate; timeZone: string; locale: string; now: Date; currency?: string };

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
  // Past a day the hours matter less, and "14 d 0 h" reads as noise.
  const days = Math.floor(hours / 24);
  if (days >= 2 || hours % 24 === 0) return t("duration.daysOnly", { days });
  return t("duration.days", { days, hours: hours % 24 });
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

/** Why the task can't be done, in words; a reason this app doesn't know yet reads as "Other". */
export function blockerReason(code: string, t: Translate): string {
  const key = `blocker.reason.${code}`;
  const text = t(key as Parameters<Translate>[0]);
  return text === key ? t("blocker.reason.other") : text;
}

/** The short line under a task's title in lists. */
export function rowMeta(task: Task, ctx: ViewContext): string {
  const { t, timeZone, locale, now } = ctx;
  if (task.status === "done") {
    const at = clock(task.confirmed_at ?? task.completed_at ?? task.created_at, timeZone, locale);
    return task.confirmed_by
      ? t("meta.checkedBy", { name: task.confirmed_by.name, time: at })
      : task.accepted_automatically
        ? t("meta.acceptedAt", { time: at })
        : t("meta.doneAt", { time: at });
  }
  if (task.status === "review") {
    return task.kind === "assigned" && task.created_by
      ? t("meta.waitingFor", { name: task.created_by.name })
      : t("meta.waitingCheck");
  }
  if (task.status === "returned") return t("meta.sentBack");
  // The reason continues the sentence after the colon: lowercase ("Can't be done: out of stock").
  if (task.blocker) return t("meta.blocked", { reason: blockerReason(task.blocker.reason_code, t).toLocaleLowerCase() });
  if (isLate(task, now)) return t("meta.late", { duration: duration(lateBy(task, now), t) });
  if (task.extension) return t("meta.extension");
  const repeat = repeatLabel(task.repeat_weekdays, ctx);
  // Started work says so: it otherwise differs from to-do only by the glyph's dot (audit M-7).
  const started = task.status === "in_progress" ? `${t("status.in_progress")} · ` : "";
  if (task.kind === "assigned" && task.created_by) return started + t("meta.from", { name: task.created_by.name });
  if (task.kind === "daily") return started + (repeat ?? t("meta.daily"));
  return started + (repeat ?? t("meta.own"));
}

/** Minutes before the deadline when the time chip turns into a countdown ("25 min left"). */
export const SOON_MINUTES = 60;

/** Minutes until the deadline of open work due within the hour, else null. */
export function minutesLeft(task: Task, now: Date): number | null {
  if (!isOpen(task) || !task.due_at) return null;
  const left = Math.ceil((+new Date(task.due_at) - +now) / 60_000);
  return left > 0 && left <= SOON_MINUTES ? left : null;
}

/**
 * The time chip on the right of a row: a countdown inside the last hour, today's time, "Tomorrow"
 * or "Yesterday", the weekday within a week either way, and the date further out (a weekday alone
 * would be ambiguous).
 */
export function rowRight(task: Task, ctx: ViewContext): string {
  if (!task.due_at) return "";
  const left = minutesLeft(task, ctx.now);
  if (left !== null) return ctx.t("due.left", { duration: duration(left, ctx.t) });
  const days = daysFromToday(task.due_at, ctx.now, ctx.timeZone);
  if (days === 0) return clock(task.due_at, ctx.timeZone, ctx.locale);
  if (days === 1) return ctx.t("day.tomorrow");
  if (days === -1) return ctx.t("day.yesterday");
  if (Math.abs(days) < 7) return weekday(task.due_at, ctx);
  return dayMonth(task.due_at, ctx.timeZone, ctx.locale);
}

/** The weekday on a chip: Uzbek spells it out ("Pay" would read as the English word). */
function weekday(moment: string, ctx: ViewContext): string {
  return ctx.locale.startsWith("uz")
    ? capitalise(weekdayLong(moment, ctx.timeZone, ctx.locale))
    : capitalise(weekdayShort(moment, ctx.timeZone, ctx.locale));
}

/**
 * A deadline as a value that starts a line: "Bugun, 18:30", "Ertaga, 09:00", then the weekday with
 * the date ("Payshanba, 29-oktabr, 18:30", "Чт 29 окт., 18:30", "Thu 29 Oct, 18:30"). Inside a
 * sentence (after a colon) Uzbek and Russian keep the day lowercase: "Muddat: bugun, 18:30".
 */
export function formatDue(moment: string, ctx: ViewContext, inSentence = false): string {
  const time = clock(moment, ctx.timeZone, ctx.locale);
  const days = daysFromToday(moment, ctx.now, ctx.timeZone);
  const lower = (text: string) => (inSentence ? text.charAt(0).toLocaleLowerCase() + text.slice(1) : text);
  if (days === 0) return `${lower(ctx.t("day.today"))}, ${time}`;
  if (days === 1) return `${lower(ctx.t("day.tomorrow"))}, ${time}`;
  if (ctx.locale.startsWith("uz")) return `${lower(weekday(moment, ctx))}, ${dayMonthLong(moment, ctx.timeZone, ctx.locale)}, ${time}`;
  // English weekday names keep their capital in a sentence too.
  const day = ctx.locale.startsWith("en") ? weekday(moment, ctx) : lower(weekday(moment, ctx));
  return `${day} ${dayMonth(moment, ctx.timeZone, ctx.locale)}, ${time}`;
}

export function isDueToday(task: Task, ctx: ViewContext): boolean {
  return task.due_at !== null && daysFromToday(task.due_at, ctx.now, ctx.timeZone) === 0;
}

/**
 * Priority as phones show it (R2 T19/T20): "Urgent" with its flag, a quiet flag for high, and
 * nothing for normal and low (four levels are a dashboard detail).
 */
export function priorityLevel(task: Pick<Task, "priority">): "urgent" | "high" | null {
  return task.priority === "urgent" ? "urgent" : task.priority === "high" ? "high" : null;
}

export type Group = { key: "attention" | "todo" | "review" | "done"; tasks: Task[] };

/** Sort by deadline, undated last. */
export function byDue(a: Task, b: Task): number {
  const left = a.due_at ? +new Date(a.due_at) : Number.MAX_SAFE_INTEGER;
  const right = b.due_at ? +new Date(b.due_at) : Number.MAX_SAFE_INTEGER;
  return left - right || a.id - b.id;
}

/**
 * One order everywhere (R2 T7): late, then sent back, then urgent, then the soonest deadline,
 * undated work last. The bot's /tasks and the dashboard read work in the same order.
 */
export function byFocus(now: Date): (a: Task, b: Task) => number {
  const rank = (task: Task) => (isLate(task, now) ? 0 : task.status === "returned" ? 1 : 2);
  const urgency = (task: Task) => (task.priority === "urgent" ? 0 : 1);
  return (a, b) => rank(a) - rank(b) || urgency(a) - urgency(b) || byDue(a, b);
}

export function groupTasks(tasks: Task[], now: Date): Group[] {
  const focus = byFocus(now);
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
    .map((group) => ({ ...group, tasks: [...group.tasks].sort(group.key === "attention" || group.key === "todo" ? focus : byDue) }))
    .filter((group) => group.tasks.length > 0);
}

export type DayGroup = { key: "attention" | "today" | "tomorrow" | "soon" | "later" | "noDue" | "review" | "done"; tasks: Task[] };

/**
 * Work by when it's due (audit M-7): what needs attention, then today, tomorrow, the next few
 * days, later (shown folded), undated; then work being checked and today's finished. A list of
 * fifteen with inventory counts weeks away no longer buries today's work.
 */
export function groupByDay(tasks: Task[], ctx: ViewContext): DayGroup[] {
  const focus = byFocus(ctx.now);
  const open = tasks.filter((task) => isOpen(task) && !needsAttention(task, ctx.now));
  const day = (task: Task) => (task.due_at ? daysFromToday(task.due_at, ctx.now, ctx.timeZone) : null);
  const groups: DayGroup[] = [
    { key: "attention", tasks: tasks.filter((task) => needsAttention(task, ctx.now)) },
    { key: "today", tasks: open.filter((task) => day(task) !== null && day(task)! <= 0) },
    { key: "tomorrow", tasks: open.filter((task) => day(task) === 1) },
    { key: "soon", tasks: open.filter((task) => day(task) !== null && day(task)! >= 2 && day(task)! <= 6) },
    { key: "later", tasks: open.filter((task) => day(task) !== null && day(task)! >= 7) },
    { key: "noDue", tasks: open.filter((task) => day(task) === null) },
    { key: "review", tasks: tasks.filter((task) => task.status === "review") },
    { key: "done", tasks: tasks.filter((task) => task.status === "done") },
  ];
  return groups
    .map((group) => ({ ...group, tasks: [...group.tasks].sort(group.key === "review" || group.key === "done" ? byDue : focus) }))
    .filter((group) => group.tasks.length > 0);
}

/** "09:12" today, "21-okt, 09:12" on another day: when something happened, said briefly. */
export function shortMoment(moment: string, ctx: ViewContext): string {
  const time = clock(moment, ctx.timeZone, ctx.locale);
  return daysFromToday(moment, ctx.now, ctx.timeZone) === 0 ? time : `${dayMonth(moment, ctx.timeZone, ctx.locale)}, ${time}`;
}

/**
 * Whether the assignee has opened work someone gave them (R2 T36), as the giver reads it. Null
 * when there is nothing to say: the backend doesn't send it yet, or the work isn't assigned.
 */
export function seenLabel(task: Task, ctx: ViewContext): string | null {
  if (task.seen_at === undefined || task.kind !== "assigned") return null;
  if (task.seen_at) return ctx.t("seen.at", { time: shortMoment(task.seen_at, ctx) });
  return isOpen(task) ? ctx.t("seen.not") : null;
}
