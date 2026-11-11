/**
 * Hand-written shapes of the contracts endpoints (`apps/contracts/serializers.py`); the lead
 * regenerates the OpenAPI types at integration. Money is a string, days are "YYYY-MM-DD".
 */
import type { Currency, Money } from "@/api/types";

export type ContractKind = "lease" | "supply" | "service" | "licence" | "insurance" | "other";
export type ContractPeriod = "monthly" | "quarterly" | "yearly" | "once";
export type ContractStatus = "draft" | "active" | "ending" | "ended" | "terminated";
export type ContractFileKind = "signed" | "annex" | "other";
export type Attention = "ending" | "notice";
export type DateKey = "signed" | "starts" | "renewed" | "notice" | "renews" | "ends" | "terminated";

export const KINDS: ContractKind[] = ["lease", "supply", "service", "licence", "insurance", "other"];
export const PERIODS: ContractPeriod[] = ["monthly", "quarterly", "yearly", "once"];
export const STATUSES: ContractStatus[] = ["draft", "active", "ending", "ended", "terminated"];

export interface Ref {
  id: number;
  name: string;
}

export interface ContractRow {
  id: number;
  kind: ContractKind;
  title: string;
  number: string;
  branch: Ref | null;
  counterparty: Ref | null;
  responsible: Ref | null;
  status: ContractStatus;
  starts_on: string | null;
  ends_on: string | null;
  auto_renews: boolean;
  notice_deadline: string | null;
  /** The next date that matters: the notice deadline while it is ahead, else the end. */
  key_day: string | null;
  days_left: number | null;
  attention: Attention | null;
  amount: Money | null;
  period: ContractPeriod;
  currency: Currency;
  per_month: Money | null;
  in_forecast: boolean;
  has_rule: boolean;
  files: number;
}

export interface ContractFile {
  id: number;
  kind: ContractFileKind;
  label: string;
  size: number;
  is_pdf: boolean;
  /** A signed link, valid for ten minutes. */
  url: string;
  uploaded_by: string | null;
  created_at: string;
}

export interface ContractDate {
  key: DateKey;
  day: string;
  past: boolean;
}

export interface ContractRule {
  id: number;
  name: string;
  is_active: boolean;
  category: Ref;
  account: Ref | null;
  amount: Money;
  currency: Currency;
  frequency: string;
  day: number;
  next_due_on: string | null;
  ends_on: string | null;
}

export interface Payment {
  id: number;
  occurred_on: string;
  amount: Money;
  currency: Currency;
  base_amount: Money;
  description: string;
  account: string | null;
  by_rule: boolean;
}

export interface Payments {
  items: Payment[];
  count: number;
  total: Money;
  this_year: Money;
  currency: Currency;
  last_paid_on: string | null;
  next: { due_on: string | null; amount: Money; currency: Currency } | null;
}

export interface ContractDetail extends ContractRow {
  signed_on: string | null;
  renewal_months: number;
  notice_days: number;
  payment_day: number | null;
  notes: string;
  terminated_on: string | null;
  termination_reason: string;
  last_renewed_on: string | null;
  renewal_confirmed: boolean;
  file_list: ContractFile[];
  dates: ContractDate[];
  rule: ContractRule | null;
  /** Null while the Finance module is off. */
  payments: Payments | null;
  created_at: string;
  can: { manage: boolean };
}

export interface ContractInput {
  kind?: ContractKind;
  title?: string;
  branch?: number | null;
  counterparty?: number | null;
  counterparty_name?: string;
  number?: string;
  signed_on?: string | null;
  starts_on?: string | null;
  ends_on?: string | null;
  auto_renews?: boolean;
  renewal_months?: number;
  notice_days?: number;
  amount?: Money | null;
  period?: ContractPeriod;
  currency?: Currency;
  payment_day?: number | null;
  notes?: string;
  status?: "draft" | "active";
  responsible?: number | null;
  in_forecast?: boolean;
  category?: number | null;
  account?: number | null;
  link_rule?: number | null;
}

export interface Summary {
  today: string;
  counts: Record<ContractStatus, number>;
  total: number;
  in_force: number;
  ending_soon: number;
  notice_due: number;
  monthly_cost: Money;
  currency: Currency;
  unpriced: number;
  remind_days: number;
  notice_remind_days: number;
}

export interface ContractSettings {
  remind_days: number;
  notice_remind_days: number;
}

export interface Options {
  finance: boolean;
  base_currency: Currency;
  categories: Array<{ id: number; name: string; system_code: string }>;
  accounts: Array<{ id: number; name: string; currency: Currency }>;
  rules: Array<{ id: number; name: string; amount: Money; currency: Currency; frequency: string; counterparty: number | null; branch: number | null }>;
  parties: Array<{ id: number; name: string; kind: string }>;
}
