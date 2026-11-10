/**
 * Business goals (v11, `goals/`): the goals with their live progress and weekly series, the
 * metrics a goal can measure, a preview while the dialog is filled in, and the writes. Keys start
 * with `[companyId, "goals"]`; the module's `invalidates` refreshes them on the `goals` pulse.
 * Types are hand-written next to the calls (the lead regenerates the OpenAPI ones).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

export const MODULE = "goals";

export type MetricKey = "revenue" | "gross_profit" | "net_profit" | "margin" | "branches" | "headcount" | "turnover" | "average_check" | "late_arrivals" | "training";
export type Unit = "money" | "percent" | "count";
export type GoalStatus = "active" | "achieved" | "missed" | "archived";
export type GoalState = "not_started" | "on_track" | "at_risk" | "off_track" | "achieved" | "missed" | "no_data";
export type Tab = "active" | "done" | "archived";

export interface GoalPoint {
  on: string;
  value: string | null;
  forecast: string | null;
  state: GoalState;
}

export interface Goal {
  id: number;
  title: string;
  metric: MetricKey;
  unit: Unit;
  better: "up" | "down";
  kind: "sum" | "rate" | "ratio" | "level";
  target: string;
  starts_on: string;
  ends_on: string;
  branch: { id: number; name: string } | null;
  owner: { id: number; name: string } | null;
  note: string;
  status: GoalStatus;
  state: GoalState;
  value: string | null;
  forecast: string | null;
  baseline: string | null;
  progress: string | null;
  days_left: number;
  time_share: string;
  available: boolean;
  series: GoalPoint[];
  can_edit: boolean;
}

export interface GoalList {
  today: string;
  currency: string;
  can_manage: boolean;
  goals: Goal[];
  counts: Record<Tab, number>;
}

export interface MetricOption {
  key: MetricKey;
  label: string;
  hint: string;
  unit: Unit;
  better: "up" | "down";
  kind: "sum" | "rate" | "ratio" | "level";
  branchable: boolean;
  available: boolean;
  feature: string | null;
}

export interface Metrics {
  metrics: MetricOption[];
  branches: Array<{ id: number; name: string }>;
  people: Array<{ id: number; name: string }>;
  company_wide: boolean;
}

export interface Preview {
  metric: MetricKey;
  state: GoalState | null;
  value: string | null;
  forecast: string | null;
  baseline: string | null;
  progress: string | null;
  days_left: number;
}

export interface GoalInput {
  title: string;
  metric: MetricKey;
  target: string;
  starts_on: string;
  ends_on: string;
  branch?: number | null;
  owner?: number | null;
  note?: string;
}

const path = (cid: number, rest = "") => ownerPath(cid, `goals/${rest}`);

export const goalsApi = {
  list: (cid: number, status: Tab) => http.get<GoalList>(path(cid), { status }),
  goal: (cid: number, id: number) => http.get<Goal>(path(cid, `${id}/`)),
  create: (cid: number, input: GoalInput) => http.post<Goal>(path(cid), input),
  update: (cid: number, id: number, input: Partial<Omit<GoalInput, "metric" | "branch">>) => http.patch<Goal>(path(cid, `${id}/`), input),
  remove: (cid: number, id: number) => http.delete(path(cid, `${id}/`)),
  archive: (cid: number, id: number) => http.post<Goal>(path(cid, `${id}/archive/`)),
  restore: (cid: number, id: number) => http.post<Goal>(path(cid, `${id}/restore/`)),
  metrics: (cid: number) => http.get<Metrics>(path(cid, "metrics/")),
  preview: (cid: number, params: { metric: string; starts_on: string; ends_on: string; branch?: number | null; target?: string | null }) => {
    const query: Record<string, string> = { metric: params.metric, starts_on: params.starts_on, ends_on: params.ends_on };
    if (params.branch) query.branch = String(params.branch);
    if (params.target) query.target = params.target;
    return http.get<Preview>(path(cid, "preview/"), query);
  },
};

export const goalsKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

export function useGoals(tab: MaybeRefOrGetter<Tab>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => goalsKeys.of(cid.value, "list", { tab: toValue(tab) })),
    queryFn: () => goalsApi.list(cid.value, toValue(tab)),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
  });
}

export function useGoal(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => goalsKeys.of(cid.value, "goal", { id: toValue(id) })),
    queryFn: () => goalsApi.goal(cid.value, Number(toValue(id))),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 30_000,
  });
}

export function useMetrics(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => goalsKeys.of(cid.value, "metrics")),
    queryFn: () => goalsApi.metrics(cid.value),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

export function usePreview(params: MaybeRefOrGetter<{ metric: string; starts_on: string; ends_on: string; branch?: number | null; target?: string | null } | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => goalsKeys.of(cid.value, "preview", { ...(toValue(params) ?? {}) })),
    queryFn: () => goalsApi.preview(cid.value, toValue(params)!),
    enabled: computed(() => cid.value > 0 && !!toValue(params)),
    staleTime: 30_000,
  });
}

/** A write, then every goals query (and the shell's pulse) refreshes. */
export function useGoalWrite<I, O>(call: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: I) => call(cid.value, input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: goalsKeys.all(cid.value) });
      void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
    },
  });
}

// ─── Pure helpers (tested) ──────────────────────────────────────────────────

export const STATE_TONES: Record<GoalState, "success" | "warning" | "danger" | "neutral" | "info" | "primary"> = {
  not_started: "neutral",
  on_track: "success",
  at_risk: "warning",
  off_track: "danger",
  achieved: "primary",
  missed: "neutral",
  no_data: "neutral",
};

/** The ring's color: the state's, a reached target green. */
export function ringTone(goal: Pick<Goal, "state">): "success" | "warning" | "danger" | "primary" | "info" {
  if (goal.state === "on_track" || goal.state === "achieved") return goal.state === "achieved" ? "primary" : "success";
  if (goal.state === "at_risk") return "warning";
  if (goal.state === "off_track" || goal.state === "missed") return "danger";
  return "info";
}

export type PeriodPreset = "month" | "quarter" | "half" | "year" | "custom";

/** The period a preset means around `today` (company-local days, both ends included). */
export function presetPeriod(preset: Exclude<PeriodPreset, "custom">, today: string): { starts_on: string; ends_on: string } {
  const [year, month] = today.split("-").map(Number) as [number, number];
  const pad = (n: number) => String(n).padStart(2, "0");
  const last = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();
  if (preset === "month") return { starts_on: `${year}-${pad(month)}-01`, ends_on: `${year}-${pad(month)}-${pad(last(year, month))}` };
  if (preset === "quarter") {
    const first = 3 * Math.floor((month - 1) / 3) + 1;
    return { starts_on: `${year}-${pad(first)}-01`, ends_on: `${year}-${pad(first + 2)}-${pad(last(year, first + 2))}` };
  }
  if (preset === "half") {
    const first = month <= 6 ? 1 : 7;
    return { starts_on: `${year}-${pad(first)}-01`, ends_on: `${year}-${pad(first + 5)}-${pad(last(year, first + 5))}` };
  }
  return { starts_on: `${year}-01-01`, ends_on: `${year}-12-31` };
}

/** Counts of the active goals per state, worst first, for the summary chips. */
export function stateCounts(goals: Goal[]): Array<{ state: GoalState; count: number }> {
  const order: GoalState[] = ["off_track", "at_risk", "on_track", "not_started", "no_data", "achieved", "missed"];
  return order.map((state) => ({ state, count: goals.filter((goal) => goal.state === state).length })).filter((row) => row.count > 0);
}

/** Worst first, then the soonest due: what needs the owner comes on top. */
export function sortGoals(goals: Goal[]): Goal[] {
  const rank: Record<GoalState, number> = { off_track: 0, at_risk: 1, on_track: 2, not_started: 3, no_data: 4, achieved: 5, missed: 6 };
  return [...goals].sort((a, b) => rank[a.state] - rank[b.state] || a.ends_on.localeCompare(b.ends_on) || a.id - b.id);
}
