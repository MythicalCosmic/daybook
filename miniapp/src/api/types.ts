import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Membership = Schemas["Membership"];
export type Position = Schemas["Position"];
/** `routine`: the routine (task template) that made a daily task, null for one-off work. The
 * employee API sends it; until the schema is regenerated it's written here by hand. */
export type Task = Schemas["Task"] & { routine?: number | null };
export type TaskStatus = Schemas["TaskStatusEnum"];
export type TaskAction = Schemas["ActionsEnum"];
export type Comment = Schemas["Comment"];
export type Activity = Schemas["Activity"];
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
