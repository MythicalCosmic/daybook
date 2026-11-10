/**
 * Egasi paneli's endpoints (apps.insights): the whole cockpit in one call (`cockpit/`), the
 * insights' own actions, the insight settings and "Check now". A decision's Approve and Reject
 * call the endpoint its module gave the item (`runQueueAction`), so each app's own service,
 * permission check and audit settle it. Types are written by hand next to the functions.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed } from "vue";

import { http, ownerPath } from "@/api/http";
import { keys as shellKeys, moduleKey, qk } from "@/api/keys";
import { runQueueAction } from "@/api/shell";
import type { Money, QueueAction, QueueItem } from "@/api/types";
import { useCompanyId } from "@/stores/company";

export const MODULE = "cockpit";

// ─── Types ──────────────────────────────────────────────────────────────────

export interface CockpitCost {
  key: string;
  name: string;
  color?: string;
  amount: Money;
  previous?: Money | null;
}

export interface PeriodPrevious {
  revenue: Money;
  gross: Money;
  gross_margin: string | null;
  expense: Money;
  profit: Money;
  margin: string | null;
}

export interface PeriodFigures {
  revenue: Money;
  /** Medicines and goods bought, booked when a goods receipt is posted. */
  goods: Money;
  gross: Money;
  gross_margin: string | null;
  expense: Money;
  profit: Money;
  margin: string | null;
  costs: CockpitCost[];
  previous: PeriodPrevious | null;
  /** This month only: monthly cost groups last month had and this month has none of yet. */
  missing?: Array<{ key: string; name: string; last_month: Money }>;
}

export type PeriodKey = "month" | "last_month";
export type BranchState = "green" | "amber" | "red";

export interface Figures {
  month: PeriodFigures;
  last_month: PeriodFigures;
  trend: Array<{ month: string; profit: Money }>;
}

export interface CockpitBranch extends Figures {
  id: number;
  name: string;
  code: string;
  states: Record<PeriodKey, { state: BranchState; reasons: string[] }>;
}

export interface PeriodRange {
  from: string;
  to: string;
  previous_from: string;
  previous_to: string;
}

export interface Unassigned {
  revenue: Money;
  goods: Money;
  gross: Money;
  expense: Money;
  profit: Money;
  costs: CockpitCost[];
}

export interface CockpitMoney {
  periods: Record<PeriodKey, PeriodRange>;
  total: Figures;
  branches: CockpitBranch[];
  unassigned: Record<PeriodKey, Unassigned> | null;
}

export interface LowCause {
  title: string;
  kind: string;
  date: string;
  amount: Money;
  overdue: boolean;
}

export interface CockpitCash {
  currency: string;
  now: Money;
  buffer: Money;
  buffer_source: "setting" | "fixed_costs";
  daily_spend: Money;
  runway: { days: number | null; basis: "spending" | "forecast"; below_zero_on: string | null; horizon: number };
  low: { date: string; balance: Money; short_by: Money; under_buffer_by: Money; causes: LowCause[] };
  end: Money;
  points: Array<{ date: string; balance: Money }>;
}

export interface Decision extends QueueItem {
  source: string;
  group: string;
}

export interface DecisionSource {
  key: string;
  group: string;
  label: string;
  count: number;
}

export interface CockpitDecisions {
  total: number;
  sources: DecisionSource[];
  items: Decision[];
}

export type InsightSeverity = "info" | "warning" | "critical";
export type InsightStatus = "open" | "acknowledged" | "dismissed" | "resolved";

export interface Insight {
  id: number;
  kind: string;
  domain: string;
  severity: InsightSeverity;
  status: InsightStatus;
  branch: { id: number; name: string } | null;
  subject: { type: string; id: number | null; label: string } | null;
  title: string;
  explanation: string;
  suggested_action: string;
  metrics: Record<string, unknown> & { value?: string; baseline?: string; unit?: string; series?: Array<string | null> };
  window: { from: string | null; to: string | null };
  detected_at: string;
  last_seen_at: string;
  acknowledged_at: string | null;
  task: { id: number; title: string; status: string } | null;
}

export interface CockpitInsights {
  live: number;
  open: number;
  critical: number;
  items: Insight[];
}

export interface Cockpit {
  today: string;
  currency: string;
  generated_at: string;
  can: { money: boolean; insights: boolean; settings: boolean };
  money?: CockpitMoney;
  cash?: CockpitCash;
  decisions: CockpitDecisions;
  insights: CockpitInsights;
}

export interface InsightSettings {
  disabled_kinds: string[];
  sensitivity: "low" | "normal" | "high";
  quiet_from: string;
  quiet_to: string;
  notify_critical_via_bot: boolean;
  expense_alert_min_amount: Money;
  kinds: Array<{ kind: string; label: string; domain: string; available: boolean }>;
  last_run_at: string | null;
}

export type InsightAction = "acknowledge" | "dismiss" | "resolve";

// ─── Endpoints ──────────────────────────────────────────────────────────────

export function fetchCockpit(companyId: number, signal?: AbortSignal): Promise<Cockpit> {
  return http.get<Cockpit>(ownerPath(companyId, "cockpit/"), undefined, { signal });
}

export function actOnInsight(companyId: number, id: number, action: InsightAction, reason?: string): Promise<Insight> {
  return http.post<Insight>(ownerPath(companyId, `insights/${id}/${action}/`), action === "dismiss" ? { reason: reason ?? "" } : {});
}

export function makeTask(companyId: number, id: number, body: { title?: string; due_on?: string | null; assignee_id?: number | null } = {}): Promise<{ insight: Insight; task: { id: number; title: string; status: string } }> {
  return http.post(ownerPath(companyId, `insights/${id}/make-task/`), body);
}

export function checkNow(companyId: number): Promise<Record<string, number>> {
  return http.post<Record<string, number>>(ownerPath(companyId, "insights/check/"));
}

export function fetchSettings(companyId: number, signal?: AbortSignal): Promise<InsightSettings> {
  return http.get<InsightSettings>(ownerPath(companyId, "insights/settings/"), undefined, { signal });
}

export function saveSettings(companyId: number, changes: Partial<InsightSettings>): Promise<InsightSettings> {
  return http.patch<InsightSettings>(ownerPath(companyId, "insights/settings/"), changes);
}

export { runQueueAction };

// ─── Keys and queries ───────────────────────────────────────────────────────

export const cockpitKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  cockpit: (companyId: number) => qk(companyId, MODULE, "cockpit"),
  settings: (companyId: number) => qk(companyId, MODULE, "settings"),
};

/** The whole page; refreshed by the pulse (index.ts `invalidates`) and every five minutes. */
export function useCockpit() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => cockpitKeys.cockpit(companyId.value)),
    queryFn: ({ signal }) => fetchCockpit(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
    staleTime: 30_000,
    refetchInterval: 5 * 60_000,
  });
}

export function useInsightSettings() {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => cockpitKeys.settings(companyId.value)),
    queryFn: ({ signal }) => fetchSettings(companyId.value, signal),
    enabled: computed(() => companyId.value > 0),
  });
}

/** The cockpit without one decided item. */
export function withoutDecision(data: Cockpit, item: Pick<Decision, "kind" | "id">): Cockpit {
  const items = data.decisions.items.filter((row) => !(row.kind === item.kind && String(row.id) === String(item.id)));
  if (items.length === data.decisions.items.length) return data;
  return {
    ...data,
    decisions: {
      total: Math.max(0, data.decisions.total - 1),
      sources: data.decisions.sources.map((source) => (source.key === item.kind ? { ...source, count: Math.max(0, source.count - 1) } : source)),
      items,
    },
  };
}

/** The cockpit with one insight changed (or gone, when it is no longer live). */
export function withInsight(data: Cockpit, insight: Insight): Cockpit {
  const live = insight.status === "open" || insight.status === "acknowledged";
  const before = data.insights.items.find((row) => row.id === insight.id);
  const items = live ? data.insights.items.map((row) => (row.id === insight.id ? insight : row)) : data.insights.items.filter((row) => row.id !== insight.id);
  const wasOpen = before?.status === "open";
  return {
    ...data,
    insights: {
      live: before && !live ? Math.max(0, data.insights.live - 1) : data.insights.live,
      open: wasOpen && insight.status !== "open" ? Math.max(0, data.insights.open - 1) : data.insights.open,
      critical: before && !live && before.severity === "critical" ? Math.max(0, data.insights.critical - 1) : data.insights.critical,
      items,
    },
  };
}

function useRefresh() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: cockpitKeys.all(companyId.value) });
    void client.invalidateQueries({ queryKey: [companyId.value, "shell", "queue"] });
    void client.invalidateQueries({ queryKey: [companyId.value, "inbox"] });
    void client.invalidateQueries({ queryKey: shellKeys.pulse(companyId.value) });
  };
}

/** Approve or reject a decision: it leaves the list at once and comes back if the server refuses. */
export function useDecision() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ action, reason }: { item: Decision; action: QueueAction; reason?: string }) => runQueueAction(companyId.value, action, reason),
    onMutate: async ({ item }) => {
      const key = cockpitKeys.cockpit(companyId.value);
      await client.cancelQueries({ queryKey: key });
      const snapshot = client.getQueryData<Cockpit>(key);
      if (snapshot) client.setQueryData(key, withoutDecision(snapshot, item));
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      if (context?.snapshot) client.setQueryData(cockpitKeys.cockpit(companyId.value), context.snapshot);
    },
    onSettled: refresh,
  });
}

/** Seen, dismiss or resolve an insight, shown at once. */
export function useInsightAction() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ insight, action, reason }: { insight: Insight; action: InsightAction; reason?: string }) => actOnInsight(companyId.value, insight.id, action, reason),
    onSuccess: (insight) => {
      const key = cockpitKeys.cockpit(companyId.value);
      const data = client.getQueryData<Cockpit>(key);
      if (data) client.setQueryData(key, withInsight(data, insight));
    },
    onSettled: refresh,
  });
}

export function useMakeTask() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ insight, body }: { insight: Insight; body?: { title?: string; due_on?: string | null } }) => makeTask(companyId.value, insight.id, body),
    onSuccess: (result) => {
      const key = cockpitKeys.cockpit(companyId.value);
      const data = client.getQueryData<Cockpit>(key);
      if (data) client.setQueryData(key, withInsight(data, result.insight));
    },
    onSettled: refresh,
  });
}

export function useCheckNow() {
  const companyId = useCompanyId();
  const refresh = useRefresh();
  return useMutation({ mutationFn: () => checkNow(companyId.value), onSuccess: refresh });
}

export function useSaveSettings() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return useMutation({
    mutationFn: (changes: Partial<InsightSettings>) => saveSettings(companyId.value, changes),
    onSuccess: (data) => {
      client.setQueryData(cockpitKeys.settings(companyId.value), data);
      void client.invalidateQueries({ queryKey: cockpitKeys.cockpit(companyId.value) });
    },
  });
}
