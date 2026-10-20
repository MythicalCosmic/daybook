/**
 * The finance endpoints (plan §4.7) as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "finance"]`, so the `finance.*` pulse keys (`invalidates` in
 * index.ts) refresh every query of the module, and switching company never shows another
 * company's money. Every write refreshes the module's queries; a few (categorizing an entry,
 * moving a category) also update the cache at once and roll back on error.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import type { DateRangeValue } from "@/lib/dateRange";
import { useCompanyStore } from "@/stores/company";

import type {
  Account,
  AccountInput,
  AccountsResponse,
  Aging,
  Balances,
  BulkResult,
  CashFlow,
  CategoryInput,
  CategoryNode,
  CategoryTrend,
  Counterparty,
  CounterpartyDetail,
  CounterpartyInput,
  Debt,
  DebtDetail,
  DebtInput,
  DebtSummary,
  FinanceSettings,
  Installment,
  Options,
  Overview,
  PaymentInput,
  Pnl,
  RateRow,
  Rates,
  Receipt,
  Statement,
  Transaction,
  TransactionInput,
  TransactionPage,
  TransactionPatch,
  Transfer,
  TransferInput,
} from "./types";

export const MODULE = "finance";

const path = (companyId: number, rest: string) => ownerPath(companyId, `finance/${rest}`);

/**
 * Query parameters of a period: a preset goes as `preset` (so the server compares "this month"
 * with the same days of last month, exactly as the picker shows), a custom range as `from`/`to`.
 */
export function periodParams(value: DateRangeValue): Record<string, string> {
  const params: Record<string, string> = value.preset === "custom" ? { from: value.range.from, to: value.range.to } : { preset: value.preset };
  if (value.compare !== "none") params.compare = value.compare;
  return params;
}

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const financeApi = {
  overview: (cid: number) => http.get<Overview>(path(cid, "overview/")),
  options: (cid: number) => http.get<Options>(path(cid, "options/")),

  accounts: (cid: number, archived = false) => http.get<AccountsResponse>(path(cid, "accounts/"), archived ? { archived: "true" } : undefined),
  account: (cid: number, id: number) => http.get<Account>(path(cid, `accounts/${id}/`)),
  createAccount: (cid: number, input: AccountInput) => http.post<Account>(path(cid, "accounts/"), input),
  updateAccount: (cid: number, id: number, input: Partial<AccountInput>) => http.patch<Account>(path(cid, `accounts/${id}/`), input),
  archiveAccount: (cid: number, id: number) => http.post<Account>(path(cid, `accounts/${id}/archive/`)),
  reopenAccount: (cid: number, id: number) => http.post<Account>(path(cid, `accounts/${id}/reopen/`)),
  statement: (cid: number, id: number, range: { from: string; to: string }) => http.get<Statement>(path(cid, `accounts/${id}/statement/`), range),

  categories: (cid: number) => http.get<CategoryNode[]>(path(cid, "categories/")),
  createCategory: (cid: number, input: CategoryInput) => http.post<CategoryNode>(path(cid, "categories/"), input),
  updateCategory: (cid: number, id: number, input: Partial<CategoryInput> & { is_active?: boolean }) => http.patch<CategoryNode>(path(cid, `categories/${id}/`), input),
  deleteCategory: (cid: number, id: number) => http.delete(path(cid, `categories/${id}/`)),
  mergeCategory: (cid: number, id: number, into: number) => http.post<CategoryNode[]>(path(cid, `categories/${id}/merge/`), { into }),
  moveCategory: (cid: number, id: number, parent: number | null, index: number) => http.post<CategoryNode[]>(path(cid, `categories/${id}/move/`), { parent, index }),

  counterparties: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Page<Counterparty>>(path(cid, "counterparties/"), params, { signal }),
  counterparty: (cid: number, id: number) => http.get<CounterpartyDetail>(path(cid, `counterparties/${id}/`)),
  createCounterparty: (cid: number, input: CounterpartyInput) => http.post<Counterparty>(path(cid, "counterparties/"), input),
  updateCounterparty: (cid: number, id: number, input: CounterpartyInput) => http.patch<Counterparty>(path(cid, `counterparties/${id}/`), input),

  transactions: (cid: number, params: Query, signal?: AbortSignal) => http.get<TransactionPage>(path(cid, "transactions/"), params, { signal }),
  transaction: (cid: number, id: number) => http.get<Transaction>(path(cid, `transactions/${id}/`)),
  createTransaction: (cid: number, input: TransactionInput) => http.post<Transaction>(path(cid, "transactions/"), input),
  updateTransaction: (cid: number, id: number, patch: TransactionPatch) => http.patch<Transaction>(path(cid, `transactions/${id}/`), patch),
  voidTransaction: (cid: number, id: number, reason: string) => http.post<Transaction>(path(cid, `transactions/${id}/void/`), { reason }),
  bulk: (cid: number, ids: number[], action: "categorize" | "void", extra: { category?: number; reason?: string }) =>
    http.post<{ results: BulkResult[] }>(path(cid, "transactions/bulk/"), { ids, action, ...extra }),
  uploadReceipt: (cid: number, file: File, transactionId?: number) => {
    const form = new FormData();
    form.append("file", file);
    return http.form<Receipt>(path(cid, transactionId ? `transactions/${transactionId}/receipts/` : "receipts/"), form);
  },
  removeReceipt: (cid: number, transactionId: number, receiptId: number) => http.delete(path(cid, `transactions/${transactionId}/receipts/${receiptId}/`)),

  transfers: (cid: number, params: Query = {}) => http.get<Page<Transfer>>(path(cid, "transfers/"), params),
  createTransfer: (cid: number, input: TransferInput) => http.post<Transfer>(path(cid, "transfers/"), input),
  voidTransfer: (cid: number, id: number, reason: string) => http.post<Transfer>(path(cid, `transfers/${id}/void/`), { reason }),

  debts: (cid: number, params: Query, signal?: AbortSignal) => http.get<Page<Debt>>(path(cid, "debts/"), params, { signal }),
  debtSummary: (cid: number) => http.get<DebtSummary>(path(cid, "debts/summary/")),
  debt: (cid: number, id: number) => http.get<DebtDetail>(path(cid, `debts/${id}/`)),
  createDebt: (cid: number, input: DebtInput) => http.post<Debt>(path(cid, "debts/"), input),
  updateDebt: (cid: number, id: number, input: { due_on?: string | null; description?: string; responsible?: number | null; branch?: number | null }) =>
    http.patch<Debt>(path(cid, `debts/${id}/`), input),
  payDebt: (cid: number, id: number, input: PaymentInput) => http.post<Transaction>(path(cid, `debts/${id}/payments/`), input),
  writeOffDebt: (cid: number, id: number, reason: string, amount?: string | null) => http.post<Transaction>(path(cid, `debts/${id}/write-off/`), { reason, amount: amount || null }),
  cancelDebt: (cid: number, id: number, reason: string) => http.post<Debt>(path(cid, `debts/${id}/cancel/`), { reason }),
  setInstallments: (cid: number, id: number, installments: Array<{ due_on: string; amount: string }>) =>
    http.put<Installment[]>(path(cid, `debts/${id}/installments/`), { installments }),

  rates: (cid: number) => http.get<Rates>(path(cid, "rates/")),
  setRate: (cid: number, date: string, rate: string) => http.post<RateRow>(path(cid, "rates/"), { currency: "USD", date, rate }),
  deleteRate: (cid: number, id: number) => http.delete(path(cid, `rates/${id}/`)),
  fetchRate: (cid: number) => http.post<{ ok: boolean; rate: string | null; detail: string }>(path(cid, "rates/fetch/"), {}, { toast: false }),

  pnl: (cid: number, params: Query) => http.get<Pnl>(path(cid, "reports/pnl/"), params),
  cashFlow: (cid: number, params: Query) => http.get<CashFlow>(path(cid, "reports/cash-flow/"), params),
  balances: (cid: number, params: Query) => http.get<Balances>(path(cid, "reports/balances/"), params),
  aging: (cid: number, params: Query) => http.get<Aging>(path(cid, "reports/debts-aging/"), params),
  categoryTrend: (cid: number, params: Query) => http.get<CategoryTrend>(path(cid, "reports/category-trend/"), params),

  settings: (cid: number) => http.get<FinanceSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<FinanceSettings>) => http.patch<FinanceSettings>(path(cid, "settings/"), input),
  lock: (cid: number, until: string | null) => http.post<FinanceSettings>(path(cid, "settings/lock/"), { until }),
};

// ─── Keys ───────────────────────────────────────────────────────────────────

export const financeKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

function useResource<T>(resource: string, params: MaybeRefOrGetter<Record<string, unknown>>, fetcher: (cid: number, params: Record<string, unknown>) => Promise<T>, options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number } = {}) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => financeKeys.of(cid.value, resource, toValue(params))),
    queryFn: () => fetcher(cid.value, toValue(params)),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

export const useOverview = () => useResource("overview", {}, (cid) => financeApi.overview(cid));
export const useOptions = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("options", {}, (cid) => financeApi.options(cid), { enabled, staleTime: 60_000 });
export const useAccounts = (archived: MaybeRefOrGetter<boolean> = false) =>
  useResource("accounts", () => ({ archived: toValue(archived) }), (cid, p) => financeApi.accounts(cid, Boolean(p.archived)), { keepPrevious: true });
export const useAccount = (id: MaybeRefOrGetter<number>) => useResource("account", () => ({ id: toValue(id) }), (cid, p) => financeApi.account(cid, Number(p.id)));
export const useStatement = (id: MaybeRefOrGetter<number>, range: MaybeRefOrGetter<{ from: string; to: string }>) =>
  useResource("statement", () => ({ id: toValue(id), ...toValue(range) }), (cid, p) => financeApi.statement(cid, Number(p.id), { from: String(p.from), to: String(p.to) }), { keepPrevious: true });
export const useCategories = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("categories", {}, (cid) => financeApi.categories(cid), { enabled, staleTime: 60_000 });
export const useCounterparties = (params: MaybeRefOrGetter<Query>) =>
  useResource("counterparties", () => ({ ...toValue(params) }), (cid, p) => financeApi.counterparties(cid, p as Query), { keepPrevious: true });
export const useCounterparty = (id: MaybeRefOrGetter<number>) => useResource("counterparty", () => ({ id: toValue(id) }), (cid, p) => financeApi.counterparty(cid, Number(p.id)));
export const useTransactions = (params: MaybeRefOrGetter<Query>) =>
  useResource("transactions", () => ({ ...toValue(params) }), (cid, p) => financeApi.transactions(cid, p as Query), { keepPrevious: true });
export const useTransaction = (id: MaybeRefOrGetter<number | null>) =>
  useResource("transaction", () => ({ id: toValue(id) }), (cid, p) => financeApi.transaction(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useTransfers = (params: MaybeRefOrGetter<Query>) => useResource("transfers", () => ({ ...toValue(params) }), (cid, p) => financeApi.transfers(cid, p as Query));
export const useDebts = (params: MaybeRefOrGetter<Query>) => useResource("debts", () => ({ ...toValue(params) }), (cid, p) => financeApi.debts(cid, p as Query), { keepPrevious: true });
export const useDebtSummary = () => useResource("debt-summary", {}, (cid) => financeApi.debtSummary(cid));
export const useDebt = (id: MaybeRefOrGetter<number | null>) => useResource("debt", () => ({ id: toValue(id) }), (cid, p) => financeApi.debt(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useRates = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("rates", {}, (cid) => financeApi.rates(cid), { enabled });
export const usePnl = (params: MaybeRefOrGetter<Query>) => useResource("pnl", () => ({ ...toValue(params) }), (cid, p) => financeApi.pnl(cid, p as Query), { keepPrevious: true });
export const useCashFlow = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("cash-flow", () => ({ ...toValue(params) }), (cid, p) => financeApi.cashFlow(cid, p as Query), { keepPrevious: true, enabled });
export const useBalances = (params: MaybeRefOrGetter<Query>) => useResource("balances", () => ({ ...toValue(params) }), (cid, p) => financeApi.balances(cid, p as Query), { keepPrevious: true });
export const useAging = (params: MaybeRefOrGetter<Query>) => useResource("aging", () => ({ ...toValue(params) }), (cid, p) => financeApi.aging(cid, p as Query), { keepPrevious: true });
export const useCategoryTrend = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean>) =>
  useResource("category-trend", () => ({ ...toValue(params) }), (cid, p) => financeApi.categoryTrend(cid, p as Query), { keepPrevious: true, enabled });
export const useSettings = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("settings", {}, (cid) => financeApi.settings(cid), { enabled });

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Refetch everything the module shows after a write (and the shell's pulse, for badges). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: financeKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}

/** A write that refreshes the module when it settles. `fn` gets the company id. */
export function useFinanceMutation<V, R>(fn: (cid: number, vars: V) => Promise<R>) {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: (vars: V) => fn(cid.value, vars), onSettled: refresh });
}

type TransactionPages = TransactionPage;

/** Recategorize an entry: the table shows the new category at once and rolls back on error. */
export function useCategorize() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ row, category }: { row: Transaction; category: { id: number; name: string; color: string; parent_name: string | null } }) =>
      financeApi.updateTransaction(cid.value, row.id, { category: category.id }),
    onMutate: async ({ row, category }) => {
      const prefix = financeKeys.of(cid.value, "transactions").slice(0, 3);
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<TransactionPages>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (!data) continue;
        client.setQueryData<TransactionPages>(key, {
          ...data,
          results: data.results.map((item) => (item.id === row.id ? { ...item, category: { ...category, kind: row.category?.kind ?? "expense" } } : item)),
        });
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

/** Move a category in the tree (drag): the new tree shows at once; the server's answer replaces it. */
export function useMoveCategory() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, parent, index }: { id: number; parent: number | null; index: number; next: CategoryNode[] }) => financeApi.moveCategory(cid.value, id, parent, index),
    onMutate: async ({ next }) => {
      const key = financeKeys.of(cid.value, "categories");
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<CategoryNode[]>(key);
      client.setQueryData(key, next);
      return { before };
    },
    onError: (_error, _vars, context) => {
      if (context?.before) client.setQueryData(financeKeys.of(cid.value, "categories"), context.before);
    },
    onSettled: refresh,
  });
}

/** Search counterparties for a ComboBox `source`. */
export async function searchCounterparties(cid: number, query: string, signal: AbortSignal) {
  const page = await financeApi.counterparties(cid, { q: query, page_size: 20, active: "true" }, signal);
  return page.results;
}
