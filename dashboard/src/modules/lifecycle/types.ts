/**
 * Shapes of the lifecycle endpoints (plan §13.4 and §14.14; apps.lifecycle.serializers, prefix
 * `lifecycle/`): disciplinary records and suspensions. Days are company-local "YYYY-MM-DD"; money
 * is a decimal string with its currency; evidence comes as a short-lived signed link.
 */
import type { BranchRef, Currency, Money, PersonRef } from "@/api/types";

export const RECORD_KINDS = ["verbal_warning", "written_warning", "final_warning", "reprimand", "other"] as const;
export type RecordKind = (typeof RECORD_KINDS)[number];

/** Pharmacy categories first (§14.14), then the general ones. */
export const PHARMACY_CATEGORIES = ["storage_breach", "dispensing_error", "rx_violation", "expired_sale", "stock_shortage", "cash_shortage"] as const;
export const GENERAL_CATEGORIES = ["lateness", "absence", "conduct", "policy_breach", "performance", "safety", "other"] as const;
export type RecordCategory = (typeof PHARMACY_CATEGORIES)[number] | (typeof GENERAL_CATEGORIES)[number];

export const RECORD_STATUSES = ["issued", "acknowledged", "withdrawn"] as const;
export type RecordStatus = (typeof RECORD_STATUSES)[number];

export interface ProposedFine {
  id: number;
  amount: Money;
  currency: Currency;
  /** The payroll adjustment's status: proposed, approved, rejected, void. */
  status: string;
}

/** One row of `GET lifecycle/discipline/` and `lifecycle/discipline/{id}/`. */
export interface DisciplinaryRecord {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  kind: RecordKind;
  category: RecordCategory | string;
  incident_on: string;
  issued_on: string;
  issued_by: PersonRef | null;
  description: string;
  /** A signed link to the evidence file, or null. */
  evidence: string | null;
  /** Until when it counts (by default 3, 6 or 12 months from the kind). */
  expires_on: string | null;
  /** Not withdrawn and not past its expiry. */
  active: boolean;
  status: RecordStatus;
  read_at: string | null;
  acknowledged_at: string | null;
  /** The employee's explanation, written in the mini app ("" until they write one). */
  employee_response: string;
  responded_at: string | null;
  /** A fine was proposed to payroll for it. */
  fine_id: number | null;
  /** The fine itself: only for payroll.view (the amount never leaves the server otherwise). */
  fine: ProposedFine | null;
  withdrawn_at: string | null;
  withdraw_reason: string;
  created_at: string;
  can_edit: boolean;
}

export interface RecordParams {
  member?: number;
  kind?: string[];
  category?: string[];
  status?: string[];
  active?: boolean;
  from?: string;
  to?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

/** What POST lifecycle/discipline/ takes (a form when there is evidence). */
export interface RecordInput {
  member_id: number;
  kind: RecordKind;
  category: RecordCategory;
  incident_on: string;
  description: string;
  /** Proposed to payroll as a fine when given. */
  fine_amount?: Money;
  evidence?: File;
}

/** One row of `GET lifecycle/suspensions/`: someone suspended now. */
export interface Suspension {
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  /** The last suspended day; null: until reinstated. */
  until: string | null;
  since: string | null;
  reason: string;
  /** Who suspended them. */
  by: string | null;
  can_reinstate: boolean;
}

export interface SuspendInput {
  member_id: number;
  until: string | null;
  reason: string;
}

// ─── Leaving (terminations) ─────────────────────────────────────────────────

export const LEAVING_KINDS = ["resignation", "company", "contract_end", "other"] as const;
export type LeavingKind = (typeof LEAVING_KINDS)[number];

export const LEAVING_STATUSES = ["requested", "agreed", "completed", "withdrawn", "declined"] as const;
export type LeavingStatus = (typeof LEAVING_STATUSES)[number];

/** The page's tabs: `closed` is withdrawn or declined. */
export const LEAVING_TABS = ["requested", "agreed", "completed", "closed"] as const;
export type LeavingTab = (typeof LEAVING_TABS)[number];

export type HandoverKind = "equipment" | "tasks" | "keys" | "documents" | "other";
export type Rehire = "yes" | "maybe" | "no";

export const EXIT_REASONS = ["pay", "schedule", "workload", "team", "growth", "moving", "studies", "health", "family", "other"] as const;
export type ExitReason = (typeof EXIT_REASONS)[number];

export interface HandoverProgress {
  done: number;
  total: number;
}

/** One row of `GET lifecycle/terminations/`. */
export interface LeavingRow {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  member_status: string;
  kind: LeavingKind;
  status: LeavingStatus;
  /** employee: they asked in the app; company: HR started it. */
  initiated_by: "employee" | "company";
  requested_at: string;
  wished_last_day: string | null;
  last_day: string | null;
  left_on: string | null;
  notice_days: number | null;
  handover: HandoverProgress;
  /** Why the evening job couldn't complete it ("" when nothing went wrong). */
  error: string;
  can_manage: boolean;
  created_at: string;
}

export interface HandoverItem {
  id: number;
  kind: HandoverKind;
  /** "" for the standard items (keys, documents, tasks): the UI names them. */
  title: string;
  asset_id: number | null;
  /** Ticked off, or done by itself (`auto`). */
  done: boolean;
  ticked: boolean;
  auto: boolean;
  /** Equipment they still hold (null for other items and closed lists). */
  held: boolean | null;
  /** The tasks item: how many are open (null otherwise). */
  open_tasks: number | null;
  note: string;
  done_at: string | null;
  done_by: PersonRef | null;
}

export interface LeavingEvent {
  kind: string;
  at: string;
  by: number | null;
  name: string;
  day: string | null;
  note: string;
}

export interface ExitInterview {
  reason: ExitReason;
  better: string;
  recommend: Rehire | "";
  answered_at: string;
}

export interface FinalPayslip {
  id: number;
  status: string;
  period: string;
  last_day: string | null;
  /** Only with payroll.view. */
  net: Money | null;
  currency: Currency;
}

/** `GET lifecycle/terminations/{id}/`. */
export interface Leaving extends LeavingRow {
  reason: string;
  requested_by: PersonRef | null;
  agreed_by: PersonRef | null;
  agreed_at: string | null;
  closed_by: PersonRef | null;
  closed_at: string | null;
  close_reason: string;
  completed_at: string | null;
  completed_by: PersonRef | null;
  final_payslip: boolean;
  leave_days: string;
  rehire: Rehire | "";
  notes: string;
  exit_interview: ExitInterview | null;
  events: LeavingEvent[];
  items: HandoverItem[];
  /** What would stop an offboarding now (cash held, an open till). */
  blockers: string[];
  /** Still open when they left. */
  left_open: string[];
  final_run: FinalPayslip | null;
  can: { manage: boolean; agree: boolean; decline: boolean; withdraw: boolean; handover: boolean; retry: boolean };
}

export interface LeavingParams {
  status?: LeavingTab;
  kind?: string[];
  member?: number;
  q?: string;
  page?: number;
  page_size?: number;
}

export type LeavingCounts = Record<LeavingTab, number>;

export interface LeaveStartInput {
  member_id: number;
  kind: LeavingKind;
  last_day: string;
  reason?: string;
  leave_days?: string;
  final_payslip?: boolean;
}

export interface LeaveAgreeInput {
  last_day?: string;
  leave_days?: string;
  final_payslip?: boolean;
}

export interface LeaveUpdateInput {
  kind?: LeavingKind;
  reason?: string;
  notes?: string;
  rehire?: Rehire | "";
  leave_days?: string;
  final_payslip?: boolean;
}

// ─── Job changes ────────────────────────────────────────────────────────────

export const CHANGE_STATUSES = ["proposed", "approved", "applied", "rejected", "cancelled"] as const;
export type ChangeStatus = (typeof CHANGE_STATUSES)[number];

/** The page's tabs: `upcoming` is approved, `closed` rejected or cancelled. */
export const CHANGE_TABS = ["proposed", "upcoming", "applied", "closed"] as const;
export type ChangeTab = (typeof CHANGE_TABS)[number];

export const CHANGE_PARTS = ["position", "branch", "department", "pay"] as const;
export type ChangePart = (typeof CHANGE_PARTS)[number];

export const PAY_TYPES = ["monthly", "daily", "hourly", "per_task"] as const;
export type PayType = (typeof PAY_TYPES)[number];

export interface Named {
  id: number;
  name: string;
}

export interface JobPay {
  amount: Money;
  currency: Currency;
  pay_type: PayType;
}

/** A job as it was or became; `pay` only for payroll.view. */
export interface JobSide {
  position: Named | null;
  branch: Named | null;
  branches: Named[];
  department: Named | null;
  role: Named | null;
  pay: JobPay | null;
}

/** One row of `GET lifecycle/job-changes/`. */
export interface JobChange {
  id: number;
  member: PersonRef;
  position_now: string | null;
  home_branch: BranchRef | null;
  member_status: string;
  effective_on: string;
  status: ChangeStatus;
  parts: ChangePart[];
  before: JobSide;
  after: JobSide;
  /** The pay changes (whether or not the viewer sees it). */
  has_pay: boolean;
  reason: string;
  proposed_by: PersonRef | null;
  created_at: string;
  decided_by: PersonRef | null;
  decided_at: string | null;
  decision_note: string;
  applied_at: string | null;
  error: string;
  /** Approved, its day still to come. */
  upcoming: boolean;
  can: { decide: boolean; cancel: boolean; retry: boolean };
}

export interface ChangeParams {
  status?: ChangeTab;
  member?: number;
  q?: string;
  page?: number;
  page_size?: number;
}

export type ChangeCounts = Record<ChangeTab, number>;

export interface ChangeInput {
  member_id: number;
  effective_on: string;
  reason: string;
  position_id?: number | null;
  branch_id?: number;
  department_id?: number | null;
  pay_amount?: Money;
  pay_type?: PayType;
  approve?: boolean;
}

/** `GET lifecycle/job-changes/current/?member=`: someone's job now, for the dialog. */
export interface CurrentJob {
  member: PersonRef;
  position: Named | null;
  home_branch: BranchRef | null;
  branches: BranchRef[];
  department: Named | null;
  role: string | null;
  pay: JobPay | null;
  may_change_pay: boolean;
  departments: Named[];
  open_changes: { id: number; effective_on: string; status: ChangeStatus; parts: ChangePart[] }[];
}

/** `GET lifecycle/people/{id}/career/`. */
export interface Career {
  hired_on: string | null;
  changes: JobChange[];
  leavings: LeavingRow[];
}
