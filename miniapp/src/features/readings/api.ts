/**
 * Storage readings on a routine's task (PLAN-OWNER §14.10), typed by hand from
 * `apps/tasks/api.py` until the regenerated schema has them: what the task asks for
 * (`readings`), what was typed in (`readings_taken`, rechecks included) and until when a second
 * measurement may come (`recheck_until`). Values and ranges are decimal strings ("5.2").
 */
import { api } from "../../api/client";
import type { Task } from "../../api/types";

/** One number a readings task asks for, with its allowed range (null: no bound that side). */
export type ReadingSpec = {
  key: string;
  label: string;
  unit: string;
  min: string | null;
  max: string | null;
  critical: boolean;
};

/** A value typed in, held to the range it had then. */
export type ReadingTaken = {
  id: number;
  key: string;
  label: string;
  unit: string;
  value: string;
  min: string | null;
  max: string | null;
  in_range: boolean;
  note: string;
  is_recheck: boolean;
  recorded_at: string;
  recorded_by: { id: number; name: string } | null;
};

/** A task as the readings block reads it: the generated Task doesn't know `readings` yet. */
export type ReadingsTask = Omit<Task, "proof"> & {
  proof: Task["proof"] | "readings";
  readings?: ReadingSpec[];
  readings_taken?: ReadingTaken[];
  recheck_until?: string | null;
};

export function asReadingsTask(task: Task): ReadingsTask {
  return task as unknown as ReadingsTask;
}

export function takesReadings(task: Task): boolean {
  const own = asReadingsTask(task);
  return own.proof === "readings" && (own.readings?.length ?? 0) > 0;
}

const taskPath = (company: number, taskId: number) => `/companies/${company}/tasks/${taskId}`;

/** Finish the task with a value per key ("5,2" as typed) and, out of range, what was done. */
export const completeWithReadings = (company: number, taskId: number, readings: Record<string, string>, note: string) =>
  api<Task>(`${taskPath(company, taskId)}/complete/`, { method: "POST", json: { readings, reading_note: note } });

/** The second measurement after something was done about a value out of range. */
export const recheckReadings = (company: number, taskId: number, readings: Record<string, string>, note: string) =>
  api<Task>(`${taskPath(company, taskId)}/recheck/`, { method: "POST", json: { readings, note } });
