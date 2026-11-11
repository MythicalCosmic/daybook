/**
 * Reports for banks and investors (v12): the balance sheet on a day (`finance/reports/balance-sheet/`),
 * what the business is worth (`finance/valuation/`) and the statement pack PDF
 * (`finance/statements/`: options, list, prepare, progress). Types are hand-written next to the
 * calls (the lead regenerates the OpenAPI types); keys live under `[companyId, "finance"]`, so every
 * finance pulse refreshes them with the rest of the module.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import type { Money } from "@/api/types";
import { downloadExport } from "@/lib/useExport";
import { useCompanyId } from "@/stores/company";

import { financeKeys } from "./api";

// ─── Types ──────────────────────────────────────────────────────────────────

export type SheetLineKey =
  | "cash_on_hand"
  | "bank"
  | "in_transit"
  | "customers"
  | "staff_owe_us"
  | "loans_given"
  | "other_receivable"
  | "stock_at_cost"
  | "fixed_assets_book"
  | "suppliers"
  | "loans_current"
  | "loans_long"
  | "taxes"
  | "staff"
  | "dividends"
  | "other_payable"
  | "owner_put_in"
  | "owner_taken_out"
  | "retained"
  | "net_assets"
  | "profit_recorded"
  | "opening_balances"
  | "older_fixed_assets"
  | "revaluation"
  | "dividends_declared";

export type SheetSectionKey = "cash" | "receivables" | "stock" | "fixed_assets" | "current" | "long_term";

export interface SheetLine {
  key: SheetLineKey;
  amount: Money;
  count?: number;
  cost?: Money;
}

export interface SheetSection {
  key: SheetSectionKey;
  lines: SheetLine[];
  total: Money;
}

export type GapKey = "no_books" | "no_opening" | "no_rate" | "negative_account" | "no_stock_module" | "stock_history" | "no_assets_module" | "pending" | "unexplained";

export interface SheetGap {
  key: GapKey;
  params: Record<string, string | number | string[]>;
}

export interface BalanceSheet {
  on: string;
  currency: string;
  whole_company: boolean;
  books_start: string | null;
  assets: { sections: SheetSection[]; total: Money };
  liabilities: { sections: SheetSection[]; total: Money };
  equity: { lines: SheetLine[]; total: Money };
  check: { assets: Money; liabilities_and_equity: Money; balanced: boolean };
  current_assets: Money;
  current_liabilities: Money;
  accounts: { id: number; name: string; kind: string; currency: string; branch_id: number | null; balance: Money; base: Money | null }[];
  foreign: { currency: string; amount: Money; base: Money | null; rate: string | null; rate_date: string; stale: boolean }[];
  rate: { rate: string | null; stale: boolean; source: string; date: string };
  complete: boolean;
  reconciliation: { lines: SheetLine[]; retained: Money; unexplained: Money } | null;
  gaps: SheetGap[];
}

export interface Valuation {
  on: string;
  currency: string;
  multiple_low: string;
  multiple_high: string;
  default_low: string;
  default_high: string;
  earnings: {
    from: string;
    to: string;
    days: number;
    enough: boolean;
    profit: Money;
    lines: { key: "profit" | "depreciation" | "interest" | "equipment"; amount: Money }[];
    earnings: Money;
    yearly: Money | null;
  };
  earnings_method: {
    applies: boolean;
    reason: "too_early" | "loss" | null;
    business_low: Money | null;
    business_high: Money | null;
    cash: Money;
    debt: Money;
    low: Money | null;
    high: Money | null;
  };
  net_assets: { value: Money; assets: Money; liabilities: Money; stock: Money | null; fixed_assets: Money | null };
  range: { low: Money; high: Money };
  editable: boolean;
}

export type PackPeriod = "month" | "quarter" | "year";
export type PackPurpose = "bank" | "partner" | "sale";
export type PackLanguage = "uz" | "ru" | "en";
export type PackStatus = "pending" | "running" | "ready" | "failed";

export interface StatementPack {
  id: number;
  period: PackPeriod;
  start: string;
  end: string;
  purpose: PackPurpose;
  language: PackLanguage;
  branches: number[] | null;
  status: PackStatus;
  progress: number;
  pages: number | null;
  error: string;
  deliver_telegram: boolean;
  created_at: string;
  finished_at: string | null;
  expires_at: string;
  file_name: string | null;
  file_url: string | null;
}

export interface StatementOptions {
  today: string;
  books_start: string | null;
  last_activity: string | null;
  language: PackLanguage;
  whole_company: boolean;
  may_prepare: boolean;
  telegram: boolean;
}

export interface PackRequest {
  period: PackPeriod;
  of: string;
  purpose: PackPurpose;
  language: PackLanguage;
  branch?: number[];
  multiple_low?: string;
  multiple_high?: string;
  deliver_telegram?: boolean;
}

// ─── Calls ──────────────────────────────────────────────────────────────────

const path = (companyId: number, rest: string) => ownerPath(companyId, `finance/${rest}`);

export const statementsApi = {
  balanceSheet: (cid: number, query: Query) => http.get<BalanceSheet>(path(cid, "reports/balance-sheet/"), query),
  valuation: (cid: number, query: Query = {}) => http.get<Valuation>(path(cid, "valuation/"), query),
  setMultiples: (cid: number, body: { multiple_low: string | null; multiple_high: string | null }) => http.patch<Valuation>(path(cid, "valuation/"), body),
  options: (cid: number) => http.get<StatementOptions>(path(cid, "statements/options/")),
  packs: (cid: number) => http.get<StatementPack[]>(path(cid, "statements/")),
  pack: (cid: number, id: number, signal?: AbortSignal) => http.get<StatementPack>(path(cid, `statements/${id}/`), undefined, { signal }),
  prepare: (cid: number, body: PackRequest) => http.post<{ id: number }>(path(cid, "statements/"), body),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useBalanceSheet(params: MaybeRefOrGetter<Query>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "balance-sheet", { ...toValue(params) })),
    queryFn: () => statementsApi.balanceSheet(cid.value, toValue(params)),
    enabled: computed(() => cid.value > 0),
    staleTime: 20_000,
  });
}

export function useValuation(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "valuation")),
    queryFn: () => statementsApi.valuation(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
    retry: false,
  });
}

export function useStatementOptions(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "statement-options")),
    queryFn: () => statementsApi.options(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

export function useStatementPacks(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, "statement-packs")),
    queryFn: () => statementsApi.packs(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 10_000,
  });
}

export function useSetMultiples() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { multiple_low: string | null; multiple_high: string | null }) => statementsApi.setMultiples(cid.value, body),
    onSuccess: (data) => {
      client.setQueryData(financeKeys.of(cid.value, "valuation"), data);
    },
  });
}

// ─── Preparing a pack ───────────────────────────────────────────────────────

const POLL_MS = 1200;
const GIVE_UP_MS = 5 * 60_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Prepare a pack and follow it: `progress` moves as the server builds it, and when it is ready
 * the PDF downloads at once (`autoDownload`). `stop()` stops following (the pack still finishes
 * and stays in the list for 7 days).
 */
export function usePreparePack() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const pack = ref<StatementPack | null>(null);
  const running = ref(false);
  const error = ref<unknown>(null);
  let controller: AbortController | null = null;

  async function start(request: PackRequest, { autoDownload = true } = {}): Promise<StatementPack | null> {
    if (running.value) return null;
    running.value = true;
    error.value = null;
    pack.value = null;
    controller = new AbortController();
    const signal = controller.signal;
    try {
      const { id } = await statementsApi.prepare(cid.value, request);
      const started = Date.now();
      while (!signal.aborted && Date.now() - started < GIVE_UP_MS) {
        const current = await statementsApi.pack(cid.value, id, signal);
        pack.value = current;
        if (current.status === "ready" || current.status === "failed") {
          void client.invalidateQueries({ queryKey: financeKeys.of(cid.value, "statement-packs") });
          if (current.status === "ready" && autoDownload) downloadExport(current);
          return current;
        }
        await sleep(POLL_MS);
      }
      return pack.value;
    } catch (caught) {
      if (!signal.aborted) error.value = caught;
      return null;
    } finally {
      running.value = false;
    }
  }

  function stop(): void {
    controller?.abort();
    running.value = false;
  }

  return { pack, running, error, start, stop };
}

/** Download a ready pack again (its signed link is fetched fresh: it lasts 10 minutes). */
export async function downloadPack(cid: number, id: number): Promise<void> {
  const fresh = await statementsApi.pack(cid, id);
  if (fresh.status === "ready") downloadExport(fresh);
}

// ─── Periods ────────────────────────────────────────────────────────────────

export interface PeriodChoice {
  key: string;
  period: PackPeriod;
  of: string;
  /** "2026-10", "2026-Q3", "2026": the label is the caller's. */
  start: string;
  end: string;
  partial: boolean;
}

function iso(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function lastDay(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/**
 * The periods a pack can cover, the latest first: months, quarters or years from today back to
 * when the books start (at most `limit`). The one in progress ends today.
 */
export function periodChoices(period: PackPeriod, today: string, booksStart: string | null, limit = 12): PeriodChoice[] {
  const [year, month] = today.split("-").map(Number);
  const first = booksStart ?? today;
  const choices: PeriodChoice[] = [];
  const span = period === "month" ? 1 : period === "quarter" ? 3 : 12;
  let startYear = year;
  let startMonth = period === "year" ? 1 : period === "quarter" ? 3 * Math.floor((month - 1) / 3) + 1 : month;
  while (choices.length < limit) {
    const start = iso(startYear, startMonth, 1);
    const endIndex = startYear * 12 + startMonth - 1 + span - 1;
    const endYear = Math.floor(endIndex / 12);
    const endMonth = (endIndex % 12) + 1;
    const fullEnd = iso(endYear, endMonth, lastDay(endYear, endMonth));
    if (fullEnd < first) break;
    const partial = fullEnd > today;
    const key = period === "month" ? start.slice(0, 7) : period === "quarter" ? `${startYear}-Q${(startMonth - 1) / 3 + 1}` : String(startYear);
    choices.push({ key, period, of: start, start, end: partial ? today : fullEnd, partial });
    const back = startYear * 12 + startMonth - 1 - span;
    startYear = Math.floor(back / 12);
    startMonth = (back % 12) + 1;
  }
  return choices;
}
