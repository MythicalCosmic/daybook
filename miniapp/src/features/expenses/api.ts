/**
 * The employee finance endpoints for expense claims (`/companies/<id>/finance/…`, PLAN-OWNER
 * §4.7 prefix E, the v6-i contract §7), typed by hand until the lead regenerates `schema.d.ts`.
 * Every key starts with ["expenses", company], so one invalidation after sending or cancelling
 * a claim refreshes the list, the Me row and the summary.
 *
 * Money is a decimal string ("450000.00") with its currency; `spent_on` is a company-local day
 * ("2026-11-05"); `created_at` and `decided_at` are moments (ISO 8601).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiForm } from "../../api/client";
import { downscale } from "../../lib/image";

export type Ref = { id: number; name: string };
export type PersonRef = { id: number; name: string; photo_url: string | null };
export type CategoryRef = { id: number; name: string; kind: "income" | "expense"; color: string; parent_id: number | null };

export type ClaimStatus = "submitted" | "approved" | "rejected" | "paid" | "cancelled";
export type PaidFrom = "own_money" | "held_cash";

export type ClaimReceipt = { id: number; url: string; thumb_url: string | null; content_type: string; is_image: boolean };

export type Claim = {
  id: number;
  member: PersonRef;
  amount: string;
  currency: string;
  category: CategoryRef;
  spent_on: string;
  description: string;
  paid_from: PaidFrom;
  status: ClaimStatus;
  /** The server's own words for the status, for a status this app doesn't know yet. */
  status_label: string;
  branch: Ref | null;
  receipts: ClaimReceipt[];
  created_at: string;
  decided_by: PersonRef | null;
  decided_at: string | null;
  reject_reason: string;
  /** How money paid from my own pocket comes back; null for company cash I hold. */
  reimburse_via: "payroll" | "cash" | null;
  transaction_id: number | null;
  debt_id: number | null;
  can_decide: boolean;
  can_pay: boolean;
  can_cancel: boolean;
};

/** An active expense category (`categories/`); `parent_id` groups children under their parent. */
export type ExpenseCategory = { id: number; name: string; parent_id: number | null; icon: string; color: string };

/** A company account in my hands (a courier's or a manager's cash). */
export type HeldAccount = { account_id: number; name: string; balance: string; currency: string };

/** `wallet/`: what I hold for the company, what it owes me, and the company's claim rules. */
export type ClaimWallet = {
  currency: string;
  held: HeldAccount[];
  held_total: string;
  owed_to_me: string;
  /** Claims under this are recorded at once; null: every claim waits for approval. */
  approval_threshold: string | null;
  /** Claims over this need a receipt; null: never required. */
  receipt_required_over: string | null;
};

/** A new claim as `POST claims/` takes it (multipart: the receipts travel with it). */
export type ClaimInput = {
  amount: string;
  category: number;
  spent_on: string;
  description: string;
  paid_from: PaidFrom;
  receipts: File[];
};

export const expensesKeys = {
  all: (company: number) => ["expenses", company] as const,
  claims: (company: number) => ["expenses", company, "claims"] as const,
  categories: (company: number) => ["expenses", company, "categories"] as const,
  wallet: (company: number) => ["expenses", company, "wallet"] as const,
};

const base = (company: number) => `/companies/${company}/finance`;

const LIST_STALE = 30_000;
/** Owners rarely change categories; a form opened twice in a row needn't ask again. */
const CATEGORIES_STALE = 5 * 60_000;

/** My claims, newest first (the server sends at most 100). */
export function useClaims(company: number, enabled = true) {
  return useQuery({
    queryKey: expensesKeys.claims(company),
    queryFn: () => api<Claim[]>(`${base(company)}/claims/`),
    staleTime: LIST_STALE,
    enabled,
  });
}

/** The active expense categories, in the company's order. */
export function useCategories(company: number, enabled = true) {
  return useQuery({
    queryKey: expensesKeys.categories(company),
    queryFn: () => api<ExpenseCategory[]>(`${base(company)}/categories/`),
    staleTime: CATEGORIES_STALE,
    enabled,
  });
}

/** Company cash I hold, what is owed to me, and the approval and receipt limits. */
export function useClaimWallet(company: number, enabled = true) {
  return useQuery({
    queryKey: expensesKeys.wallet(company),
    queryFn: () => api<ClaimWallet>(`${base(company)}/wallet/`),
    staleTime: LIST_STALE,
    enabled,
  });
}

/**
 * Send a claim. Receipt photos are made smaller inside the request (a PDF goes as it is), so the
 * button stays busy meanwhile and a second tap can't send the claim twice.
 */
export function useSubmitClaim(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ receipts, ...fields }: ClaimInput) => {
      const files = await Promise.all(receipts.map((file) => downscale(file)));
      return apiForm<Claim>(`${base(company)}/claims/`, { ...fields, receipts: files });
    },
    onSuccess: (claim) => {
      // The new claim tops the list at once; the refetch brings the wallet's sums.
      client.setQueryData<Claim[]>(expensesKeys.claims(company), (rows) => (rows ? [claim, ...rows.filter((row) => row.id !== claim.id)] : rows));
      void client.invalidateQueries({ queryKey: expensesKeys.claims(company) });
      void client.invalidateQueries({ queryKey: expensesKeys.wallet(company) });
    },
  });
}

/** Take back a claim nobody has decided yet. */
export function useCancelClaim(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<Claim>(`${base(company)}/claims/${id}/cancel/`, { method: "POST" }),
    onSuccess: (claim) => {
      client.setQueryData<Claim[]>(expensesKeys.claims(company), (rows) => rows?.map((row) => (row.id === claim.id ? claim : row)));
      void client.invalidateQueries({ queryKey: expensesKeys.claims(company) });
      void client.invalidateQueries({ queryKey: expensesKeys.wallet(company) });
    },
  });
}
