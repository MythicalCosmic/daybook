/**
 * Shapes of the tasks owner endpoints (plan §4.5, `apps.tasks.owner_serializers`), written by hand
 * from the serializers. Money and dates are strings; people are their membership id and name.
 */
import type { BranchRef, Money } from "@/api/types";

export type TaskStatus = "todo" | "in_progress" | "review" | "returned" | "done" | "cancelled";
export type TaskKind = "daily" | "assigned" | "personal";
export type TaskPriority = "low" | "normal" | "high" | "urgent";
/** "readings": numbers within an allowed range, typed in when a routine's run is done (§14.10). */
export type ProofKind = "none" | "photo" | "text" | "any" | "readings";
/** Board columns: To do, In progress, Waiting, Sent back, Done. */
export type BoardColumnId = "todo" | "in_progress" | "review" | "returned" | "done";
export type TaskAction = "start" | "complete" | "confirm" | "return" | "edit" | "cancel" | "reassign" | "nudge" | "comment";

export const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "returned", "done", "cancelled"];
export const PRIORITIES: readonly TaskPriority[] = ["urgent", "high", "normal", "low"];
export const KINDS: readonly TaskKind[] = ["daily", "assigned", "personal"];
export const BOARD_COLUMNS: readonly BoardColumnId[] = ["todo", "in_progress", "review", "returned", "done"];

export interface TaskPerson {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
}

/** Why the assignee can't do it ("Can't do it", cross-area contract 7). */
export type BlockerReason = "no_stock" | "no_access" | "broken" | "not_mine" | "other";
export interface TaskBlocker {
  reason_code: BlockerReason;
  note: string;
  at: string;
}

/** The assignee asks for a later deadline (contract 8); the giver approves or declines. */
export interface TaskExtension {
  until: string;
  note: string;
  at: string;
}

/**
 * One number a readings task asks for (PLAN-OWNER §14.10, `TasksReadingSpec`): a fridge's
 * temperature, the room's humidity. Bounds are decimal strings ("2.0"); null: none on that side.
 */
export interface ReadingSpec {
  key: string;
  label: string;
  unit: string;
  min: string | null;
  max: string | null;
  /** Out of range, the alert about it is critical. */
  critical: boolean;
}

/** A value typed in for a readings task, held to the range it had then (`TasksReadingTaken`). */
export interface ReadingTaken {
  id: number;
  key: string;
  label: string;
  unit: string;
  /** Decimal string ("5.2"). */
  value: string;
  min: string | null;
  max: string | null;
  in_range: boolean;
  /** What was done about it: there when a value was out of range, and on rechecks. */
  note: string;
  /** The second measurement after something was done about a value out of range. */
  is_recheck: boolean;
  recorded_at: string;
  recorded_by: { id: number; name: string } | null;
}

/**
 * Fields the backend adds tonight (contracts 7, 8, 10). Optional: an older backend leaves them
 * out, and the drawer and the table then simply don't show them.
 */
export interface TaskExtras {
  blocker?: TaskBlocker | null;
  extension?: TaskExtension | null;
  /** When the assignee first opened it (the app's task screen or the bot card). */
  seen_at?: string | null;
  /** What a readings task asks for (copied from its routine when the task was made). */
  readings?: ReadingSpec[];
}

export interface TaskRow extends TaskExtras {
  id: number;
  kind: TaskKind;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_at: string | null;
  for_date: string | null;
  is_overdue: boolean;
  assignee: TaskPerson;
  created_by: TaskPerson | null;
  branch: BranchRef | null;
  routine: { id: number; title: string; onboarding: boolean } | null;
  /** The project board the task is a card on; `number` makes its key ("OPEN-14"), null until numbered. */
  project: { id: number; key: string; name: string; number: number | null } | null;
  proof: ProofKind;
  needs_confirmation: boolean;
  /** With needs_confirmation: finished with a photo or text proof, it's accepted at once. */
  accept_with_proof?: boolean;
  /** Done without anyone checking it: at once, or after the company's wait (`confirmed_at`). */
  accepted_automatically?: boolean;
  has_proof: boolean;
  /** 400 px preview (or the photo until the preview exists). */
  proof_thumb: string | null;
  proof_photo: string | null;
  checklist: { done: number; total: number };
  reward: Money | null;
  started_at: string | null;
  completed_at: string | null;
  confirmed_at: string | null;
  created_at: string;
  /** Board columns the caller may drag this card to. */
  moves: BoardColumnId[];
}

export interface ChecklistRow {
  id: number;
  text: string;
  is_done: boolean;
}

export interface TaskComment {
  id: number;
  author: TaskPerson | null;
  text: string;
  created_at: string;
}

export interface ReminderPlan {
  policy: { id: number; name: string };
  heads_up_minutes: number;
  every_minutes: number;
  /** 0 = until it's done. */
  max_reminders: number;
  /** 0 = nobody is told. */
  escalate_after: number;
  sent: number;
  next_at: string | null;
  escalated_at: string | null;
  escalate_to: TaskPerson[];
  snoozed_until: string | null;
  snoozes_left: number;
}

/** A card of the reviews queue (`tasks/reviews/`): the row plus what was written and reported. */
export interface TaskReview extends TaskRow {
  description: string;
  proof_text: string;
  /** The values typed in, for a readings task. */
  readings_taken?: ReadingTaken[];
}

export interface TaskDetail extends TaskRow {
  description: string;
  proof_text: string;
  confirmed_by: TaskPerson | null;
  checklist_items: ChecklistRow[];
  comments: TaskComment[];
  reminders: ReminderPlan | null;
  actions: TaskAction[];
  last_nudged_at: string | null;
  /** A readings task's values, first measurements and rechecks, in time order. */
  readings_taken?: ReadingTaken[];
  /** A finished readings task takes a second measurement until then (null: no more). */
  recheck_until?: string | null;
}

/** A reading as the journal lists it (`TasksReadingRow`): the value, where and for which routine. */
export interface ReadingRow extends ReadingTaken {
  task_id: number;
  /** Company-local day and time it was taken. */
  day: string;
  time: string;
  branch: BranchRef | null;
  routine: { id: number; title: string } | null;
}

/** Today's storage readings (`routines/readings/today/`): the Overview card. */
export interface ReadingsToday {
  day: string;
  /** The company has a readings routine running; until then the card shows nothing. */
  set_up: boolean;
  /** First measurements taken today. */
  taken: number;
  /** Values out of range today; `back_in_range_at` when a recheck brought one back. */
  excursions: Array<ReadingRow & { back_in_range_at: string | null }>;
  /** Readings due by now that nobody took (a shared routine's copies count once). */
  missed: Array<{
    task_id: number;
    routine: { id: number; title: string };
    branch: BranchRef | null;
    due_at: string;
    /** The person, unless the routine is shared ("one of us does it"). */
    assignee: string | null;
  }>;
}

export interface TaskTimelineEntry {
  at: string;
  kind: "created" | "comment" | "completed" | "heads_up" | "reminder" | "escalation" | "blocked" | "audit";
  action: string;
  actor: TaskPerson | null;
  text: string;
  meta: { step?: number; delivered?: boolean; changes?: Record<string, [unknown, unknown]>; reason?: string; [key: string]: unknown };
}

export interface BoardColumn {
  id: BoardColumnId;
  count: number;
  items: TaskRow[];
}

export interface CalendarDayCounts {
  date: string;
  total: number;
  done: number;
  review: number;
  open: number;
  late: number;
}

export interface TaskCalendar {
  days: CalendarDayCounts[];
  items: TaskRow[];
  truncated: boolean;
}

export interface SeriesPoint {
  date: string;
  on_time: number;
  late: number;
  missed: number;
  total: number;
  done: number;
  on_time_percent: number | null;
}

export interface TaskSummary {
  today: string;
  done_today: number;
  total_today: number;
  late_now: number;
  review: number;
  open: number;
  on_time_percent: number | null;
  on_time_previous: number | null;
  done_7d: number;
  done_prev_7d: number;
  series: SeriesPoint[];
}

export interface OptionPerson extends TaskPerson {
  branch: string | null;
  branch_id: number | null;
  position_id: number | null;
}

export interface TaskOptions {
  people: OptionPerson[];
  positions: Array<{ id: number; name: string }>;
  routines: Array<{ id: number; title: string }>;
  policies: Array<{ id: number; name: string; is_default: boolean }>;
}

export interface TaskCreateInput {
  title: string;
  description?: string;
  due_at?: string | null;
  priority?: TaskPriority;
  proof?: ProofKind;
  /** null or left out: the company's rule for finished work decides. */
  needs_confirmation?: boolean | null;
  checklist?: string[];
  reward?: Money | null;
  assignee_ids?: number[];
  position_ids?: number[];
  branch_ids?: number[];
}

/** What quick add read in a typed title (contract 1, `tasks/parse/`); nothing is saved. */
export interface QuickAddParse {
  /** The title without the words that were understood. */
  title: string;
  due_at: string | null;
  /** The deadline in the reader's language, with the weekday and the date ("Ertaga, 22-oktabr (payshanba), 18:00"). */
  due_label: string | null;
  priority: TaskPriority | null;
  repeat: "daily" | "weekdays" | "weekly" | null;
  repeat_weekdays: number[] | null;
}

export type BlockerAction = "reassign" | "new_due" | "cancel";

export interface TaskUpdateInput {
  title?: string;
  description?: string;
  due_at?: string | null;
  priority?: TaskPriority;
  reward?: Money | null;
}

export type BulkAction = "reassign" | "reschedule" | "priority" | "cancel" | "confirm" | "nudge";

export interface BulkInput {
  ids: number[];
  action: BulkAction;
  payload?: { assignee_id?: number; due_at?: string; shift_days?: number; priority?: TaskPriority };
}

export interface BulkResponse {
  done: number;
  failed: number;
  results: Array<{ id: number; ok: boolean; error: string }>;
}

export interface ProofWall {
  day: string;
  items: TaskRow[];
}

/** The list's filters, as the API and the URL name them. */
export interface TaskFilterParams {
  status?: string[];
  kind?: string[];
  assignee?: string[];
  position?: string[];
  branch?: string[];
  created_by?: string[];
  priority?: string[];
  routine?: string[];
  due_from?: string;
  due_to?: string;
  overdue?: string;
  has_proof?: string;
  needs_confirmation?: string;
  q?: string;
}

export type TaskView = "table" | "board" | "calendar";

/** "When someone finishes a task" (PLAN-OWNER §15.3). */
export type OnFinish = "auto" | "proof" | "ask";

/** The company's rules for finished work (`tasks/settings/`). */
export interface TasksSettings {
  on_finish: OnFinish;
  /** Accept work nobody reviewed after this many hours (4–72); null: never. */
  auto_accept_after_hours: number | null;
}
