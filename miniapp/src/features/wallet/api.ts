/**
 * The employee payroll endpoints (`/companies/<id>/payroll/…`, backend/apps/payroll/api.py,
 * PLAN-OWNER §4.11 prefix E) as react-query hooks. Every key starts with ["wallet", company], so
 * one invalidation after a request, a dispute or "I received it" refreshes every card.
 *
 * Amounts arrive as decimal strings ("5200000.00") with a currency; screens show them through the
 * money helpers and never add them up.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { components } from "../../api/schema";

type Schemas = components["schemas"];

export type Earnings = Schemas["PayrollEarnings"];
export type EarningsSums = Schemas["PayrollEarningsSums"];
export type Proposed = Schemas["PayrollEarningsProposed"];
/** A bonus rule's progress: `op` says whether more or less is better, `limit` what an at-most rule that pays now must stay within. */
export type Progress = Schemas["PayrollEarningsProgress"];
export type Op = Schemas["PayrollRuleOpEnum"];
export type Adjustment = Schemas["Adjustment"];
export type AdjustmentKind = Schemas["PayrollAdjustmentKindEnum"];
export type Advance = Schemas["Advance"];
export type AdvanceCap = Schemas["PayrollAdvanceCap"];
export type MyAdvances = Schemas["PayrollMyAdvances"];
export type PayslipRow = Schemas["PayslipRow"];
export type Payslip = Schemas["PayrollPayslip"];
export type PayslipLine = Schemas["Line"];
export type AdvanceRequest = Schemas["PayrollAdvanceRequestRequest"];

export const walletKeys = {
  all: (company: number) => ["wallet", company] as const,
  earnings: (company: number) => ["wallet", company, "earnings"] as const,
  adjustments: (company: number) => ["wallet", company, "adjustments"] as const,
  advances: (company: number) => ["wallet", company, "advances"] as const,
  payslips: (company: number) => ["wallet", company, "payslips"] as const,
  payslip: (company: number, id: number) => ["wallet", company, "payslip", id] as const,
};

const base = (company: number) => `/companies/${company}/payroll`;

/** The server keeps "earned so far" for 10 minutes; asking more often only costs requests. */
const EARNINGS_STALE = 5 * 60_000;
const LIST_STALE = 60_000;

/** This month so far, the month's estimate, waiting bonuses and fines, and rule progress. */
export function useEarnings(company: number, enabled = true) {
  return useQuery({
    queryKey: walletKeys.earnings(company),
    queryFn: () => api<Earnings>(`${base(company)}/earnings/current/`),
    staleTime: EARNINGS_STALE,
    enabled,
  });
}

/** My bonuses, fines, allowances and deductions, newest month first. */
export function useAdjustments(company: number, enabled = true) {
  return useQuery({
    queryKey: walletKeys.adjustments(company),
    queryFn: () => api<Adjustment[]>(`${base(company)}/adjustments/`),
    staleTime: LIST_STALE,
    enabled,
  });
}

/** My advances and how much more I may ask for now (`cap.available`). */
export function useAdvances(company: number, enabled = true) {
  return useQuery({
    queryKey: walletKeys.advances(company),
    queryFn: () => api<MyAdvances>(`${base(company)}/advances/`),
    staleTime: LIST_STALE,
    enabled,
  });
}

/** My published and paid payslips, newest first. */
export function usePayslips(company: number, enabled = true) {
  return useQuery({
    queryKey: walletKeys.payslips(company),
    queryFn: () => api<PayslipRow[]>(`${base(company)}/payslips/`),
    staleTime: LIST_STALE,
    enabled,
  });
}

/** The list's copy of a payslip follows the detail: its "new" and "received" marks change at once. */
function patchList(client: QueryClient, company: number, payslip: Payslip): void {
  const { status, viewed_at, paid_at, received_at } = payslip;
  client.setQueryData<PayslipRow[]>(walletKeys.payslips(company), (rows) =>
    rows?.map((row) => (row.id === payslip.id ? { ...row, status, viewed_at, paid_at, received_at } : row)),
  );
}

/** One payslip with every line. Opening it marks it seen, so the list loses its "new" mark. */
export function usePayslip(company: number, id: number) {
  const client = useQueryClient();
  return useQuery({
    queryKey: walletKeys.payslip(company, id),
    queryFn: async () => {
      const payslip = await api<Payslip>(`${base(company)}/payslips/${id}/`);
      patchList(client, company, payslip);
      return payslip;
    },
  });
}

/** A fresh signed link to the payslip's PDF (they expire within minutes, so asked for on tap). */
export function payslipPdf(company: number, id: number): () => Promise<string> {
  return () => api<{ url: string }>(`${base(company)}/payslips/${id}/pdf/`).then((link) => link.url);
}

/** "I received it", for a paid payslip. */
export function useReceived(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Payslip>(`${base(company)}/payslips/${id}/received/`, { method: "POST" }),
    onSuccess: (payslip) => {
      client.setQueryData(walletKeys.payslip(company, payslip.id), payslip);
      patchList(client, company, payslip);
    },
  });
}

/** Dispute one of my fines or deductions, once, with a short explanation. */
export function useDispute(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) =>
      api<Adjustment>(`${base(company)}/adjustments/${id}/dispute/`, { json: { text } }),
    onSuccess: (row) => {
      client.setQueryData<Adjustment[]>(walletKeys.adjustments(company), (rows) => rows?.map((item) => (item.id === row.id ? row : item)));
      void client.invalidateQueries({ queryKey: walletKeys.adjustments(company) });
    },
  });
}

/** Ask for an advance. The cap and the month's estimate change with it. */
export function useRequestAdvance(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: AdvanceRequest) => api<Advance>(`${base(company)}/advances/`, { json: request }),
    onSuccess: () => client.invalidateQueries({ queryKey: walletKeys.all(company) }),
  });
}

/** Take back an advance request nobody has decided yet. */
export function useCancelAdvance(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Advance>(`${base(company)}/advances/${id}/cancel/`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: walletKeys.all(company) }),
  });
}
