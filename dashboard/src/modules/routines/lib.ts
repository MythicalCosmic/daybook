/**
 * When a routine's tasks come, in words. The server says it for saved routines (`next_run`, by
 * `apps.tasks.generation`'s rules, holidays included); `nextRunOf` mirrors the day rules for the
 * editor's live hint, without company holidays, which only the server knows.
 */
import { TZDate } from "@date-fns/tz";

import { addDays, diffDays, parseDay, todayIn, zonedDay } from "@/lib/dates";

type T = (key: string, params?: Record<string, unknown>) => string;

/** Monday = 0 … Sunday = 6, of a company-local day ("2026-10-21"). */
export function weekdayOf(day: string): number {
  return (parseDay(day).getUTCDay() + 6) % 7;
}

/** A company-local day and wall-clock time ("2026-10-21", "09:00") as an ISO instant. */
export function zonedIso(day: string, time: string, timeZone: string): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const [hour, minute] = time.split(":").map(Number) as [number, number];
  return new TZDate(year, month - 1, date, hour, minute, timeZone).toISOString();
}

export interface RunDraft {
  weekdays: number[];
  /** "09:00" or "09:00:00" */
  due_time: string | null;
  starts_on: string | null;
  is_active?: boolean;
  onboarding?: boolean;
}

/**
 * The deadline of a routine's next tasks after `now`: the first of its days (on or after its start)
 * whose due time is still ahead. Null when paused, onboarding or nothing is picked yet.
 */
export function nextRunOf(draft: RunDraft, now: Date | number, timeZone: string, horizon = 31): string | null {
  if (draft.is_active === false || draft.onboarding || !draft.weekdays.length || !draft.due_time) return null;
  const nowMs = typeof now === "number" ? now : now.getTime();
  const today = todayIn(timeZone, nowMs);
  const first = draft.starts_on && draft.starts_on > today ? draft.starts_on : today;
  for (let offset = 0; offset <= horizon; offset += 1) {
    const day = addDays(first, offset);
    if (!draft.weekdays.includes(weekdayOf(day))) continue;
    const due = new Date(zonedIso(day, draft.due_time.slice(0, 5), timeZone));
    if (due.getTime() > nowMs) return due.toISOString();
  }
  return null;
}

/**
 * A routine made now misses today: today is one of its days (and it has started) but today's due
 * time has passed. Its first tasks come the next day it's due; today's can still be given by hand.
 */
export function missesToday(draft: RunDraft, now: Date | number, timeZone: string): boolean {
  if (draft.is_active === false || draft.onboarding || !draft.due_time) return false;
  const nowMs = typeof now === "number" ? now : now.getTime();
  const today = todayIn(timeZone, nowMs);
  if (!draft.weekdays.includes(weekdayOf(today)) || (draft.starts_on && draft.starts_on > today)) return false;
  return new Date(zonedIso(today, draft.due_time.slice(0, 5), timeZone)).getTime() <= nowMs;
}

export interface RunWords {
  t: T;
  timeZone: string;
  now: number;
  /** "09:00" of an instant, in the company's zone. */
  time: (iso: string) => string;
  /** "3 Nov" of a company-local day. */
  day: (day: string) => string;
}

/** "Today 13:00", "Tomorrow 09:00", "Thu 09:00" (this week), "3 Nov, 09:00". */
export function runLabel(iso: string, words: RunWords): string {
  const day = zonedDay(iso, words.timeZone);
  const ahead = diffDays(todayIn(words.timeZone, words.now), day);
  const time = words.time(iso);
  if (ahead === 0) return words.t("routines.run.today", { time });
  if (ahead === 1) return words.t("routines.run.tomorrow", { time });
  if (ahead > 1 && ahead < 7) return words.t("routines.run.weekday", { day: words.t(`routines.weekday.${weekdayOf(day)}`), time });
  return words.t("routines.run.date", { day: words.day(day), time });
}

/** The day alone, to finish "it starts …": "today", "tomorrow", "on Thursday", "on 3 Nov". */
export function runDayWords(iso: string, words: RunWords): string {
  const day = zonedDay(iso, words.timeZone);
  const ahead = diffDays(todayIn(words.timeZone, words.now), day);
  if (ahead === 0) return words.t("routines.runDay.today");
  if (ahead === 1) return words.t("routines.runDay.tomorrow");
  if (ahead > 1 && ahead < 7) return words.t(`routines.runDay.weekday.${weekdayOf(day)}`);
  return words.t("routines.runDay.date", { day: words.day(day) });
}

/**
 * What saving a routine says next: a new one made after today's deadline opens the "it starts …,
 * give today's task now?" dialog; an edit of one whose today's task can still go out offers it in
 * the toast; anything else is a plain toast (with when its first or next tasks come).
 */
export function afterSave(
  routine: { onboarding: boolean; today: { reason: string | null; give: unknown } | null },
  created: boolean,
): "dialog" | "offer" | "plain" {
  if (routine.onboarding) return "plain";
  if (created && routine.today?.reason === "made_late") return "dialog";
  if (routine.today?.give) return "offer";
  return "plain";
}

/** "dushanba kuni boshlanadi" → "Dushanba kuni boshlanadi": a phrase that starts with run words. */
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Whether an instant falls on the company's today. */
export function isToday(iso: string, timeZone: string, now: number): boolean {
  return zonedDay(iso, timeZone) === todayIn(timeZone, now);
}
