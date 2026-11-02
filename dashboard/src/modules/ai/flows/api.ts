/**
 * The Flows endpoints (`/api/v1/owner/companies/{cid}/ai/flows/…`, briefs/v3-contract.md §4.7) and
 * the vue-query helpers the pages use. Keys start with `[companyId, "ai"]`, so the `ai` pulse key
 * refreshes everything here. A run is polled every second while it works and given up on after
 * 60 s; the runs list keeps its older pages.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { qk } from "@/api/keys";
import type { Page } from "@/api/types";

import { useCompanyId } from "../api";
import { mergeRuns, RUN_POLL_MS, runIsLive, runPollDecision } from "./lib";
import type { Flow, FlowCatalog, FlowCreate, FlowPatch, FlowRun, RunsPage } from "./types";

const MODULE = "ai";
const path = (cid: number, rest = "") => ownerPath(cid, `ai/${rest}`);

/** A list endpoint may answer with a page or a plain array. */
function rows<T>(body: Page<T> | T[]): T[] {
  return Array.isArray(body) ? body : body.results;
}

/** What the Flows pages read of `GET ai/models/` (contract §5): the company's model for flows. */
export interface ModelsLite {
  models: { id: string; name: string }[];
  features: { key: string; model: string; default: string }[];
}

export const flowsApi = {
  catalog: (cid: number, signal?: AbortSignal) => http.get<FlowCatalog>(path(cid, "flows/catalog/"), undefined, { signal }),
  list: (cid: number, signal?: AbortSignal) => http.get<Flow[] | Page<Flow>>(path(cid, "flows/"), undefined, { signal }).then(rows),
  get: (cid: number, id: number, signal?: AbortSignal) => http.get<Flow>(path(cid, `flows/${id}/`), undefined, { signal }),
  create: (cid: number, body: FlowCreate) => http.post<Flow>(path(cid, "flows/"), body),
  /** Field errors are shown on their fields by the page (it reads the 400's body), so no toast here. */
  patch: (cid: number, id: number, patch: FlowPatch) => http.patch<Flow>(path(cid, `flows/${id}/`), patch, { toast: false }),
  remove: (cid: number, id: number) => http.delete(path(cid, `flows/${id}/`)),
  test: (cid: number, id: number, subjectId: number | null = null) => http.post<{ run_id: number }>(path(cid, `flows/${id}/test/`), { subject_id: subjectId }),
  runs: (cid: number, id: number, params: { limit?: number; before?: number }, signal?: AbortSignal) => http.get<RunsPage>(path(cid, `flows/${id}/runs/`), params, { signal }),
  run: (cid: number, runId: number, signal?: AbortSignal) => http.get<FlowRun>(path(cid, `flow-runs/${runId}/`), undefined, { signal }),
  models: (cid: number, signal?: AbortSignal) => http.get<ModelsLite>(path(cid, "models/"), undefined, { signal }),
};

export const flowKeys = {
  catalog: (cid: number) => qk(cid, MODULE, "flows-catalog"),
  list: (cid: number) => qk(cid, MODULE, "flows"),
  flow: (cid: number, id: number) => qk(cid, MODULE, "flow", { id }),
  runs: (cid: number, id: number, limit: number) => qk(cid, MODULE, "flow-runs", { id, limit }),
  run: (cid: number, id: number) => qk(cid, MODULE, "flow-run", { id }),
  models: (cid: number) => qk(cid, MODULE, "models"),
};

// ─── Catalog and flows ──────────────────────────────────────────────────────

export function useFlowCatalog() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => flowKeys.catalog(cid.value)),
    queryFn: ({ signal }) => flowsApi.catalog(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 5 * 60_000,
  });
}

/** The list refreshes every 30 s while in view (counts, last runs), every 3 s while a run works. */
export function useFlows() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => flowKeys.list(cid.value)),
    queryFn: ({ signal }) => flowsApi.list(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 10_000,
    refetchInterval: (query) => ((query.state.data ?? []).some((flow) => runIsLive(flow.last_run?.status)) ? 3000 : 30_000),
  });
}

export function useFlow(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => flowKeys.flow(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => flowsApi.get(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 10_000,
  });
}

/** The company's model for flows by name ("Claude Haiku 5.5"), for "Company default · …"; null when unknown. */
export function useFlowsModelName(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  const query = useQuery({
    queryKey: computed(() => flowKeys.models(cid.value)),
    queryFn: ({ signal }) => flowsApi.models(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 5 * 60_000,
    retry: false,
  });
  return computed(() => {
    const body = query.data.value;
    const feature = body?.features?.find((item) => item.key === "flows");
    const id = feature?.model || feature?.default;
    return (id && body?.models?.find((model) => model.id === id)?.name) || null;
  });
}

/** After a flow changed: its own cache and its row in the list. */
function useFlowRefresh() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return (flow: Flow) => {
    client.setQueryData(flowKeys.flow(cid.value, flow.id), flow);
    client.setQueryData<Flow[]>(flowKeys.list(cid.value), (list) => (list ? (list.some((item) => item.id === flow.id) ? list.map((item) => (item.id === flow.id ? flow : item)) : [...list, flow]) : list));
  };
}

export function useCreateFlow() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useFlowRefresh();
  return useMutation({
    mutationFn: (body: FlowCreate) => flowsApi.create(cid.value, body),
    onSuccess: (flow) => {
      refresh(flow);
      void client.invalidateQueries({ queryKey: flowKeys.list(cid.value) });
    },
  });
}

/** Change a flow. The switch moves at once in the list and on the page, and goes back if refused. */
export function usePatchFlow() {
  const cid = useCompanyId();
  const client = useQueryClient();
  const refresh = useFlowRefresh();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: FlowPatch }) => flowsApi.patch(cid.value, id, patch),
    onMutate: async ({ id, patch }) => {
      if (patch.enabled === undefined) return {};
      const listKey = flowKeys.list(cid.value);
      const flowKey = flowKeys.flow(cid.value, id);
      await client.cancelQueries({ queryKey: listKey });
      const list = client.getQueryData<Flow[]>(listKey);
      const flow = client.getQueryData<Flow>(flowKey);
      if (list) client.setQueryData<Flow[]>(listKey, list.map((item) => (item.id === id ? { ...item, enabled: patch.enabled! } : item)));
      if (flow) client.setQueryData<Flow>(flowKey, { ...flow, enabled: patch.enabled });
      return { list, flow };
    },
    onError: (_error, { id }, context) => {
      if (context?.list) client.setQueryData(flowKeys.list(cid.value), context.list);
      if (context?.flow) client.setQueryData(flowKeys.flow(cid.value, id), context.flow);
    },
    onSuccess: (flow) => refresh(flow),
  });
}

export function useDeleteFlow() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => flowsApi.remove(cid.value, id),
    onSuccess: (_result, id) => {
      client.setQueryData<Flow[]>(flowKeys.list(cid.value), (list) => list?.filter((flow) => flow.id !== id));
      client.removeQueries({ queryKey: flowKeys.flow(cid.value, id) });
      void client.invalidateQueries({ queryKey: flowKeys.list(cid.value) });
    },
  });
}

/** Start a test run (202 `{"run_id"}`); the run is then watched with useFlowRun. */
export function useStartTest() {
  const cid = useCompanyId();
  return useMutation({
    mutationFn: ({ id, subjectId = null }: { id: number; subjectId?: number | null }) => flowsApi.test(cid.value, id, subjectId),
  });
}

// ─── Runs ───────────────────────────────────────────────────────────────────

/**
 * One run, polled every second while it is queued or running. After 60 s without an end it stops
 * and says so (`gaveUp`); `retry()` watches another 60 s.
 */
export function useFlowRun(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  const startedAt = ref(Date.now());
  const gaveUp = ref(false);
  watch(
    () => toValue(id),
    () => {
      startedAt.value = Date.now();
      gaveUp.value = false;
    },
  );
  const query = useQuery({
    queryKey: computed(() => flowKeys.run(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => flowsApi.run(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && !gaveUp.value),
    refetchInterval: (q) => {
      const decision = runPollDecision(q.state.data?.status, Date.now() - startedAt.value);
      if (decision === "give_up") gaveUp.value = true;
      return decision === "poll" ? RUN_POLL_MS : false;
    },
  });
  function retry(): void {
    startedAt.value = Date.now();
    gaveUp.value = false;
    void query.refetch();
  }
  return { ...query, gaveUp, retry };
}

/**
 * A flow's runs, newest first: the newest page (refreshed every 15 s while in view, every 2 s while
 * one of them works), older pages added below on demand, each run once.
 */
export function useFlowRuns(flowId: MaybeRefOrGetter<number | null>, options: { limit?: number } = {}) {
  const cid = useCompanyId();
  const limit = options.limit ?? 20;
  const head = useQuery({
    queryKey: computed(() => flowKeys.runs(cid.value, toValue(flowId) ?? 0, limit)),
    queryFn: ({ signal }) => flowsApi.runs(cid.value, toValue(flowId)!, { limit }, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(flowId)),
    refetchInterval: (query) => ((query.state.data?.results ?? []).some((run) => runIsLive(run.status)) ? 2000 : 15_000),
  });
  const items = shallowRef<FlowRun[]>([]);
  const cursor = ref<number | null>(null);
  const olderPages = ref(0);
  const loadingOlder = ref(false);
  const olderFailed = ref(false);

  watch([cid, () => toValue(flowId)], () => {
    items.value = [];
    cursor.value = null;
    olderPages.value = 0;
  });
  watch(
    () => head.data.value,
    (page) => {
      if (!page) return;
      items.value = mergeRuns(items.value, page.results);
      if (olderPages.value === 0) cursor.value = page.next_before;
    },
    { immediate: true },
  );

  async function loadOlder(): Promise<void> {
    const before = cursor.value;
    const id = toValue(flowId);
    if (before === null || !id || loadingOlder.value) return;
    loadingOlder.value = true;
    olderFailed.value = false;
    try {
      const page = await flowsApi.runs(cid.value, id, { limit, before });
      items.value = mergeRuns(items.value, page.results);
      cursor.value = page.next_before;
      olderPages.value += 1;
    } catch {
      olderFailed.value = true;
    } finally {
      loadingOlder.value = false;
    }
  }

  return {
    items,
    hasOlder: computed(() => cursor.value !== null),
    loadingOlder,
    olderFailed,
    loadOlder,
    isPending: head.isPending,
    isError: computed(() => head.isError.value && !items.value.length),
    error: head.error,
    refetch: () => head.refetch(),
  };
}
