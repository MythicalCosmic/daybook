/** Shapes of the reminders endpoints (plan §4.5, `apps.reminders.owner_api`). */
import type { BranchRef, Page } from "@/api/types";

export interface ReminderText {
  from_step: number;
  text: string;
}

export interface Policy {
  id: number;
  name: string;
  is_default: boolean;
  heads_up_minutes: number;
  repeat_every_minutes: number;
  max_reminders: number;
  escalate_after: number;
  /** "22:00:00" or null. */
  quiet_from: string | null;
  quiet_until: string | null;
  quiet_days: number[];
  snooze_minutes: number;
  max_snoozes: number;
  replace_previous: boolean;
  texts: ReminderText[];
  usage: { routines: number; open_tasks: number };
  updated_at: string;
}

export type PolicyInput = Partial<Omit<Policy, "id" | "is_default" | "usage" | "updated_at">>;

export type LogKind = "heads_up" | "reminder" | "escalation" | "blocked";

export interface LogPerson {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
}

export interface LogRow {
  id: number;
  kind: LogKind;
  step: number;
  sent_at: string;
  delivered: boolean;
  error: string;
  recipient: LogPerson | null;
  task: { id: number; title: string; status: string };
  branch: BranchRef | null;
}

export type LogPage = Page<LogRow>;

export interface BlockedPerson {
  member: LogPerson;
  blocked_at: string;
  branch: string | null;
  open_tasks: number;
  late_tasks: number;
}
