/**
 * The lifecycle module's plain logic, tested on its own: who may do what, the create payload (with
 * the proposed fine), what a record's state reads as, the suggested next step, and the filters as
 * API params.
 */
import type { Money } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import type { FilterValues } from "@/components/filters";
import { addMonths } from "@/lib/dates";
import { moneySign } from "@/lib/money";

import type { DisciplinaryRecord, RecordCategory, RecordInput, RecordKind, RecordParams } from "./types";

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
