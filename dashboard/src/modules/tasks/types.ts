/**
 * Shapes of the tasks owner endpoints (plan §4.5, `apps.tasks.owner_serializers`), written by hand
 * from the serializers. Money and dates are strings; people are their membership id and name.
 */
import type { BranchRef, Money } from "@/api/types";

export type TaskStatus = "todo" | "in_progress" | "review" | "returned" | "done" | "cancelled";
export type TaskKind = "daily" | "assigned" | "personal";
export type TaskPriority = "low" | "normal" | "high" | "urgent";
export type ProofKind = "none" | "photo" | "text" | "any";
/** Board columns: To do, In progress, Waiting, Sent back, Done. */
export type BoardColumnId = "todo" | "in_progress" | "review" | "returned" | "done";
export type TaskAction = "start" | "complete" | "confirm" | "return" | "edit" | "cancel" | "reassign" | "nudge" | "comment";

export const STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "review", "returned", "done", "cancelled"];
export const OPEN_STATUSES: readonly TaskStatus[] = ["todo", "in_progress", "returned"];
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
export const BLOCKER_REASONS: readonly BlockerReason[] = ["no_stock", "no_access", "broken", "not_mine", "other"];

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
 * Fields the backend adds tonight (contracts 7, 8, 10). Optional: an older backend leaves them
 * out, and the drawer and the table then simply don't show them.
 */
export interface TaskExtras {
  blocker?: TaskBlocker | null;
  extension?: TaskExtension | null;
  /** When the assignee first opened it (the app's task screen or the bot card). */
  seen_at?: string | null;
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
  needs_confirmation?: boolean;
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
