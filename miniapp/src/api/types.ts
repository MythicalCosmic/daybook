import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Membership = Schemas["Membership"];
export type Position = Schemas["Position"];
export type TaskStatus = Schemas["TaskStatusEnum"];
export type Priority = Schemas["PriorityEnum"];

/** Why the person can't do the task (`POST tasks/{id}/blocker/`). */
export type BlockerReason = "no_stock" | "no_access" | "broken" | "not_mine" | "other";
export type Blocker = { reason_code: BlockerReason; note: string; at: string };
/** A pending request for more time (`POST tasks/{id}/extension/`). */
export type Extension = { until: string; note: string; at: string };

/**
 * A task as the app reads it: the schema's, plus what the task-management pass adds to the
 * serializer (snooze choices, blockers, more time, seen receipts). They stay optional until the
 * schema is regenerated, and a field the backend doesn't send yet is `undefined`, never `null`:
 * the screens hide what the backend can't tell rather than claim "not seen".
 */
export type Task = Schemas["Task"] & {
  snoozed_until?: string | null;
  blocker?: Blocker | null;
  extension?: Extension | null;
  seen_at?: string | null;
};

/** `POST tasks/parse/`: what quick add read in the typed text (nothing is saved). */
export type QuickAdd = {
  title: string;
  due_at: string | null;
  /** Ready to show in the person's language: "Ertaga, 22-oktabr (payshanba), 18:00". */
  due_label: string | null;
  priority: Priority | null;
  repeat: Exclude<Schemas["RepeatEnum"], "none"> | null;
  repeat_weekdays?: number[] | null;
};

export type SnoozePreset = "15m" | "1h" | "tomorrow_morning";
export type BlockerResolution = "reassign" | "new_due" | "cancel";
export type TaskAction = Schemas["ActionsEnum"];
export type Comment = Schemas["Comment"];
/** An inbox entry. The backend may add kinds (a blocker, a request for more time) before this app
 * knows them: screens show those with a neutral look rather than break. */
export type Activity = Omit<Schemas["Activity"], "kind"> & { kind: Schemas["ActivityKindEnum"] | (string & {}) };
export type Summary = Schemas["Summary"];
export type ReminderInfo = Schemas["ReminderInfo"];
export type Day = Schemas["Day"];
export type MemberBrief = Schemas["MemberBrief"];
export type Language = Schemas["LanguageEnum"];
export type Repeat = Schemas["RepeatEnum"];
export type Proof = Schemas["ProofEnum"];
export type Period = Schemas["PeriodEnum"];
export type Score = Schemas["Score"];
export type TeamRow = Schemas["TeamRow"];
export type TeamStats = Schemas["TeamStats"];
export type TimeOff = Schemas["TimeOff"];
export type TimeOffStatus = Schemas["TimeOffStatusEnum"];
export type Holiday = Schemas["Holiday"];
export type OffToday = Schemas["OffToday"];

/** `POST tasks/confirm/`: how confirming several tasks went, one result per id. */
export type ConfirmMany = { done: number; failed: number; results: { id: number; ok: boolean; error: string }[] };

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
