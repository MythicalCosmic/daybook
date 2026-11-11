/**
 * Loans and the tax calendar (v12, owner feature 5): `finance/loans/` (a loan's terms, its schedule
 * with principal and interest, payments, early repayment) and `finance/taxes/` (the deadlines by the
 * company's regime, marks, the turnover tax / VAT comparison). Types are hand-written next to the
 * calls (the lead regenerates the OpenAPI types); keys live under `[companyId, "finance"]`, so every
 * finance pulse refreshes them with the rest of the module.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import type { Currency, Money } from "@/api/types";
import { dec } from "@/lib/decimal";
import { useCompanyId } from "@/stores/company";

import { financeKeys } from "./api";
import type { Transaction } from "./types";

// ─── Loans ──────────────────────────────────────────────────────────────────

export type LoanDirection = "payable" | "receivable";
export type LoanMethod = "annuity" | "equal_principal" | "custom";
export type LoanBasis = "monthly" | "actual";
export type LoanLineStatus = "paid" | "partial" | "due" | "overdue";
export type EarlyMode = "payment" | "term";

export interface LoanLine {
  id: number;
  position: number;
  due_on: string;
  principal: Money;
  interest: Money;
  payment: Money;
  principal_paid: Money;
  interest_paid: Money;
  /** What is still to pay of it, principal and interest. */
  rest: Money;
  /** The principal still owed after it. */
  balance: Money;
  status: LoanLineStatus;
  early: boolean;
}

export interface Loan {
  id: number;
  debt_id: number;
  direction: LoanDirection;
  direction_label: string;
  counterparty: { id: number; name: string };
  branch: { id: number; name: string } | null;
  account: { id: number; name: string; kind: string; currency: Currency } | null;
  description: string;
  currency: Currency;
  status: "open" | "paid" | "written_off" | "cancelled";
  is_opening: boolean;
  issued_on: string;
  ends_on: string | null;
  annual_rate: string;
  method: LoanMethod;
  method_label: string;
  basis: LoanBasis;
  term_months: number;
  first_due_on: string;
  grace_months: number;
  fee: Money;
  amount: Money;
  owed: Money;
  paid_principal: Money;
  interest_paid: Money;
  interest_left: Money;
  next: LoanLine | null;
  overdue_count: number;
  overdue_amount: Money;
  payments_left: number;
  payments: number;
}

export interface LoanList {
  currency: Currency;
  owed: Money;
  owed_to_us: Money;
  due_30: Money;
  overdue: Money;
  loans: Loan[];
}

export interface LoanDetail {
  loan: Loan;
  schedule: LoanLine[];
  payments: Transaction[];
  can_pay: boolean;
  can_edit_schedule: boolean;
  can_undo: boolean;
}

export interface ScheduleRow {
  due_on: string;
  principal: Money;
  interest: Money;
}

export interface LoanTerms {
  amount: Money;
  currency: Currency;
  issued_on: string;
  annual_rate: string;
  method: LoanMethod;
  basis: LoanBasis;
  term_months: number;
  first_due_on: string | null;
  grace_months: number;
  fee?: Money;
  rows?: ScheduleRow[];
}

export interface LoanInput extends LoanTerms {
  direction: LoanDirection;
  counterparty: number;
  account: number | null;
  branch?: number | null;
  description?: string;
}

export interface LoanPreview {
  rows: Array<{ position: number; due_on: string; principal: Money; interest: Money; payment: Money; balance: Money }>;
  totals: { principal: Money; interest: Money; payments: Money; fee: Money; cost: Money };
  first_payment: Money;
  effective_rate: string;
}

// ─── Taxes ──────────────────────────────────────────────────────────────────

export type TaxAction = "file_pay" | "file" | "pay";
export type TaxStatus = "due" | "overdue" | "done";

export interface TaxDeadline {
  /** "<rule>:<period start>" */
  key: string;
  rule: string;
  tax: string;
  tax_name: string;
  name: string;
  period: "month" | "quarter" | "year";
  period_start: string;
  period_end: string;
  period_label: string;
  due_on: string;
  action: TaxAction;
  action_label: string;
  estimate: Money | null;
  /** How the estimate is worked out. */
  basis: string;
  /** The amount is a booked tax debt, not an estimate. */
  booked: boolean;
  currency: Currency;
  status: TaxStatus;
  done_on: string | null;
  mark_id: number | null;
  paid: Money | null;
  transaction_id: number | null;
  debt_id: number | null;
  /** The recurring tax bill that reminds of it. */
  rule_id: number | null;
  rate: string | null;
  law: string;
  url: string;
  confidence: "H" | "M";
  note: string;
}

export interface TaxCalendar {
  today: string;
  from: string;
  to: string;
  currency: Currency;
  regime: "turnover" | "vat" | "vat_simplified";
  regime_label: string;
  profile: { payroll: boolean; property: boolean; land: boolean; big_income: boolean };
  remind_days: number;
  warnings: string[];
  deadlines: TaxDeadline[];
  checked_on: string;
  sources: Array<{ label: string; url: string }>;
  disclaimer: string;
}

export interface TaxMarkInput {
  rule: string;
  period_start: string;
  done_on: string;
  transaction?: number | null;
  account?: number | null;
  amount?: Money | null;
  note?: string;
}

export interface TaxCandidate {
  id: number;
  occurred_on: string;
  amount: Money;
  description: string;
  account: string;
  category: string | null;
}

export interface TaxCompareOption {
  regime: "turnover" | "vat" | "vat_simplified";
  label: string;
  total: Money;
  parts: Array<{ name: string; amount: Money; formula: string }>;
  available: boolean;
  why_not: string;
  law: string;
  current: boolean;
  cheapest: boolean;
}

export interface TaxCompare {
  from: string;
  to: string;
  days: number;
  currency: Currency;
  income: Money;
  goods: Money;
  expense: Money;
  profit: Money;
  enough: boolean;
  threshold: Money;
  threshold_law: string;
  over_threshold: boolean;
  regime: string;
  options: TaxCompareOption[];
  assumptions: string[];
  disclaimer: string;
}

// ─── Calls ──────────────────────────────────────────────────────────────────

const path = (cid: number, rest: string) => ownerPath(cid, `finance/${rest}`);

export const creditApi = {
  loans: (cid: number) => http.get<LoanList>(path(cid, "loans/")),
  loan: (cid: number, id: number) => http.get<LoanDetail>(path(cid, `loans/${id}/`)),
  createLoan: (cid: number, input: LoanInput) => http.post<Loan>(path(cid, "loans/"), input),
  preview: (cid: number, terms: LoanTerms) => http.post<LoanPreview>(path(cid, "loans/preview/"), terms, { toast: false }),
  replaceSchedule: (cid: number, id: number, input: Partial<Omit<LoanTerms, "amount" | "currency" | "issued_on">>) =>
    http.put<LoanDetail>(path(cid, `loans/${id}/schedule/`), input),
  pay: (cid: number, id: number, input: { installment: number; account: number; paid_on: string; principal?: Money | null; interest?: Money | null }) =>
    http.post<LoanDetail>(path(cid, `loans/${id}/pay/`), input),
  repayEarly: (cid: number, id: number, input: { account: number; paid_on: string; amount: Money; interest?: Money; mode: EarlyMode }) =>
    http.post<LoanDetail>(path(cid, `loans/${id}/repay-early/`), input),
  undo: (cid: number, id: number, transaction: number, reason: string) => http.post<LoanDetail>(path(cid, `loans/${id}/undo/`), { transaction, reason }),

  taxes: (cid: number, back = 1, ahead = 12) => http.get<TaxCalendar>(path(cid, "taxes/"), { back: String(back), ahead: String(ahead) }),
  candidates: (cid: number, deadline: string) => http.get<TaxCandidate[]>(path(cid, "taxes/candidates/"), { deadline }),
  mark: (cid: number, input: TaxMarkInput) => http.post<{ id: number }>(path(cid, "taxes/marks/"), input),
  unmark: (cid: number, id: number) => http.delete(path(cid, `taxes/marks/${id}/`)),
  compare: (cid: number) => http.get<TaxCompare>(path(cid, "taxes/compare/")),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useLoans() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "loans")),
    queryFn: () => creditApi.loans(cid.value),
    enabled: computed(() => cid.value > 0),
    staleTime: 20_000,
  });
}

export function useLoan(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "loan", { id: toValue(id) })),
    queryFn: () => creditApi.loan(cid.value, toValue(id) ?? 0),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 10_000,
  });
}

export function useTaxCalendar(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "taxes")),
    queryFn: () => creditApi.taxes(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
    retry: false,
  });
}

export function useTaxCompare(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "tax-compare")),
    queryFn: () => creditApi.compare(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// ─── Pure helpers (tested) ──────────────────────────────────────────────────

export const LINE_TONES: Record<LoanLineStatus, "success" | "info" | "neutral" | "danger"> = {
  paid: "success",
  partial: "info",
  due: "neutral",
  overdue: "danger",
};

export const TAX_TONES: Record<TaxStatus, "success" | "neutral" | "danger"> = {
  done: "success",
  due: "neutral",
  overdue: "danger",
};

/** How much of the principal is repaid, 0–100. */
export function repaidShare(loan: Pick<Loan, "amount" | "owed">): number {
  const amount = dec(loan.amount);
  if (amount.isZero()) return 0;
  const share = amount.minus(dec(loan.owed)).div(amount).times(100).toNumber();
  return Math.max(0, Math.min(100, Math.round(share)));
}

/** The deadlines in the order an owner reads them: overdue first, then the soonest; done ones last. */
export function deadlinesInOrder(rows: TaxDeadline[]): TaxDeadline[] {
  const rank = (row: TaxDeadline) => (row.status === "overdue" ? 0 : row.status === "due" ? 1 : 2);
  return [...rows].sort((a, b) => rank(a) - rank(b) || (rank(a) === 2 ? b.due_on.localeCompare(a.due_on) : a.due_on.localeCompare(b.due_on)) || a.key.localeCompare(b.key));
}

/** Deadlines grouped by the month they are due ("2026-12"), months in order. */
export function deadlinesByMonth(rows: TaxDeadline[]): Array<{ month: string; rows: TaxDeadline[] }> {
  const groups = new Map<string, TaxDeadline[]>();
  for (const row of [...rows].sort((a, b) => a.due_on.localeCompare(b.due_on) || a.key.localeCompare(b.key))) {
    const month = row.due_on.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), row]);
  }
  return [...groups.entries()].map(([month, list]) => ({ month, rows: list }));
}

/** A typed schedule row's principal parts add up to the loan (the server checks it again). */
export function principalGap(amount: Money | null, rows: ScheduleRow[]): string {
  let sum = dec(0);
  for (const row of rows) sum = sum.plus(dec(row.principal || "0"));
  return dec(amount || "0").minus(sum).toFixed(2);
}
