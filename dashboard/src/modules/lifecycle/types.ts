/**
 * Shapes of the lifecycle endpoints (plan §13.4 and §14.14, apps.lifecycle.owner_api, prefix
 * `lifecycle/`): disciplinary records and suspensions. Days are company-local "YYYY-MM-DD"; money
 * is a decimal string with its currency; evidence comes as a short-lived signed link.
 */
import type { Currency, Money, PersonRef } from "@/api/types";

export const RECORD_KINDS = ["verbal_warning", "written_warning", "final_warning", "reprimand", "other"] as const;
export type RecordKind = (typeof RECORD_KINDS)[number];

/** Pharmacy categories first (§14.14), then the general ones. */
export const PHARMACY_CATEGORIES = ["storage_breach", "dispensing_error", "rx_violation", "expired_sale", "stock_shortage", "cash_shortage"] as const;
export const GENERAL_CATEGORIES = ["lateness", "absence", "misconduct", "policy_breach", "performance", "safety", "other"] as const;
export type RecordCategory = (typeof PHARMACY_CATEGORIES)[number] | (typeof GENERAL_CATEGORIES)[number];

export type RecordStatus = "draft" | "issued" | "acknowledged" | "disputed" | "withdrawn" | "expired";

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
  kind: RecordKind;
  category: RecordCategory | string;
  incident_on: string;
  description: string;
  /** A signed link to the evidence file, or null. */
  evidence: string | null;
  evidence_name?: string;
  issued_by: string | null;
  issued_at: string;
  expires_on: string | null;
  status: RecordStatus;
  acknowledged_at: string | null;
  /** The employee's explanation, written in the mini app ("" until they write one). */
  employee_response: string;
  responded_at: string | null;
  fine: ProposedFine | null;
}

export interface RecordParams {
  member?: number;
  kind?: string[];
  category?: string[];
  status?: string[];
  active?: boolean;
  q?: string;
  ordering?: string;
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

export type SuspensionStatus = "scheduled" | "active" | "ended" | "cancelled";

/** One row of `GET lifecycle/suspensions/`. */
export interface Suspension {
  id: number;
  member: PersonRef;
  position: string | null;
  starts_on: string;
  /** The last suspended day; null means until reinstated. */
  ends_on: string | null;
  reason: string;
  status: SuspensionStatus;
  created_by: string | null;
  created_at: string;
  ended_at: string | null;
  ended_by: string | null;
}

export interface SuspensionParams {
  member?: number;
  status?: SuspensionStatus[];
  q?: string;
  page?: number;
  page_size?: number;
}

export interface SuspendInput {
  member_id: number;
  until: string | null;
  reason: string;
}
