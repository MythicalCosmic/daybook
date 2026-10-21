/**
 * Routines (daily tasks a routine makes, `kind: "daily"`) read apart from one-off work: their own
 * progress for today, finished runs kept in sight, and a manager's checks grouped by routine.
 */

import type { Task } from "../api/types";
import { byDue, isDueToday, type ViewContext } from "./taskView";

/** One day's run of a routine, as opposed to work given once (assigned) or my own (personal). */
export function isRoutine(task: Task): boolean {
  return task.kind === "daily";
}

/** Finished from the person's side: done, or waiting for a check (as Home's numbers count it). */
export function isFinished(task: Task): boolean {
  return task.status === "done" || task.status === "review";
}

/** Today's routines: how many are due today and how many of them are finished. */
export function routineProgress(tasks: readonly Task[], ctx: ViewContext): { done: number; total: number } {
  const today = tasks.filter((task) => isRoutine(task) && task.status !== "cancelled" && isDueToday(task, ctx));
  return { done: today.filter(isFinished).length, total: today.length };
}

/** When the run was finished (or checked, once it was). */
export function finishedAt(task: Task): string | null {
  return task.completed_at ?? task.confirmed_at ?? null;
}

/** Done runs, the latest first. */
export function byFinished(a: Task, b: Task): number {
  return (finishedAt(b) ?? "").localeCompare(finishedAt(a) ?? "") || byDue(a, b);
}

export type RoutineGroup = {
  /** The routine's id, or its title for tasks from before the API named the routine. */
  key: string;
  title: string;
  tasks: Task[];
};

/**
 * Runs waiting for a check, one group per routine (the routine with most runs first), each group's
 * runs in the order they were finished.
 */
export function groupByRoutine(tasks: readonly Task[]): RoutineGroup[] {
  const groups = new Map<string, RoutineGroup>();
  for (const task of tasks) {
    const key = task.routine != null ? `routine:${task.routine}` : `title:${task.title}`;
    const group = groups.get(key) ?? { key, title: task.title, tasks: [] };
    group.tasks.push(task);
    groups.set(key, group);
  }
  return [...groups.values()]
    .map((group) => ({ ...group, tasks: [...group.tasks].sort((a, b) => (finishedAt(a) ?? "").localeCompare(finishedAt(b) ?? "")) }))
    .sort((a, b) => b.tasks.length - a.tasks.length || a.title.localeCompare(b.title));
}
