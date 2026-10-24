/**
 * The tasks endpoints (plan §4.5) as typed functions and the vue-query helpers the pages use.
 * Keys start with `[companyId, "tasks"]`, so the `tasks` pulse keys refresh everything here.
 * Writes update the cache at once where an undo is obvious and roll back when the server refuses.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type {
  BlockerAction,
  BoardColumn,
  BoardColumnId,
  BulkInput,
  BulkResponse,
  ProofWall,
  QuickAddParse,
  TaskCalendar,
  TaskComment,
  TaskCreateInput,
  TaskDetail,
  TaskReview,
  TaskFilterParams,
  TaskOptions,
  TaskRow,
  TaskSummary,
  TaskTimelineEntry,
  TaskUpdateInput,
} from "./types";

export const MODULE = "tasks";

type Params = Record<string, string | number | boolean | string[] | undefined | null>;

// ─── Endpoints ──────────────────────────────────────────────────────────────

export const tasksApi = {
  list: (cid: number, params: Params, signal?: AbortSignal) => http.get<Page<TaskRow>>(ownerPath(cid, "tasks/"), params, { signal }),
  board: (cid: number, params: Params, signal?: AbortSignal) => http.get<{ columns: BoardColumn[] }>(ownerPath(cid, "tasks/board/"), params, { signal }),
  calendar: (cid: number, params: Params, signal?: AbortSignal) => http.get<TaskCalendar>(ownerPath(cid, "tasks/calendar/"), params, { signal }),
  summary: (cid: number, params: Params = {}, signal?: AbortSignal) => http.get<TaskSummary>(ownerPath(cid, "tasks/summary/"), params, { signal }),
  reviews: (cid: number, params: Params = {}, signal?: AbortSignal) => http.get<Page<TaskReview>>(ownerPath(cid, "tasks/reviews/"), params, { signal }),
  options: (cid: number, signal?: AbortSignal) => http.get<TaskOptions>(ownerPath(cid, "tasks/options/"), undefined, { signal }),
  detail: (cid: number, id: number, signal?: AbortSignal) => http.get<TaskDetail>(ownerPath(cid, `tasks/${id}/`), undefined, { signal }),
  timeline: (cid: number, id: number, signal?: AbortSignal) => http.get<TaskTimelineEntry[]>(ownerPath(cid, `tasks/${id}/timeline/`), undefined, { signal }),
  proofs: (cid: number, params: Params, signal?: AbortSignal) => http.get<ProofWall>(ownerPath(cid, "proofs/"), params, { signal }),
  create: (cid: number, input: TaskCreateInput) => http.post<{ created: number; ids: number[] }>(ownerPath(cid, "tasks/"), input),
  update: (cid: number, id: number, input: TaskUpdateInput) => http.patch<TaskDetail>(ownerPath(cid, `tasks/${id}/`), input),
  confirm: (cid: number, id: number) => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/confirm/`)),
  sendBack: (cid: number, id: number, reason: string) => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/return/`), { reason }),
  cancel: (cid: number, id: number) => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/cancel/`)),
  reassign: (cid: number, id: number, assigneeId: number) => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/reassign/`), { assignee_id: assigneeId }),
  nudge: (cid: number, id: number) => http.post<{ nudged_at: string }>(ownerPath(cid, `tasks/${id}/nudge/`)),
  /** `mentions` (membership ids) are told in Telegram too (contract 5); left out when nobody is. */
  comment: (cid: number, id: number, text: string, mentions: number[] = []) =>
    http.post<TaskComment>(ownerPath(cid, `tasks/${id}/comment/`), mentions.length ? { text, mentions } : { text }),
  move: (cid: number, id: number, to: BoardColumnId, reason = "") => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/move/`), { to, reason }),
  bulk: (cid: number, input: BulkInput) => http.post<BulkResponse>(ownerPath(cid, "tasks/bulk/"), input),
  /** Quick add (contract 1): what a typed title says about the deadline and urgency. Never toasts. */
  parse: (cid: number, text: string, signal?: AbortSignal) => http.post<QuickAddParse>(ownerPath(cid, "tasks/parse/"), { text }, { signal, toast: false }),
  /** Can't do it (contract 7): give it to someone else, set a new time, or cancel it. */
  resolveBlocker: (cid: number, id: number, input: { action: BlockerAction; assignee_id?: number; due_at?: string }) =>
    http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/blocker/resolve/`), input),
  /** Need more time (contract 8): the giver's answer. */
  decideExtension: (cid: number, id: number, approve: boolean) => http.post<TaskDetail>(ownerPath(cid, `tasks/${id}/extension/decide/`), { approve }),
};

/** Filter values (URL shape) as API params: empty values dropped. */
export function filterParams(filters: TaskFilterParams): Params {
  const params: Params = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;
    params[key] = value as Params[string];
  }
  return params;
}

// ─── Keys ───────────────────────────────────────────────────────────────────

export const taskKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  list: (cid: number, params: Params) => qk(cid, MODULE, "list", params),
  board: (cid: number, params: Params) => qk(cid, MODULE, "board", params),
  calendar: (cid: number, params: Params) => qk(cid, MODULE, "calendar", params),
  summary: (cid: number, params: Params = {}) => qk(cid, MODULE, "summary", params),
  reviews: (cid: number) => qk(cid, MODULE, "reviews"),
  options: (cid: number) => qk(cid, MODULE, "options"),
  detail: (cid: number, id: number) => qk(cid, MODULE, "detail", { id }),
  timeline: (cid: number, id: number) => qk(cid, MODULE, "timeline", { id }),
  proofs: (cid: number, params: Params) => qk(cid, MODULE, "proofs", params),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

// ─── Queries ────────────────────────────────────────────────────────────────

export function useTaskList(params: MaybeRefOrGetter<Params>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.list(cid.value, toValue(params))),
    queryFn: ({ signal }) => tasksApi.list(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

/**
 * How many tasks match `params`, fetching one row: the counts of "what needs you" chips. `check`
 * says whether that row really matches (a backend that ignores the filter answers with any task):
 * the count is null then, and the chip stays hidden. A refusal (no tasks.view_all) is null too.
 */
export function useTaskCount(params: MaybeRefOrGetter<Params>, check: (row: TaskRow) => boolean) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(cid.value, MODULE, "count", toValue(params))),
    queryFn: async ({ signal }) => {
      const page = await tasksApi.list(cid.value, { ...toValue(params), page_size: 1 }, signal);
      const first = page.results[0];
      return first && !check(first) ? null : page.count;
    },
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
    retry: false,
  });
}

export function useBoard(params: MaybeRefOrGetter<Params>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.board(cid.value, toValue(params))),
    queryFn: ({ signal }) => tasksApi.board(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useCalendar(params: MaybeRefOrGetter<Params>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.calendar(cid.value, toValue(params))),
    queryFn: ({ signal }) => tasksApi.calendar(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled) && !!toValue(params).from),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

/** The KPI numbers; widgets and the page share one fetch per parameter set. */
export function useSummary(params: MaybeRefOrGetter<Params> = {}) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.summary(cid.value, toValue(params))),
    queryFn: ({ signal }) => tasksApi.summary(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
  });
}

/** One-off work waiting for my check; routine work has its own queue (Routines → To confirm). */
export function useReviews() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.reviews(cid.value)),
    queryFn: ({ signal }) => tasksApi.reviews(cid.value, { page_size: 100, routines: "without" }, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 10_000,
  });
}

export function useTaskOptions() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.options(cid.value)),
    queryFn: ({ signal }) => tasksApi.options(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 5 * 60_000,
  });
}

export function useTaskDetail(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.detail(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => tasksApi.detail(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 10_000,
  });
}

export function useTimeline(id: MaybeRefOrGetter<number | null>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.timeline(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => tasksApi.timeline(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && toValue(enabled)),
    staleTime: 10_000,
  });
}

export function useProofWall(params: MaybeRefOrGetter<Params>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => taskKeys.proofs(cid.value, toValue(params))),
    queryFn: ({ signal }) => tasksApi.proofs(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Everything under `[companyId, "tasks"]` refetches after a write (lists, board, counts). */
export function useRefreshTasks() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => client.invalidateQueries({ queryKey: taskKeys.all(cid.value) });
}

/** A write on one task: the drawer shows the server's answer at once, then lists refresh. */
export function useTaskMutation<V>(run: (cid: number, vars: V) => Promise<TaskDetail>) {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshTasks();
  return useMutation({
    mutationFn: (vars: V) => run(cid.value, vars),
    onSuccess: (task) => client.setQueryData(taskKeys.detail(cid.value, task.id), task),
    onSettled: refresh,
  });
}

export function useCreateTasks() {
  const cid = useCompanyId();
  const refresh = useRefreshTasks();
  return useMutation({ mutationFn: (input: TaskCreateInput) => tasksApi.create(cid.value, input), onSettled: refresh });
}

export function useBulk() {
  const cid = useCompanyId();
  const refresh = useRefreshTasks();
  return useMutation({ mutationFn: (input: BulkInput) => tasksApi.bulk(cid.value, input), onSettled: refresh });
}

/**
 * A board drag. The card moves at once in every cached board; if the server refuses, the boards
 * snap back (and the HTTP layer shows why).
 */
export function useMoveCard() {
  const client = useQueryClient();
  const cid = useCompanyId();
  const refresh = useRefreshTasks();
  return useMutation({
    mutationFn: ({ task, to, reason }: { task: TaskRow; to: BoardColumnId; reason?: string }) => tasksApi.move(cid.value, task.id, to, reason ?? ""),
    onMutate: async ({ task, to }) => {
      const prefix = [cid.value, MODULE, "board"] as const;
      await client.cancelQueries({ queryKey: prefix });
      const snapshot = client.getQueriesData<{ columns: BoardColumn[] }>({ queryKey: prefix });
      for (const [key, data] of snapshot) {
        if (!data) continue;
        client.setQueryData(key, { columns: moveInColumns(data.columns, task, to) });
      }
      return { snapshot };
    },
    onError: (_error, _vars, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
    },
    onSettled: refresh,
  });
}

/** The columns with `task` taken out of its column and put at the top of `to`. */
export function moveInColumns(columns: BoardColumn[], task: TaskRow, to: BoardColumnId): BoardColumn[] {
  return columns.map((column) => {
    const without = column.items.filter((item) => item.id !== task.id);
    const removed = without.length !== column.items.length;
    if (column.id === to) {
      return { ...column, items: [{ ...task, status: to, moves: [] }, ...without], count: column.count + (removed ? 0 : 1) };
    }
    return removed ? { ...column, items: without, count: Math.max(0, column.count - 1) } : column;
  });
}
