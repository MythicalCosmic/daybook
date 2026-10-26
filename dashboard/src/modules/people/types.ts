/**
 * Shapes of the people endpoints (plan §4.6, apps.members.owner_api), written by hand from the
 * serializers. Days are company-local "YYYY-MM-DD", instants ISO strings, money strings.
 */
import type { BranchRef, MoneyValue, PersonRef } from "@/api/types";

export type MemberStatus = "pending" | "approved" | "rejected" | "blocked" | "left" | "suspended";
export type DirectoryStatus = "current" | "active" | "suspended" | "pending" | "left" | "blocked" | "former";

export interface Named {
  id: number;
  name: string;
}

export interface RoleBrief extends Named {
  is_owner: boolean;
}

export interface WorkNumbers {
  /** "93.5" or null when there was no shared work in the last 30 days. */
  on_time_30d: string | null;
  done_30d: number;
  late_now: number;
  open_now: number;
}

/** Fields other modules add through `register_person_fields` (absent without their permission). */
export interface PersonFields {
  attendance_today?: "in" | "late" | "not_yet" | "absent" | "off" | null;
  attendance_30d?: string | null;
  salary?: (MoneyValue & { pay_type: string }) | null;
  time_off_today?: { id: number; until: string } | null;
  [key: string]: unknown;
}

/** One row of `GET people/`. */
export interface Person {
  id: number;
  name: string;
  full_name: string;
  first_name: string;
  last_name: string;
  photo_url: string | null;
  phone: string;
  username: string;
  position: Named | null;
  role: RoleBrief | null;
  home_branch: BranchRef | null;
  branches: BranchRef[];
  status: MemberStatus;
  suspended_until: string | null;
  /** Their first day (when they asked, for a request). */
  joined_on: string | null;
  /** Their last day, for someone who left or was blocked. */
  left_on: string | null;
  onboarded: boolean;
  bot_blocked: boolean;
  work: WorkNumbers;
  fields: PersonFields;
}

export interface TrendPoint {
  date: string;
  on_time_percent: number | null;
  done: number;
  total: number;
}

export interface UpcomingTimeOff {
  id: number;
  first_day: string;
  last_day: string;
  status: "pending" | "approved";
  reason: string;
}

export interface PersonOverview {
  range: { from: string; to: string };
  on_time_percent: number | null;
  on_time: number;
  late: number;
  missed: number;
  done: number;
  total: number;
  open_now: number;
  late_now: number;
  streak: number;
  trend: TrendPoint[];
  joined_on: string | null;
  left_on: string | null;
  tenure_days: number | null;
  days_off_this_year: number;
  upcoming_time_off: UpcomingTimeOff[];
}

export interface PersonActions {
  edit: boolean;
  change_role: boolean;
  block: boolean;
  unblock: boolean;
  offboard: boolean;
  suspend: boolean;
  reinstate: boolean;
  record_time_off: boolean;
}

/** `GET people/{id}/`: Person 360. */
export interface PersonDetail extends Person {
  language: "uz" | "ru" | "en";
  overview: PersonOverview;
  can: PersonActions;
}

export interface PeopleParams {
  q?: string;
  status?: DirectoryStatus;
  position?: string[];
  role?: string[];
  branch?: string[];
  bot_blocked?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface PersonUpdate {
  first_name?: string;
  last_name?: string;
  position_id?: number | null;
  branch_ids?: number[];
  home_branch_id?: number | null;
  role_id?: number;
}

/** One row of `GET people/{id}/history/` (the AuditTrail row shape). */
export interface HistoryRecord {
  id: number;
  created_at: string;
  action: string;
  action_label: string;
  actor: { id: number | null; name: string } | null;
  target_type: string;
  target_id: number | null;
  target: string;
  details: Record<string, unknown>;
}

export type FieldKind = "text" | "textarea" | "bool" | "choice" | "date" | "money" | "number" | "member";

export interface OffboardField {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  choices: Array<[string, string]>;
  help: string;
}

export interface OffboardStep {
  key: string;
  label: string;
  order: number;
  lines: string[];
  blockers: string[];
  fields: OffboardField[];
  defaults: Record<string, unknown>;
  /** A step the viewer can't open: only its label and blockers come (they still apply). */
  restricted?: boolean;
}

export type OffboardReason = "resignation" | "mutual_agreement" | "contract_end" | "dismissal" | "probation_failed" | "redundancy" | "other";

/** `GET people/{id}/offboard-preview/` */
export interface OffboardPreview {
  steps: OffboardStep[];
  blockers: number;
  can_override: boolean;
  reasons: OffboardReason[];
  today: string;
}

export interface OffboardInput {
  terminated_on: string | null;
  reason: OffboardReason;
  note: string;
  steps: Record<string, Record<string, unknown>>;
  override_blockers: boolean;
}

/** The team link someone came through: its branch and role are preselected when approving them. */
export interface JoinRequestLink {
  id: number;
  name: string;
  auto_approve: boolean;
  branch: Named | null;
  role: Named | null;
}

/** One row of `GET join-requests/`. */
export interface JoinRequest {
  id: number;
  name: string;
  first_name: string;
  last_name: string;
  photo_url: string | null;
  phone: string;
  username: string;
  position: Named | null;
  onboarded: boolean;
  requested_at: string;
  former: { left_on: string; how: "left" | "blocked" } | null;
  /** Null for the main invite link (and on servers without team links). */
  join_link?: JoinRequestLink | null;
  fields: Record<string, unknown>;
}

export interface ApproveInput {
  role_id?: number | null;
  position_id?: number | null;
  branch_ids?: number[];
  home_branch_id?: number | null;
}

/** `POST join-requests/bulk/`: approve or reject up to 200 requests at once. */
export interface BulkDecisionInput {
  ids: number[];
  action: "approve" | "reject";
  /** Approve: one role for all; null or left out: each person's link role, else the default role. */
  role_id?: number | null;
  /** Approve: replaces the position they picked; left out: they keep theirs. */
  position_id?: number | null;
  /** Approve: left out or empty: each person's link branch, else the company's only branch. */
  branch_ids?: number[];
  home_branch_id?: number | null;
  /** Reject: optional, at most 300 characters, only approvers see it. */
  reason?: string;
}

export interface BulkDecisionResult {
  /** One per id, in the order sent; `detail` says why not. */
  results: Array<{ id: number; ok: boolean; detail: string }>;
  done: number;
  failed: number;
}

/** One row of `GET roles/`. */
export interface Role {
  id: number;
  name: string;
  permissions: string[];
  is_owner: boolean;
  is_default: boolean;
  members_count: number;
  /** The caller may change it (rule 1: not the Owner role, not a role they hold). */
  can_edit: boolean;
  /** The caller may give it to someone (rule 2). */
  can_assign: boolean;
}

export interface RoleInput {
  name?: string;
  permissions?: string[];
  is_default?: boolean;
}

/** One row of `GET positions/`. */
export interface PositionRow {
  id: number;
  name: string;
  order: number;
  is_active: boolean;
  members_count: number;
}

export type { BranchRef, PersonRef };
