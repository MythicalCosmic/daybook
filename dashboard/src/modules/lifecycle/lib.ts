/**
 * The lifecycle module's plain logic, tested on its own: who may do what, the create payload (with
 * the proposed fine), what a record's state reads as, the suggested next step, and the filters as
 * API params; for leaving and job changes the payloads, their checks, the countdown to a last day,
 * the handover's progress and what a change reads as.
 */
import type { Money } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import type { FilterValues } from "@/components/filters";
import { addDays, addMonths, diffDays, startOfMonth } from "@/lib/dates";
import { moneySign } from "@/lib/money";

import type {
  ChangeInput,
  ChangePart,
  ChangeStatus,
  ChangeTab,
  DisciplinaryRecord,
  HandoverItem,
  HandoverProgress,
  JobChange,
  JobSide,
  LeaveStartInput,
  LeavingKind,
  LeavingRow,
  LeavingStatus,
  PayType,
  RecordCategory,
  RecordInput,
  RecordKind,
  RecordParams,
} from "./types";

// ─── Access ────────────────────────────────────────────────────────────────

export interface LifecycleAccess {
  /** Sees records and suspensions. */
  view: boolean;
  /** Issues and withdraws disciplinary records. */
  discipline: boolean;
  /** Suspends and reinstates. */
  suspend: boolean;
}

export function lifecycleAccess(can: (perm: "hr.view" | "hr.discipline" | "hr.suspend") => boolean): LifecycleAccess {
  const discipline = can("hr.discipline");
  const suspend = can("hr.suspend");
  return { view: discipline || suspend || can("hr.view"), discipline, suspend };
}

// ─── Create ────────────────────────────────────────────────────────────────

export interface RecordForm {
  member: number | null;
  kind: RecordKind;
  category: RecordCategory | null;
  incident_on: string | null;
  description: string;
  files: File[];
  proposeFine: boolean;
  fine: Money | null;
}

export type RecordFormErrors = Partial<Record<"member" | "category" | "incident_on" | "description" | "fine", "required" | "future" | "amount">>;

/** What is missing or wrong in the form (the keys of the messages to show). */
export function recordFormErrors(form: RecordForm, today: string): RecordFormErrors {
  const errors: RecordFormErrors = {};
  if (!form.member) errors.member = "required";
  if (!form.category) errors.category = "required";
  if (!form.incident_on) errors.incident_on = "required";
  else if (form.incident_on > today) errors.incident_on = "future";
  if (!form.description.trim()) errors.description = "required";
  if (form.proposeFine && moneySign(form.fine) !== 1) errors.fine = "amount";
  return errors;
}

/**
 * The body of POST lifecycle/discipline/: the description trimmed, the evidence only when a file
 * was added, and `fine_amount` only when "also propose a fine" is on with an amount above zero
 * (payroll gets it as a proposal to approve).
 */
export function recordPayload(form: RecordForm): RecordInput {
  const payload: RecordInput = {
    member_id: form.member!,
    kind: form.kind,
    category: form.category!,
    incident_on: form.incident_on!,
    description: form.description.trim(),
  };
  if (form.proposeFine && moneySign(form.fine) === 1) payload.fine_amount = form.fine!;
  if (form.files[0]) payload.evidence = form.files[0];
  return payload;
}

// ─── Records ───────────────────────────────────────────────────────────────

export const KIND_TONES: Record<RecordKind, StatusTone> = {
  verbal_warning: "info",
  written_warning: "warning",
  final_warning: "danger",
  reprimand: "danger",
  other: "neutral",
};

/** How a record's state reads: issued (not read yet), read, withdrawn, or no longer counting. */
export type RecordState = "issued" | "acknowledged" | "withdrawn" | "expired";

export const STATE_TONES: Record<RecordState, StatusTone> = { issued: "warning", acknowledged: "success", withdrawn: "neutral", expired: "neutral" };

export function recordState(record: Pick<DisciplinaryRecord, "status" | "active">): RecordState {
  if (record.status === "withdrawn") return "withdrawn";
  if (!record.active) return "expired";
  return record.status;
}

const LADDER: Record<RecordKind, number> = { other: 0, verbal_warning: 1, written_warning: 2, reprimand: 2, final_warning: 3 };

export type NextStep = "written_warning" | "final_warning" | "consider_termination";

/**
 * The step after the strongest record still in force from the last six months (plan §13.4: "the
 * UI shows active records in the last 6 months and a suggested next step"): a verbal warning
 * leads to a written one, a written warning or reprimand to a final one, a final one to
 * considering termination. Null when nothing counts.
 */
export function nextStep(records: readonly Pick<DisciplinaryRecord, "kind" | "active" | "incident_on">[], today: string): { step: NextStep; count: number } | null {
  const since = addMonths(today, -6);
  const counting = records.filter((record) => record.active && record.incident_on >= since && LADDER[record.kind] > 0);
  if (!counting.length) return null;
  const top = Math.max(...counting.map((record) => LADDER[record.kind]));
  const step: NextStep = top >= 3 ? "consider_termination" : top === 2 ? "final_warning" : "written_warning";
  return { step, count: counting.length };
}

const asList = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : typeof value === "string" && value ? [value] : []);

/** The Discipline filters as the API's query. */
export function recordParams(values: FilterValues, search: string): RecordParams {
  const params: RecordParams = {};
  for (const key of ["kind", "category", "status"] as const) {
    const list = asList(values[key]);
    if (list.length) params[key] = list;
  }
  if (values.active === true || values.active === "true") params.active = true;
  if (search.trim()) params.q = search.trim();
  return params;
}

// ─── Leaving ───────────────────────────────────────────────────────────────

/** A resignation's usual notice (the server's `NOTICE_DAYS`): two weeks. */
export const NOTICE_DAYS = 14;

export interface LeavingAccess {
  /** Sees the leaving pages. */
  view: boolean;
  /** Agrees, declines, starts, ticks the handover off (hr.terminate). */
  manage: boolean;
}

export function leavingAccess(can: (perm: "hr.view" | "hr.terminate") => boolean): LeavingAccess {
  const manage = can("hr.terminate");
  return { view: manage || can("hr.view"), manage };
}

export const LEAVING_TONES: Record<LeavingStatus, StatusTone> = {
  requested: "warning",
  agreed: "info",
  completed: "neutral",
  withdrawn: "neutral",
  declined: "neutral",
};

export const LEAVING_KIND_TONES: Record<LeavingKind, StatusTone> = {
  resignation: "primary",
  company: "warning",
  contract_end: "info",
  other: "neutral",
};

/** Days from `today` to the leaving's last day (0 on it, negative once past); null without a day. */
export function daysLeft(row: Pick<LeavingRow, "last_day" | "wished_last_day">, today: string): number | null {
  const day = row.last_day ?? row.wished_last_day;
  return day ? diffDays(today, day) : null;
}

/** Less than the usual two weeks' notice: worth a look (never a refusal). */
export const shortNotice = (days: number | null | undefined): boolean => days !== null && days !== undefined && days < NOTICE_DAYS;

export const handoverPercent = (progress: HandoverProgress): number => (progress.total ? Math.round((progress.done / progress.total) * 100) : 0);

/** An item's own title, or null when the UI names it by its kind (keys, documents, open tasks). */
export const itemTitle = (item: Pick<HandoverItem, "title">): string | null => item.title.trim() || null;

export interface StartForm {
  member: number | null;
  kind: LeavingKind;
  last_day: string | null;
  reason: string;
  final_payslip: boolean;
  leave_days: number | null;
}

export type StartFormErrors = Partial<Record<"member" | "last_day" | "leave_days", "required" | "past" | "range">>;

export function startFormErrors(form: StartForm, today: string): StartFormErrors {
  const errors: StartFormErrors = {};
  if (!form.member) errors.member = "required";
  if (!form.last_day) errors.last_day = "required";
  else if (form.last_day < today) errors.last_day = "past";
  if (form.leave_days !== null && (form.leave_days < 0 || form.leave_days > 366)) errors.leave_days = "range";
  return errors;
}

/** The body of POST lifecycle/terminations/: the reason trimmed, the leave days when given. */
export function startPayload(form: StartForm): LeaveStartInput {
  const payload: LeaveStartInput = { member_id: form.member!, kind: form.kind, last_day: form.last_day!, final_payslip: form.final_payslip };
  if (form.reason.trim()) payload.reason = form.reason.trim();
  if (form.leave_days !== null) payload.leave_days = String(form.leave_days);
  return payload;
}

/** The day a new leaving suggests: the usual notice from today. */
export const suggestedLastDay = (today: string): string => addDays(today, NOTICE_DAYS);

// ─── Job changes ───────────────────────────────────────────────────────────

export interface ChangeAccess {
  view: boolean;
  /** Proposes changes (hr.manage). */
  propose: boolean;
}

export function changeAccess(can: (perm: "hr.view" | "hr.manage") => boolean): ChangeAccess {
  const propose = can("hr.manage");
  return { view: propose || can("hr.view"), propose };
}

export const CHANGE_TONES: Record<ChangeStatus, StatusTone> = {
  proposed: "warning",
  approved: "info",
  applied: "success",
  rejected: "danger",
  cancelled: "neutral",
};

/** Which tab a change sits in. */
export function changeTab(change: Pick<JobChange, "status">): ChangeTab {
  if (change.status === "proposed") return "proposed";
  if (change.status === "approved") return "upcoming";
  if (change.status === "applied") return "applied";
  return "closed";
}

/** The day a new change suggests: the 1st of next month (changes usually start with a month). */
export const suggestedChangeDay = (today: string): string => startOfMonth(addMonths(startOfMonth(today), 1));

/** Before and after of one part, by name ("Farmatsevt", "Provizor"); pay comes as amounts. */
export function partSides(change: Pick<JobChange, "before" | "after">, part: Exclude<ChangePart, "pay">): { was: string | null; now: string | null } {
  const name = (side: JobSide) => side[part]?.name ?? null;
  return { was: name(change.before), now: name(change.after) };
}

export interface ChangeForm {
  member: number | null;
  effective_on: string | null;
  parts: ChangePart[];
  position: number | null;
  branch: number | null;
  department: number | null;
  pay_amount: Money | null;
  pay_type: PayType | null;
  reason: string;
  approve: boolean;
}

export type ChangeFormErrors = Partial<Record<"member" | "effective_on" | "parts" | "position" | "branch" | "pay_amount" | "reason", "required" | "past" | "amount" | "nothing">>;

/** What the dialog still needs: a person, a day (today or later), something that changes, a reason. */
export function changeFormErrors(form: ChangeForm, today: string): ChangeFormErrors {
  const errors: ChangeFormErrors = {};
  if (!form.member) errors.member = "required";
  if (!form.effective_on) errors.effective_on = "required";
  else if (form.effective_on < today) errors.effective_on = "past";
  if (!form.parts.length) errors.parts = "nothing";
  if (form.parts.includes("position") && !form.position) errors.position = "required";
  if (form.parts.includes("branch") && !form.branch) errors.branch = "required";
  if (form.parts.includes("pay") && moneySign(form.pay_amount) !== 1) errors.pay_amount = "amount";
  if (!form.reason.trim()) errors.reason = "required";
  return errors;
}

/**
 * The body of POST lifecycle/job-changes/: only the parts that change ("position_id": null takes
 * the position away, "department_id": null the department), the reason trimmed, and "approve" for
 * someone who decides it in the same step.
 */
export function changePayload(form: ChangeForm): ChangeInput {
  const payload: ChangeInput = { member_id: form.member!, effective_on: form.effective_on!, reason: form.reason.trim() };
  if (form.parts.includes("position")) payload.position_id = form.position;
  if (form.parts.includes("branch") && form.branch) payload.branch_id = form.branch;
  if (form.parts.includes("department")) payload.department_id = form.department;
  if (form.parts.includes("pay") && form.pay_amount) {
    payload.pay_amount = form.pay_amount;
    if (form.pay_type) payload.pay_type = form.pay_type;
  }
  if (form.approve) payload.approve = true;
  return payload;
}
