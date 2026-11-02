/**
 * The payroll endpoints (plan §4.11) as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "payroll"]`, so the `payroll.*` pulse keys (`invalidates` in
 * index.ts) refresh every query of the module and switching company never shows another
 * company's pay. Every write refreshes the module's queries and the pulse (badges).
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import type {
  Adjustment,
  AdjustmentInput,
  Advance,
  AdvanceInput,
  BulkDecideInput,
  BulkDecideRow,
  Compensation,
  CompensationInput,
  Decision,
  ManualLineInput,
  MarkPaidInput,
  PayAccount,
  PayInput,
  PayRow,
  PayrollOverview,
  PayrollSettings,
  Payslip,
  PdfLink,
  RepayInput,
  Rule,
  RuleInput,
  RulePreview,
  Run,
} from "./types";

export const MODULE = "payroll";

const path = (cid: number, rest: string) => ownerPath(cid, `payroll/${rest}`);

/** Lists come paginated like every owner list; a few small ones may come as a plain array. */
export function rowsOf<T>(body: Page<T> | T[] | null | undefined): T[] {
  if (!body) return [];
  return Array.isArray(body) ? body : body.results;
}

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const payrollApi = {
  settings: (cid: number) => http.get<PayrollSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<PayrollSettings>) => http.patch<PayrollSettings>(path(cid, "settings/"), input),
  overview: (cid: number, months = 12) => http.get<PayrollOverview>(path(cid, "overview/"), { months }),

  /** A person's pay setups, newest first (or everyone's with `current=true`: today's only). */
  compensations: (cid: number, params: Query = {}, signal?: AbortSignal) =>
    http.get<Page<Compensation> | Compensation[]>(path(cid, "compensations/"), { page_size: 200, ...params }, { signal }),
  /** Everyone who can be paid, with today's setup and the next one planned. */
  payPeople: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Page<PayRow>>(path(cid, "compensations/people/"), { page_size: 200, ...params }, { signal }),
  createCompensation: (cid: number, input: CompensationInput) => http.post<Compensation>(path(cid, "compensations/"), input),
  updateCompensation: (cid: number, id: number, input: Partial<CompensationInput>) => http.patch<Compensation>(path(cid, `compensations/${id}/`), input),
  deleteCompensation: (cid: number, id: number) => http.delete(path(cid, `compensations/${id}/`)),

  adjustments: (cid: number, params: Query, signal?: AbortSignal) => http.get<Page<Adjustment>>(path(cid, "adjustments/"), params, { signal }),
  adjustment: (cid: number, id: number) => http.get<Adjustment>(path(cid, `adjustments/${id}/`)),
  createAdjustment: (cid: number, input: AdjustmentInput) => http.post<Adjustment>(path(cid, "adjustments/"), input),
  decideAdjustment: (cid: number, id: number, decision: Decision, reason = "") => http.post<Adjustment>(path(cid, `adjustments/${id}/${decision}/`), { reason }),
  voidAdjustment: (cid: number, id: number, reason: string) => http.post<Adjustment>(path(cid, `adjustments/${id}/void/`), { reason }),
  /** Answer a dispute; `voidIt` also takes the fine back. */
  answerDispute: (cid: number, id: number, answer: string, voidIt = false) => http.post<Adjustment>(path(cid, `adjustments/${id}/answer-dispute/`), { answer, void: voidIt }),
  bulkDecide: (cid: number, input: BulkDecideInput) => http.post<BulkDecideRow[]>(path(cid, "adjustments/bulk-decide/"), input),

  rules: (cid: number, signal?: AbortSignal) => http.get<Page<Rule> | Rule[]>(path(cid, "rules/"), { page_size: 200 }, { signal }),
  /** `quiet`: the builder shows a refusal itself (a toast would sit behind its panel). */
  createRule: (cid: number, input: RuleInput, quiet = false) => http.post<Rule>(path(cid, "rules/"), input, quiet ? { toast: false } : undefined),
  updateRule: (cid: number, id: number, input: Partial<RuleInput>, quiet = false) => http.patch<Rule>(path(cid, `rules/${id}/`), input, quiet ? { toast: false } : undefined),
  deleteRule: (cid: number, id: number) => http.delete(path(cid, `rules/${id}/`)),
  /** Dry run of a saved rule for a month ("2026-10-01"): who would get what. Nothing is written. */
  previewRule: (cid: number, id: number, period: string, signal?: AbortSignal) =>
    http.post<RulePreview>(path(cid, `rules/${id}/preview/`), { period }, { signal, toast: false }),

  advances: (cid: number, params: Query, signal?: AbortSignal) => http.get<Page<Advance>>(path(cid, "advances/"), params, { signal }),
  advance: (cid: number, id: number) => http.get<Advance>(path(cid, `advances/${id}/`)),
  createAdvance: (cid: number, input: AdvanceInput) => http.post<Advance>(path(cid, "advances/"), input),
  decideAdvance: (cid: number, id: number, decision: Decision, reason = "") => http.post<Advance>(path(cid, `advances/${id}/decide/`), { approve: decision === "approve", reason }),
  // Payouts say what went wrong inside their dialog (a toast would sit behind it): no toast.
  payAdvance: (cid: number, id: number, input: PayInput) => http.post<Advance>(path(cid, `advances/${id}/pay/`), input, { toast: false }),
  repayAdvance: (cid: number, id: number, input: RepayInput) => http.post<Advance>(path(cid, `advances/${id}/repay/`), input, { toast: false }),
  cancelAdvance: (cid: number, id: number, reason: string) => http.post<Advance>(path(cid, `advances/${id}/cancel/`), { reason }),

  runs: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Page<Run> | Run[]>(path(cid, "runs/"), { page_size: 100, ...params }, { signal }),
  run: (cid: number, id: number) => http.get<Run>(path(cid, `runs/${id}/`)),
  createRun: (cid: number, period: string) => http.post<Run>(path(cid, "runs/"), { period }),
  runAction: (cid: number, id: number, action: "calculate" | "finalize" | "reopen" | "cancel" | "publish", body: Record<string, unknown> = {}) =>
    http.post<Run>(path(cid, `runs/${id}/${action}/`), body),
  markPaid: (cid: number, id: number, input: MarkPaidInput) => http.post<Run>(path(cid, `runs/${id}/mark-paid/`), input, { toast: false }),
  payslips: (cid: number, runId: number, signal?: AbortSignal) => http.get<Page<Payslip> | Payslip[]>(path(cid, `runs/${runId}/payslips/`), { page_size: 200 }, { signal }),
  /**
   * One person's payslips of the last `months` runs. There is no list by person on the server
   * yet: the recent runs' payslip tables are read and the person's row kept.
   */
  memberPayslips: async (cid: number, member: number, months = 6, signal?: AbortSignal): Promise<Payslip[]> => {
    const runs = rowsOf(await payrollApi.runs(cid, { page_size: months }, signal)).filter((run) => run.status !== "cancelled");
    const tables = await Promise.all(runs.map((run) => payrollApi.payslips(cid, run.id, signal)));
    return tables.flatMap((table, index) => rowsOf(table).filter((slip) => slip.member.id === member).map((slip) => ({ ...slip, run: runs[index]!.id, run_status: runs[index]!.status })));
  },

  payslip: (cid: number, id: number) => http.get<Payslip>(path(cid, `payslips/${id}/`)),
  /** Replaces the payslip's manual lines (only while its run is a draft). */
  setManualLines: (cid: number, id: number, lines: ManualLineInput[]) => http.patch<Payslip>(path(cid, `payslips/${id}/`), { manual_lines: lines }),
  /** A short-lived signed link to the payslip's PDF, in the viewer's language. */
  payslipPdf: (cid: number, id: number) => http.get<PdfLink>(path(cid, `payslips/${id}/pdf/`), undefined, { toast: true }),

  /** Accounts money may be paid from: the finance options (a plain call; the finance module isn't imported). */
  accounts: (cid: number) => http.get<{ accounts: PayAccount[] }>(ownerPath(cid, "finance/options/")),
};

// ─── Keys ───────────────────────────────────────────────────────────────────

export const payrollKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

// ─── Queries ────────────────────────────────────────────────────────────────

function useResource<T>(
  resource: string,
  params: MaybeRefOrGetter<Record<string, unknown>>,
  fetcher: (cid: number, params: Record<string, unknown>, signal: AbortSignal) => Promise<T>,
  options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number } = {},
) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => payrollKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
  });
}

export const useSettings = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("settings", {}, (cid) => payrollApi.settings(cid), { enabled, staleTime: 60_000 });
export const useOverview = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("overview", {}, (cid) => payrollApi.overview(cid), { enabled });
export const useCompensations = (params: MaybeRefOrGetter<Query> = {}, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("compensations", () => ({ ...toValue(params) }), async (cid, p, signal) => rowsOf(await payrollApi.compensations(cid, p as Query, signal)), { enabled, keepPrevious: true });
export const usePayPeople = (params: MaybeRefOrGetter<Query> = {}) =>
  useResource("pay-people", () => ({ ...toValue(params) }), (cid, p, signal) => payrollApi.payPeople(cid, p as Query, signal), { keepPrevious: true });
export const useAdjustments = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("adjustments", () => ({ ...toValue(params) }), (cid, p, signal) => payrollApi.adjustments(cid, p as Query, signal), { enabled, keepPrevious: true });
export const useAdjustment = (id: MaybeRefOrGetter<number | null>) =>
  useResource("adjustment", () => ({ id: toValue(id) }), (cid, p) => payrollApi.adjustment(cid, Number(p.id)), { enabled: () => !!toValue(id), staleTime: 10_000 });
export const useRules = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("rules", {}, async (cid, _p, signal) => rowsOf(await payrollApi.rules(cid, signal)), { enabled });
export const useAdvances = (params: MaybeRefOrGetter<Query>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("advances", () => ({ ...toValue(params) }), (cid, p, signal) => payrollApi.advances(cid, p as Query, signal), { enabled, keepPrevious: true });
export const useAdvance = (id: MaybeRefOrGetter<number | null>) =>
  useResource("advance", () => ({ id: toValue(id) }), (cid, p) => payrollApi.advance(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useRuns = (params: MaybeRefOrGetter<Query> = {}, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("runs", () => ({ ...toValue(params) }), async (cid, p, signal) => rowsOf(await payrollApi.runs(cid, p as Query, signal)), { enabled, keepPrevious: true });
export const useRun = (id: MaybeRefOrGetter<number | null>) => useResource("run", () => ({ id: toValue(id) }), (cid, p) => payrollApi.run(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const usePayslips = (runId: MaybeRefOrGetter<number | null>) =>
  useResource("payslips", () => ({ run: toValue(runId) }), async (cid, p, signal) => rowsOf(await payrollApi.payslips(cid, Number(p.run), signal)), { enabled: () => !!toValue(runId) });
export const useMemberPayslips = (member: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("member-payslips", () => ({ member: toValue(member) }), (cid, p, signal) => payrollApi.memberPayslips(cid, Number(p.member), 6, signal), { enabled });
export const usePayslip = (id: MaybeRefOrGetter<number | null>) => useResource("payslip", () => ({ id: toValue(id) }), (cid, p) => payrollApi.payslip(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useAccounts = (enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("accounts", {}, async (cid) => (await payrollApi.accounts(cid)).accounts ?? [], { enabled, staleTime: 60_000 });

// ─── After a write ──────────────────────────────────────────────────────────

/** Refetch everything the module shows after a write (and the shell's pulse, for badges). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: payrollKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}

/**
 * Opens a payslip's PDF from its short-lived signed link: Telegram's own download inside
 * Telegram (the link needs no sign-in, so Telegram can fetch it), a new tab elsewhere (the server
 * serves PDFs inline).
 */
export async function openPayslipPdf(cid: number, id: number, fallbackName: string): Promise<void> {
  const link = await payrollApi.payslipPdf(cid, id);
  const absolute = new URL(link.url, window.location.origin).href;
  const webApp = window.Telegram?.WebApp;
  if (webApp?.initData && webApp.downloadFile && webApp.isVersionAtLeast("8.0")) {
    webApp.downloadFile({ url: absolute, file_name: link.name || fallbackName });
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = absolute;
  anchor.target = "_blank";
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
