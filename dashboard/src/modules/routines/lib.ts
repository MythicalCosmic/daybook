/**
 * When a routine's tasks come, in words. The server says it for saved routines (`next_run`, by
 * `apps.tasks.generation`'s rules, holidays included); `nextRunOf` mirrors the day rules for the
 * editor's live hint, without company holidays, which only the server knows.
 */
import { TZDate } from "@date-fns/tz";
import { AlarmClock, CircleCheck, CircleDashed, CircleSlash, Hourglass, RotateCcw, TriangleAlert } from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";
import { addDays, diffDays, parseDay, todayIn, zonedDay } from "@/lib/dates";

import type { RoutineRun, RunState } from "./types";

type T = (key: string, params?: Record<string, unknown>, plural?: number) => string;

/** How a run's state reads: its tone and icon (late and missed are the ones to act on). */
export const RUN_LOOK: Record<RunState, { tone: StatusTone; icon: Component }> = {
  done: { tone: "success", icon: CircleCheck },
  review: { tone: "warning", icon: Hourglass },
  late: { tone: "danger", icon: AlarmClock },
  missed: { tone: "danger", icon: TriangleAlert },
  returned: { tone: "warning", icon: RotateCcw },
  open: { tone: "neutral", icon: CircleDashed },
  cancelled: { tone: "neutral", icon: CircleSlash },
};

/** "Done 08:50", "Done 09:35 · late", "Waiting · done 09:20", "Late · due 09:00", "To do · due 18:00". */
export function runText(run: RoutineRun, t: T, time: (iso: string) => string): string {
  const due = run.due_at ? time(run.due_at) : "—";
  const done = run.completed_at ? time(run.completed_at) : "—";
  switch (run.state) {
    case "done":
      return t(run.on_time === false ? "routines.runState.doneLate" : "routines.runState.done", { time: done });
    case "review":
      return t("routines.runState.review", { time: done });
    case "cancelled":
      return t("routines.runState.cancelled");
    default:
      return t(`routines.runState.${run.state}`, { time: due });
  }
}

/** A whole percent of `whole` that reads 100 only when all of it is done and 0 only when none is
 * (537 of 539 is 99, not a rounded-up 100), as the server rounds Today's and History's rates. */
export function share(part: number, whole: number): number | null {
  if (!whole) return null;
  let value = Math.round((100 * part) / whole);
  if (part < whole) value = Math.min(value, 99);
  if (part > 0) value = Math.max(value, 1);
  return value;
}

/** A percent with decimals shown whole by the same rule: 99.6 reads 99, 0.3 reads 1. */
export function wholePercent(value: number): number {
  const rounded = Math.round(value);
  if (value < 100 && rounded >= 100) return 99;
  if (value > 0 && rounded <= 0) return 1;
  return rounded;
}

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

/**
 * The note on a day a routine skipped because it was made after that day's deadline. Today: when it
 * starts by itself, and whether today's task already went out by hand (`given`) or can still be
 * given (`give`, "Give today's task now"). An earlier day: no task that day, unless one was given
 * by hand (then its runs say enough and there is no note).
 */
export function madeLateNote(
  routine: { due_time: string; next_run: string | null },
  day: { past: boolean; given: number; give: { people: number } | null },
  words: RunWords,
): { title: string; body: string } | null {
  const { t } = words;
  const due = routine.due_time.slice(0, 5);
  if (day.past) return day.given > 0 ? null : { title: t("routines.preview.madeLate", { time: due }), body: "" };
  const starts = routine.next_run ? runDayWords(routine.next_run, words) : null;
  const title = starts ? capitalize(t("routines.give.title", { day: starts })) : t("routines.give.titleLater");
  const more = day.give?.people ?? 0;
  if (day.given > 0) return { title, body: more ? t("routines.give.givenMoreBody", { due, n: more }, more) : t("routines.give.givenBody", { due }) };
  return { title, body: more ? t("routines.give.detailBody", { due, n: more }, more) : t("routines.give.detailBodyNobody", { due }) };
}

/** "dushanba kuni boshlanadi" → "Dushanba kuni boshlanadi": a phrase that starts with run words. */
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Whether an instant falls on the company's today. */
export function isToday(iso: string, timeZone: string, now: number): boolean {
  return zonedDay(iso, timeZone) === todayIn(timeZone, now);
}
