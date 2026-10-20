/**
 * Shapes of the time-off endpoints (plan §4.6, apps.timeoff.owner_api), written by hand from the
 * serializers. Days are company-local "YYYY-MM-DD".
 */
import type { BranchRef, PersonRef } from "@/api/types";

export type TimeOffStatus = "pending" | "approved" | "rejected" | "cancelled";

/** One row of `GET time-off/` and `time-off/{id}/`. */
export interface TimeOffRow {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  first_day: string;
  last_day: string;
  days: number;
  reason: string;
  status: TimeOffStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  recorded_by: PersonRef | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoke_reason: string;
  /** A signed link to the sick note (10 minutes), or null. */
  attachment: string | null;
  can_decide: boolean;
  can_revoke: boolean;
}

export interface TimeOffParams {
  status?: TimeOffStatus[];
  from?: string;
  to?: string;
  member?: number;
  branch?: number[];
  q?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface CalendarItem {
  id: number;
  first_day: string;
  last_day: string;
  status: "pending" | "approved";
  reason: string;
  recorded: boolean;
  days: number;
}

export interface CalendarRow {
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  items: CalendarItem[];
}

export interface Holiday {
  id: number;
  date: string;
  name: string;
}

/** `GET time-off/calendar/?month=` */
export interface CalendarMonth {
  month: string;
  from: string;
  to: string;
  today: string;
  holidays: Holiday[];
  /** Company work days, 0 = Monday … 6 = Sunday. */
  workdays: number[];
  rows: CalendarRow[];
}

/** `GET time-off/stats/` */
export interface TimeOffStats {
  pending: number;
  off_today: number;
  off_this_week: number;
  days_this_month: number;
  next_holiday: { date: string; name: string } | null;
}

export interface RecordInput {
  member_id: number;
  first_day: string;
  last_day: string;
  reason: string;
  attachment?: File | null;
}

export type { BranchRef, PersonRef };
