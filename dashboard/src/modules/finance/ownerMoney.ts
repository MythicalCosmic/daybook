/**
 * The owner's money (v11): the safe amount to take out today with its reasons, draws and
 * contributions, planned purchases, partners and dividends (`finance/owner-money/`,
 * `finance/partners/`, `finance/dividends/`). Types are hand-written next to the calls (the lead
 * regenerates the OpenAPI types); keys live under `[companyId, "finance"]`, so every finance
 * pulse refreshes them with the rest of the module.
 */
import { useMutation, useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import type { Money } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import { financeKeys, useRefresh } from "./api";

// ─── Types ──────────────────────────────────────────────────────────────────

export type ReasonKind = "bill" | "auto" | "tax" | "payable" | "payroll" | "loan" | "installment";

export interface Reason {
  key: string;
  kind: ReasonKind;
  title: string;
  subtitle: string;
  date: string;
  amount: Money | null;
  count: number;
  overdue: boolean;
  estimate: boolean;
  url: string;
}

export interface PlannedPurchase {
  id: number;
  title: string;
  amount: Money;
  due_on: string | null;
  branch: { id: number; name: string } | null;
  done: boolean;
}

export interface FlowRow {
  id: number;
  occurred_on: string;
  direction: "in" | "out";
  amount: Money;
  currency: string;
  base_amount: Money;
  account: { id: number; name: string; kind: string };
  description: string;
  person: string | null;
  dividend: boolean;
  created_by: string | null;
}

export interface Flows {
  from: string;
  to: string;
  drawn: Money;
  put_in: Money;
  net: Money;
  count: number;
  rows: FlowRow[];
}

export interface Suggestion {
  today: string;
  currency: string;
  days: number;
  monthly: Money;
  dates: string[];
  buffer: Money;
  low: { date: string | null; balance: Money };
  below_buffer_on: string | null;
  /** Net profit per month over the last three full months. */
  profit_average: Money;
  /** The monthly amount is more than that: it would come out of the business's capital. */
  above_profit: boolean;
}

export interface MonthPoint {
  month: string;
  profit: Money;
  drawn: Money;
  put_in: Money;
}

export interface DrawAccount {
  id: number;
  name: string;
  kind: string;
  currency: string;
  balance: Money;
  branch_id: number | null;
}

export interface OwnerMoney {
  today: string;
  currency: string;
  horizon_days: number;
  until: string;
  cash: Money;
  personal: Money;
  complete: boolean;
  due: Money;
  reasons: Reason[];
  unknown: number;
  buffer: { amount: Money; auto: boolean; fixed_costs: Money };
  planned: Money;
  purchases: { kept: PlannedPurchase[]; later: PlannedPurchase[] };
  safe: Money;
  short: Money;
  month: Flows;
  suggestion: Suggestion;
  history: MonthPoint[];
  accounts: DrawAccount[];
  settings: { cash_buffer: Money | null; draw_horizon_days: number };
  partners: number;
  is_owner: boolean;
}

export interface MoveInput {
  account: number;
  amount: Money;
  occurred_on?: string;
  description?: string;
  confirmed?: boolean;
}

export interface MoveResult {
  id: number;
  occurred_on: string;
  amount: Money;
  account: number;
  safe: Money;
}

export interface Partner {
  id: number;
  key: string;
  name: string;
  member: { id: number; name: string } | null;
  share: string;
  starts_on: string;
  ends_on: string | null;
}

export interface Partners {
  current: Partner[];
  history: Partner[];
  since: string | null;
  people: Array<{ id: number; name: string }>;
}

export interface PartnerRowInput {
  member?: number | null;
  name?: string;
  share: string;
}

export interface ProfitShare {
  from: string;
  to: string;
  currency: string;
  profit: Money;
  partners: Array<{ key: string; name: string; membership_id: number | null; share: string; profit: Money; dividends_paid: Money; dividends_due: Money }>;
  unassigned_share: string;
}

export type DividendStatus = "draft" | "partly_paid" | "paid" | "cancelled";

export interface DividendLine {
  id: number;
  partner: { id: number; name: string; member_id: number | null };
  share: string;
  amount: Money;
  paid: boolean;
  paid_on: string | null;
  account: { id: number; name: string } | null;
  transaction_id: number | null;
}

export interface Dividend {
  id: number;
  period_start: string;
  period_end: string;
  amount: Money;
  profit: Money | null;
  status: DividendStatus;
  note: string;
  paid_amount: Money;
  paid_at: string | null;
  created_at: string;
  lines: DividendLine[];
}

export interface DividendSuggestion {
  from: string;
  to: string;
  currency: string;
  profit: Money;
  already: Money;
  safe: Money;
  amount: Money;
  limited_by: "safe" | "profit";
  split: Array<{ partner_id: number; name: string; share: string; amount: Money }>;
}

// ─── Endpoints ──────────────────────────────────────────────────────────────

const path = (cid: number, rest: string) => ownerPath(cid, `finance/${rest}`);

export const ownerMoneyApi = {
  summary: (cid: number) => http.get<OwnerMoney>(path(cid, "owner-money/")),
  take: (cid: number, input: MoveInput) => http.post<MoveResult>(path(cid, "owner-money/take/"), input, { toast: false }),
  put: (cid: number, input: MoveInput) => http.post<MoveResult>(path(cid, "owner-money/put/"), input, { toast: false }),
  settings: (cid: number, input: { cash_buffer?: Money | null; draw_horizon_days?: number }) =>
    http.patch<{ cash_buffer: Money | null; draw_horizon_days: number }>(path(cid, "owner-money/settings/"), input),
  addPurchase: (cid: number, input: { title: string; amount: Money; due_on?: string | null }) => http.post<PlannedPurchase>(path(cid, "owner-money/purchases/"), input),
  updatePurchase: (cid: number, id: number, input: Partial<{ title: string; amount: Money; due_on: string | null; done: boolean }>) =>
    http.patch<PlannedPurchase>(path(cid, `owner-money/purchases/${id}/`), input),
  removePurchase: (cid: number, id: number) => http.delete(path(cid, `owner-money/purchases/${id}/`)),

  partners: (cid: number) => http.get<Partners>(path(cid, "partners/")),
  setPartners: (cid: number, input: { effective_on: string; partners: PartnerRowInput[] }) => http.put<Partners>(path(cid, "partners/"), input),
  profitShare: (cid: number, range: { from: string; to: string }) => http.get<ProfitShare>(path(cid, "partners/profit-share/"), range),

  dividends: (cid: number) => http.get<Dividend[]>(path(cid, "dividends/")),
  suggest: (cid: number, range: { from: string; to: string }) => http.get<DividendSuggestion>(path(cid, "dividends/suggest/"), range),
  createDividend: (cid: number, input: { period_start: string; period_end: string; amount: Money; note?: string }) => http.post<Dividend>(path(cid, "dividends/"), input),
  updateDividend: (cid: number, id: number, input: { amount?: Money; note?: string }) => http.patch<Dividend>(path(cid, `dividends/${id}/`), input),
  payDividend: (cid: number, id: number, input: { account: number; paid_on?: string; lines?: number[] }) => http.post<Dividend>(path(cid, `dividends/${id}/pay/`), input),
  cancelDividend: (cid: number, id: number, reason: string) => http.post<Dividend>(path(cid, `dividends/${id}/cancel/`), { reason }),
  undoLine: (cid: number, id: number, line: number, reason: string) => http.post<Dividend>(path(cid, `dividends/${id}/lines/${line}/undo/`), { reason }),
};

// ─── Queries ────────────────────────────────────────────────────────────────

function useResource<T>(resource: string, params: MaybeRefOrGetter<Record<string, unknown>>, fetcher: (cid: number, params: Record<string, unknown>) => Promise<T>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, resource, toValue(params))),
    queryFn: () => fetcher(cid.value, toValue(params)),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 20_000,
  });
}

export const useOwnerMoney = () => useResource("owner-money", {}, (cid) => ownerMoneyApi.summary(cid));
export const usePartners = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("partners", {}, (cid) => ownerMoneyApi.partners(cid), enabled);
export const useProfitShare = (range: MaybeRefOrGetter<{ from: string; to: string } | null>) =>
  useResource(
    "profit-share",
    () => ({ ...(toValue(range) ?? {}) }),
    (cid, p) => ownerMoneyApi.profitShare(cid, { from: String(p.from), to: String(p.to) }),
    () => !!toValue(range),
  );
export const useDividends = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("dividends", {}, (cid) => ownerMoneyApi.dividends(cid), enabled);
export const useDividendSuggestion = (range: MaybeRefOrGetter<{ from: string; to: string } | null>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource(
    "dividend-suggest",
    () => ({ ...(toValue(range) ?? {}) }),
    (cid, p) => ownerMoneyApi.suggest(cid, { from: String(p.from), to: String(p.to) }),
    () => !!toValue(range) && toValue(enabled),
  );

/** A write, then the module's queries and the shell's pulse refresh. */
export function useOwnerMoneyWrite<I, O>(call: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (input: I) => call(cid.value, input), onSuccess: refresh });
}

// ─── Helpers (pure, tested) ─────────────────────────────────────────────────

/** Cash split for the hero bar: what goes to payments, the buffer, planned purchases and the safe
 * part, each as a share of the cash (0–100, adding up to 100 when the cash covers everything). */
export function cashSplit(data: Pick<OwnerMoney, "cash" | "due" | "buffer" | "planned" | "safe">): Array<{ key: "due" | "buffer" | "planned" | "safe"; amount: number; share: number }> {
  const cash = Math.max(Number(data.cash), 0);
  const parts = [
    { key: "due" as const, amount: Math.max(Number(data.due), 0) },
    { key: "buffer" as const, amount: Math.max(Number(data.buffer.amount), 0) },
    { key: "planned" as const, amount: Math.max(Number(data.planned), 0) },
    { key: "safe" as const, amount: Math.max(Number(data.safe), 0) },
  ];
  const whole = Math.max(cash, parts.reduce((sum, part) => sum + part.amount, 0));
  if (!whole) return parts.map((part) => ({ ...part, share: 0 }));
  let left = 100;
  return parts.map((part, index) => {
    const share = index === parts.length - 1 ? Math.max(left, 0) : Math.min(left, (part.amount / whole) * 100);
    left -= share;
    return { ...part, share: Math.round(share * 10) / 10 };
  });
}

/** Shares typed in the partners dialog: their sum, and whether they make exactly 100 %. */
export function sharesTotal(rows: Array<{ share: number | null }>): { total: number; exact: boolean } {
  const cents = rows.reduce((sum, row) => sum + Math.round((row.share ?? 0) * 100), 0);
  return { total: cents / 100, exact: cents === 10000 };
}

/** A dividend split as the server does it: by share to the tiyin, the rounding to the biggest. */
export function splitByShares(amount: number, shares: number[]): number[] {
  if (!shares.length) return [];
  const cents = Math.round(amount * 100);
  const parts = shares.map((share) => Math.round((cents * share) / 100));
  let biggest = 0;
  shares.forEach((share, index) => {
    if (share > (shares[biggest] ?? 0)) biggest = index;
  });
  parts[biggest] = (parts[biggest] ?? 0) + cents - parts.reduce((sum, part) => sum + part, 0);
  return parts.map((part) => part / 100);
}

/** The quarter before the one `today` falls in, as dates. */
export function lastQuarter(today: string): { from: string; to: string } {
  const [year, month] = today.split("-").map(Number) as [number, number];
  const quarter = Math.floor((month - 1) / 3);
  const startMonth = quarter === 0 ? 10 : quarter * 3 - 2;
  const startYear = quarter === 0 ? year - 1 : year;
  const endMonth = startMonth + 2;
  const lastDay = new Date(Date.UTC(startYear, endMonth, 0)).getUTCDate();
  const pad = (n: number) => String(n).padStart(2, "0");
  return { from: `${startYear}-${pad(startMonth)}-01`, to: `${startYear}-${pad(endMonth)}-${pad(lastDay)}` };
}
