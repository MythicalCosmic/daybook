/**
 * The sales endpoints (plan §4.8) as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "sales"]`, so the `sales.*` pulse keys (index.ts `invalidates`)
 * refresh every sales query, and switching company never shows another company's numbers.
 * Writes refresh what they change; verify and handover answers update the cache at once.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type {
  CashierScore,
  CashPositions,
  DailyRow,
  Entry,
  EntryInput,
  GroupBy,
  Movement,
  MovementInput,
  PaymentLineInput,
  PaymentMethod,
  PaymentMethodInput,
  Register,
  RegisterInput,
  SalesOptions,
  SalesSettings,
  SalesSummary,
  ShiftDetail,
  ShiftRow,
  BranchTodaySales,
  TargetsView,
} from "./types";

export const MODULE = "sales";

const path = (companyId: number, rest: string) => ownerPath(companyId, `sales/${rest}`);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const salesApi = {
  settings: (cid: number) => http.get<SalesSettings>(path(cid, "settings/")),
  saveSettings: (cid: number, input: Partial<SalesSettings>) => http.patch<SalesSettings>(path(cid, "settings/"), input),

  methods: (cid: number) => http.get<PaymentMethod[]>(path(cid, "payment-methods/")),
  createMethod: (cid: number, input: PaymentMethodInput) => http.post<PaymentMethod>(path(cid, "payment-methods/"), input),
  updateMethod: (cid: number, id: number, input: PaymentMethodInput) => http.patch<PaymentMethod>(path(cid, `payment-methods/${id}/`), input),
  reorderMethods: (cid: number, ids: number[]) => http.post<PaymentMethod[]>(path(cid, "payment-methods/reorder/"), { ids }),

  registers: (cid: number) => http.get<Register[]>(path(cid, "registers/")),
  createRegister: (cid: number, input: RegisterInput) => http.post<Register>(path(cid, "registers/"), input),
  updateRegister: (cid: number, id: number, input: RegisterInput) => http.patch<Register>(path(cid, `registers/${id}/`), input),

  options: (cid: number) => http.get<SalesOptions>(path(cid, "options/")),
  today: (cid: number) => http.get<{ branches: BranchTodaySales[] }>(path(cid, "today/")),
  summary: (cid: number, params: Query) => http.get<SalesSummary>(path(cid, "summary/"), params),
  daily: (cid: number, params: Query) => http.get<Page<DailyRow>>(path(cid, "daily/"), params),
  cashiers: (cid: number, params: Query) => http.get<{ range: { from: string; to: string }; results: CashierScore[] }>(path(cid, "cashiers/"), params),

  shifts: (cid: number, params: Query, signal?: AbortSignal) => http.get<Page<ShiftRow>>(path(cid, "shifts/"), params, { signal }),
  shift: (cid: number, id: number) => http.get<ShiftDetail>(path(cid, `shifts/${id}/`)),
  verify: (cid: number, id: number, input: { recount_cash?: string | null; note?: string }) => http.post<ShiftDetail>(path(cid, `shifts/${id}/verify/`), input),
  dispute: (cid: number, id: number, reason: string) => http.post<ShiftDetail>(path(cid, `shifts/${id}/dispute/`), { reason }),
  forceClose: (cid: number, id: number, input: { reason: string; counted_cash?: string | null }) =>
    http.post<ShiftDetail>(path(cid, `shifts/${id}/force-close/`), input),
  correct: (cid: number, id: number, input: { payments: PaymentLineInput[]; reason: string; counted_cash?: string | null }) =>
    http.patch<ShiftDetail>(path(cid, `shifts/${id}/payments/`), input),

  positions: (cid: number) => http.get<CashPositions>(path(cid, "cash/positions/")),
  movements: (cid: number, params: Query) => http.get<Page<Movement>>(path(cid, "cash-movements/"), params),
  recordMovement: (cid: number, input: MovementInput) => http.post<Movement>(path(cid, "cash-movements/"), input),
  voidMovement: (cid: number, id: number, reason: string) => http.post<Movement>(path(cid, `cash-movements/${id}/void/`), { reason }),
  confirmHandover: (cid: number, id: number) => http.post<Movement>(path(cid, `handovers/${id}/confirm/`)),
  declineHandover: (cid: number, id: number, reason: string) => http.post<Movement>(path(cid, `handovers/${id}/decline/`), { reason }),

  entries: (cid: number, params: Query) => http.get<Page<Entry>>(path(cid, "entries/"), params),
  createEntry: (cid: number, input: EntryInput) => http.post<Entry>(path(cid, "entries/"), input),
  voidEntry: (cid: number, id: number, reason: string) => http.post<Entry>(path(cid, `entries/${id}/void/`), { reason }),

  targets: (cid: number, month: string) => http.get<TargetsView>(path(cid, "targets/"), { month }),
  setTarget: (cid: number, input: { month: string; amount: string; branch_id?: number | null; member_id?: number | null }) =>
    http.post<{ id: number }>(path(cid, "targets/"), input),
  updateTarget: (cid: number, id: number, amount: string) => http.patch<{ id: number }>(path(cid, `targets/${id}/`), { amount }),
  deleteTarget: (cid: number, id: number) => http.delete(path(cid, `targets/${id}/`)),
};

// ─── Keys and queries ────────────────────────────────────────────────────────

export const salesKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  resource: (cid: number, name: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, name, params),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

function useResource<T>(name: string, params: MaybeRefOrGetter<Record<string, unknown>>, fetcher: (cid: number, params: Record<string, unknown>) => Promise<T>, options: { keep?: boolean; enabled?: MaybeRefOrGetter<boolean>; staleTime?: number } = {}) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => salesKeys.resource(cid.value, name, toValue(params))),
    queryFn: () => fetcher(cid.value, toValue(params)),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keep ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 15_000,
  });
}

export const useOptions = () => useResource("options", {}, (cid) => salesApi.options(cid), { staleTime: 60_000 });
export const useSettings = () => useResource("settings", {}, (cid) => salesApi.settings(cid), { staleTime: 60_000 });
export const useMethods = () => useResource("methods", {}, (cid) => salesApi.methods(cid));
export const useRegisters = () => useResource("registers", {}, (cid) => salesApi.registers(cid));
export const useToday = () => useResource("today", {}, (cid) => salesApi.today(cid));
export const usePositions = () => useResource("positions", {}, (cid) => salesApi.positions(cid));

export function useSummary(params: MaybeRefOrGetter<Record<string, unknown>>, groupBy: MaybeRefOrGetter<GroupBy>) {
  return useResource("summary", () => ({ ...toValue(params), group_by: toValue(groupBy) }), (cid, p) => salesApi.summary(cid, p as Query), { keep: true });
}

export function useCashiers(params: MaybeRefOrGetter<Record<string, unknown>>) {
  return useResource("cashiers", params, (cid, p) => salesApi.cashiers(cid, p as Query), { keep: true });
}

export function useShifts(params: MaybeRefOrGetter<Record<string, unknown>>) {
  return useResource("shifts", params, (cid, p) => salesApi.shifts(cid, p as Query), { keep: true });
}

export function useShift(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => salesKeys.resource(cid.value, "shift", { id: toValue(id) })),
    queryFn: () => salesApi.shift(cid.value, toValue(id)!),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 10_000,
  });
}

export function useMovements(params: MaybeRefOrGetter<Record<string, unknown>>) {
  return useResource("movements", params, (cid, p) => salesApi.movements(cid, p as Query), { keep: true });
}

export function useEntries(params: MaybeRefOrGetter<Record<string, unknown>>) {
  return useResource("entries", params, (cid, p) => salesApi.entries(cid, p as Query), { keep: true });
}

export function useTargets(month: MaybeRefOrGetter<string>) {
  return useResource("targets", () => ({ month: toValue(month) }), (cid, p) => salesApi.targets(cid, String(p.month)), { keep: true });
}

// ─── Mutations ───────────────────────────────────────────────────────────────

/** Refreshes every sales query (and the shell's queue and pulse, which sales feeds). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: salesKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "queue"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}

/** A mutation that refreshes the sales queries when it settles. */
export function useSalesMutation<Vars, Result>(fn: (cid: number, vars: Vars) => Promise<Result>, options: { onSuccess?: (result: Result, vars: Vars) => void } = {}) {
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (vars: Vars) => fn(cid.value, vars),
    onSuccess: options.onSuccess,
    onSettled: refresh,
  });
}

/** Writes a shift's new state into the drawer's cache at once (verify, dispute, corrections). */
export function useShiftWrite<Vars>(fn: (cid: number, vars: Vars) => Promise<ShiftDetail>) {
  const client = useQueryClient();
  const cid = useCompanyId();
  return useSalesMutation(fn, {
    onSuccess: (shift) => client.setQueryData(salesKeys.resource(cid.value, "shift", { id: shift.id }), shift),
  });
}

/** Answers a handover in place: it leaves the "in transit" list before the server answers. */
export function useHandoverAnswer() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, answer, reason }: { id: number; answer: "confirm" | "decline"; reason?: string }) =>
      answer === "confirm" ? salesApi.confirmHandover(cid.value, id) : salesApi.declineHandover(cid.value, id, reason ?? ""),
    onMutate: async ({ id }) => {
      const key = salesKeys.resource(cid.value, "positions");
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<CashPositions>(key);
      if (previous) {
        client.setQueryData<CashPositions>(key, { ...previous, in_transit: previous.in_transit.filter((row) => row.id !== id) });
      }
      return { previous, key };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(context.key, context.previous);
    },
    onSettled: refresh,
  });
}
