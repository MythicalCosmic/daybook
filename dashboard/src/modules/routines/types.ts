/** Shapes of the routines endpoints (plan §4.5 `routines/`, `apps.tasks.owner_serializers`). */
import type { BranchRef } from "@/api/types";

export type ProofKind = "none" | "photo" | "text" | "any";

export interface RoutinePerson {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
}

export interface RoutineStats {
  made_30d: number;
  done_30d: number;
  on_time_30d: number;
  /** Finished share of what it made in 30 days; null when it made nothing. */
  completion_30d: number | null;
  /** 14 days of daily completion %, oldest first (null: nothing due that day). */
  spark: Array<number | null>;
}

/** Why a routine makes no tasks on a day (`apps.tasks.generation`), in the order they're checked. */
export type SkipReason = "paused" | "onboarding" | "holiday" | "not_due" | "not_started" | "made_late";
/** Why someone a routine names doesn't get its task on a day. */
export type PersonReason = "left" | "suspended" | "not_registered" | "branch" | "joined_later" | "time_off" | "off";

/** Today, on a routine's own answers (detail, create, edit); null in the list. */
export interface RoutineToday {
  date: string;
  /** Why it makes no tasks today; null when it does. */
  reason: SkipReason | null;
  /** "Give today's task now": made after today's deadline and someone would still get it. */
  give: { people: number; due_at: string } | null;
  /** Made after today's deadline: today's tasks given by hand anyway (0 when none). */
  given?: number;
}

export interface Routine {
  id: number;
  title: string;
  description: string;
  /** 0 = Monday … 6 = Sunday. */
  weekdays: number[];
  /** "08:45:00" */
  due_time: string;
  starts_on: string | null;
  is_active: boolean;
  onboarding: boolean;
  due_after_days: number;
  proof: ProofKind;
  needs_confirmation: boolean;
  checklist: string[];
  branch: BranchRef | null;
  assignees: RoutinePerson[];
  positions: Array<{ id: number; name: string }>;
  reminder_policy: { id: number; name: string } | null;
  escalate_to: RoutinePerson | null;
  stats: RoutineStats | null;
  /** When its next tasks are due (holidays counted); null when paused or onboarding. */
  next_run: string | null;
  today: RoutineToday | null;
  created_at: string;
}

export interface RoutineInput {
  title?: string;
  description?: string;
  weekdays?: number[];
  due_time?: string;
  starts_on?: string | null;
  is_active?: boolean;
  onboarding?: boolean;
  due_after_days?: number;
  proof?: ProofKind;
  needs_confirmation?: boolean;
  checklist?: string[];
  branch_id?: number | null;
  assignee_ids?: number[];
  position_ids?: number[];
  reminder_policy_id?: number | null;
  escalate_to_id?: number | null;
}

export interface RoutinePreview {
  day: string;
  due: boolean;
  holiday: boolean;
  /** Why it makes no tasks that day; null when it does. */
  reason: SkipReason | null;
  due_at: string;
  /** When a day it skips is followed by tasks ("made after today's 09:00: starts tomorrow"). */
  next_run: string | null;
  people: Array<{ member: RoutinePerson; gets: boolean; reason: PersonReason | null }>;
}

export interface GivenToday {
  given: number;
  due_at: string;
  people: RoutinePerson[];
}

/** What "Give today's task now" needs to know about a routine (a whole Routine or a day's row). */
export type GiveTarget = Pick<Routine, "id" | "title" | "due_time" | "next_run" | "today">;

// ─── Routine work (the Routines page: Today, History, To confirm) ───────────────────────────

/** How one person's run of a routine stands: late is open past its deadline while the day lasts. */
export type RunState = "done" | "review" | "late" | "missed" | "returned" | "open" | "cancelled";
/** Why someone a routine names was left out of a day. */
export type SkippedReason = "time_off" | "off" | "suspended" | "joined_later";

export interface RoutineRef {
  id: number;
  title: string;
  /** "09:00" */
  due_time: string;
  branch: BranchRef | null;
  proof: ProofKind;
  needs_confirmation: boolean;
  is_active: boolean;
}

export interface RoutineRun {
  /** The task's id. */
  id: number;
  member: RoutinePerson;
  branch: BranchRef | null;
  state: RunState;
  status: string;
  due_at: string | null;
  completed_at: string | null;
  on_time: boolean | null;
  proof: ProofKind;
  proof_text: string;
  proof_thumb: string | null;
  proof_photo: string | null;
  checklist: { done: number; total: number };
  can_confirm: boolean;
}

export type RunCounts = Record<RunState | "skipped", number>;

export interface DayRoutine {
  routine: RoutineRef;
  due_at: string;
  /** Why it makes no tasks that day (null when it does). */
  reason: SkipReason | null;
  next_run: string | null;
  /** "Give today's task now" (today, made after its time, for whoever may plan routines). */
  give: { people: number; due_at: string } | null;
  progress: { finished: number; total: number; percent: number | null };
  counts: RunCounts;
  runs: RoutineRun[];
  skipped: Array<{ member: RoutinePerson; reason: SkippedReason }>;
}

export interface RoutineDay {
  day: string;
  holiday: boolean;
  /** Routines with nothing that day (not one of their days, paused…). */
  idle: number;
  totals: RunCounts & { total: number; finished: number; routines: number };
  routines: DayRoutine[];
}

export interface HistoryCell {
  made: number;
  finished: number;
  on_time: number;
  late: number;
  missed: number;
  /** Not finished and its time still ahead (not counted in the rates). */
  open: number;
  percent: number | null;
  on_time_percent: number | null;
}

export interface RoutineHistory {
  range: { from: string; to: string };
  days: string[];
  routines: Array<{ routine: RoutineRef; cells: Array<HistoryCell | null>; totals: HistoryCell }>;
  series: Array<HistoryCell & { date: string }>;
  people: Array<HistoryCell & { member: RoutinePerson }>;
  totals: HistoryCell;
}

export interface ConfirmGroup {
  routine: RoutineRef;
  day: string;
  items: RoutineRun[];
}

export interface ToConfirm {
  count: number;
  groups: ConfirmGroup[];
}

export interface BulkResult {
  done: number;
  failed: number;
  results: Array<{ id: number; ok: boolean; error: string }>;
}

export interface ComplianceDay {
  date: string;
  made: number;
  on_time: number;
  late: number;
  missed: number;
  on_time_percent: number | null;
}

export interface RoutineCompliance {
  range: { from: string; to: string };
  totals: { made: number; on_time: number; late: number; missed: number; on_time_percent: number | null };
  series: ComplianceDay[];
  people: Array<{ member: RoutinePerson; made: number; on_time: number; late: number; missed: number; on_time_percent: number | null }>;
}

export interface PlanOptions {
  people: Array<RoutinePerson & { branch: string | null; branch_id: number | null; position_id: number | null }>;
  positions: Array<{ id: number; name: string }>;
  routines: Array<{ id: number; title: string }>;
  policies: Array<{ id: number; name: string; is_default: boolean }>;
}
