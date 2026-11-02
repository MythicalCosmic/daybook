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
