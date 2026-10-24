import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, ApiError } from "./client";
import type {
  Activity,
  BlockerReason,
  BlockerResolution,
  Comment,
  ConfirmMany,
  Holiday,
  Language,
  Me,
  MemberBrief,
  Membership,
  Page,
  Period,
  Position,
  Priority,
  Proof,
  Repeat,
  SnoozePreset,
  Summary,
  Task,
  TeamStats,
  TimeOff,
} from "./types";

export const keys = {
  me: ["me"] as const,
  summary: (company: number) => ["summary", company] as const,
  tasks: (company: number) => ["tasks", company] as const,
  board: (company: number) => ["tasks", company, "board"] as const,
  review: (company: number) => ["tasks", company, "review"] as const,
  given: (company: number) => ["tasks", company, "given"] as const,
  task: (company: number, id: number) => ["tasks", company, "detail", id] as const,
  comments: (company: number, id: number) => ["tasks", company, "comments", id] as const,
  activity: (company: number) => ["activity", company] as const,
  positions: (company: number) => ["positions", company] as const,
  members: (company: number) => ["members", company] as const,
  team: (company: number, period: Period) => ["team", company, period] as const,
  timeOff: (company: number) => ["timeOff", company] as const,
  holidays: (company: number) => ["holidays", company] as const,
};

const tasksPath = (company: number) => `/companies/${company}/tasks`;

/**
 * The backend doesn't have this endpoint yet: no route (Django's plain 404, no JSON body) or a
 * route that takes no POST (405). A 404 that explains itself ("No such task") is a real answer.
 */
export function isMissingEndpoint(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 405 || (error.status === 404 && error.detail === null));
}

export function useMe(options: { poll?: boolean; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api<Me>("/me/"),
    refetchInterval: options.poll ? 4000 : false,
    enabled: options.enabled ?? true,
  });
}

export function useSummary(company: number) {
  return useQuery({
    queryKey: keys.summary(company),
    queryFn: () => api<Summary>(`/companies/${company}/summary/`),
  });
}

export function useBoard(company: number) {
  return useQuery({
    queryKey: keys.board(company),
    queryFn: () =>
      api<Page<Task>>(`${tasksPath(company)}/?scope=board&page_size=200`).then((page) => page.results),
  });
}

export function useReviewQueue(company: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.review(company),
    queryFn: () =>
      api<Page<Task>>(`${tasksPath(company)}/?scope=review&page_size=200`).then(
        (page) => page.results,
      ),
    enabled,
  });
}

/**
 * Work I gave others that is still going (Tasks → Given by me): `given_by=me` with `scope=created`
 * beside it, so a backend without the new filter still answers with the same list.
 */
export function useGivenByMe(company: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.given(company),
    queryFn: () =>
      api<Page<Task>>(
        `${tasksPath(company)}/?given_by=me&scope=created&status=todo,in_progress,returned,review&page_size=200`,
      ).then((page) => page.results),
    enabled,
  });
}

/** The people this member may hand work to (the branch team; everyone with branches.all). */
export function useMembers(company: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.members(company),
    queryFn: () => api<MemberBrief[]>(`/companies/${company}/members/`),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useTask(company: number, id: number) {
  return useQuery({
    queryKey: keys.task(company, id),
    queryFn: () => api<Task>(`${tasksPath(company)}/${id}/`),
  });
}

export function useComments(company: number, id: number) {
  return useQuery({
    queryKey: keys.comments(company, id),
    queryFn: () => api<Comment[]>(`${tasksPath(company)}/${id}/comments/`),
  });
}

export function useActivity(company: number) {
  return useQuery({
    queryKey: keys.activity(company),
    queryFn: () =>
      api<Page<Activity>>(`/companies/${company}/activity/?page_size=100`).then(
        (page) => page.results,
      ),
  });
}

export function useTeamStats(company: number, period: Period) {
  return useQuery({
    queryKey: keys.team(company, period),
    queryFn: () => api<TeamStats>(`/companies/${company}/team-stats/?period=${period}`),
    staleTime: 60_000,
  });
}

export function useTimeOff(company: number) {
  return useQuery({
    queryKey: keys.timeOff(company),
    queryFn: () => api<TimeOff[]>(`/companies/${company}/time-off/`),
  });
}

export function useHolidays(company: number) {
  return useQuery({
    queryKey: keys.holidays(company),
    queryFn: () => api<Holiday[]>(`/companies/${company}/holidays/`),
    staleTime: 60 * 60_000,
  });
}

export function useRequestTimeOff(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: { first_day: string; last_day: string; reason: string }) =>
      api<TimeOff>(`/companies/${company}/time-off/`, { json: request }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.timeOff(company) });
      void client.invalidateQueries({ queryKey: keys.summary(company) });
    },
  });
}

export function useCancelTimeOff(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      api<TimeOff>(`/companies/${company}/time-off/${id}/cancel/`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.timeOff(company) });
      void client.invalidateQueries({ queryKey: keys.summary(company) });
    },
  });
}

export function usePositions(company: number) {
  return useQuery({
    queryKey: keys.positions(company),
    queryFn: () => api<Position[]>(`/companies/${company}/positions/`),
  });
}

/**
 * After anything changes a task: refresh lists, numbers and the feed. A plain function as well as
 * a hook, for work that outlives its screen (an Undo pressed after the task closed).
 */
export function refreshAfterTaskChange(client: QueryClient, company: number, task?: Task) {
  if (task) client.setQueryData(keys.task(company, task.id), task);
  void client.invalidateQueries({ queryKey: keys.tasks(company) });
  void client.invalidateQueries({ queryKey: keys.summary(company) });
  void client.invalidateQueries({ queryKey: keys.activity(company) });
}

function useRefreshAfterTaskChange(company: number) {
  const client = useQueryClient();
  return (task?: Task) => refreshAfterTaskChange(client, company, task);
}

/** Undo a Done: the person who finished it, within a minute, before anyone confirmed it. */
export async function reopenTask(client: QueryClient, company: number, taskId: number): Promise<Task> {
  const task = await api<Task>(`${tasksPath(company)}/${taskId}/reopen/`, { method: "POST" });
  refreshAfterTaskChange(client, company, task);
  return task;
}

export type TaskChanges = { due_at?: string | null; title?: string; description?: string; priority?: Priority };

export type ActionInput =
  | { taskId: number; action: "start" | "confirm" | "reopen" }
  | { taskId: number; action: "snooze"; preset?: SnoozePreset }
  | { taskId: number; action: "complete"; proofText: string; photo: File | null }
  | { taskId: number; action: "return"; reason: string }
  | { taskId: number; action: "cancel"; stopRepeating?: boolean }
  | { taskId: number; action: "edit"; changes: TaskChanges }
  | { taskId: number; action: "blocker"; reasonCode: BlockerReason; note: string }
  | { taskId: number; action: "extension"; until: string; note: string }
  | { taskId: number; action: "resolveBlocker"; resolution: BlockerResolution; assigneeId?: number; dueAt?: string }
  | { taskId: number; action: "decideExtension"; approve: boolean; until?: string };

function runAction(company: number, input: ActionInput): Promise<Task> {
  const base = `${tasksPath(company)}/${input.taskId}`;
  switch (input.action) {
    case "complete": {
      const form = new FormData();
      form.append("proof_text", input.proofText);
      if (input.photo) form.append("proof_photo", input.photo);
      return api<Task>(`${base}/complete/`, { method: "POST", form });
    }
    case "return":
      return api<Task>(`${base}/return/`, { json: { reason: input.reason } });
    case "cancel":
      return api<Task>(`${base}/cancel/`, { json: { stop_repeating: input.stopRepeating ?? false } });
    case "snooze":
      // Without a preset, the policy's own minutes, as before the choices existed.
      return input.preset
        ? api<Task>(`${base}/snooze/`, { json: { preset: input.preset } })
        : api<Task>(`${base}/snooze/`, { method: "POST" });
    case "edit":
      return api<Task>(`${base}/`, { method: "PATCH", json: input.changes });
    case "blocker":
      return api<Task>(`${base}/blocker/`, { json: { reason_code: input.reasonCode, note: input.note } });
    case "extension":
      return api<Task>(`${base}/extension/`, { json: { until: input.until, note: input.note } });
    case "resolveBlocker":
      return api<Task>(`${base}/blocker/resolve/`, {
        json: {
          action: input.resolution,
          ...(input.assigneeId !== undefined ? { assignee_id: input.assigneeId } : {}),
          ...(input.dueAt !== undefined ? { due_at: input.dueAt } : {}),
        },
      }).catch((error: unknown) => {
        // A backend without the resolve endpoint: a new time and cancelling still work the old way.
        if (!isMissingEndpoint(error)) throw error;
        if (input.resolution === "new_due" && input.dueAt) {
          return runAction(company, { taskId: input.taskId, action: "edit", changes: { due_at: input.dueAt } });
        }
        if (input.resolution === "cancel") return runAction(company, { taskId: input.taskId, action: "cancel" });
        throw error;
      });
    case "decideExtension":
      return api<Task>(`${base}/extension/decide/`, { json: { approve: input.approve } }).catch((error: unknown) => {
        // Without the endpoint, approving still moves the deadline; declining has nowhere to go.
        if (!isMissingEndpoint(error) || !input.approve || !input.until) throw error;
        return runAction(company, { taskId: input.taskId, action: "edit", changes: { due_at: input.until } });
      });
    default:
      return api<Task>(`${base}/${input.action}/`, { method: "POST" });
  }
}

export function useTaskAction(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: (input: ActionInput) => runAction(company, input),
    onSuccess: refresh,
  });
}

/** Confirm several finished tasks at once (a routine's runs): each by the same rules as one. */
export function useConfirmMany(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: (ids: number[]) => api<ConfirmMany>(`${tasksPath(company)}/confirm/`, { json: { ids } }),
    onSuccess: () => refresh(),
  });
}

/**
 * Tick a checklist step. The tick shows at once (PLAN-OWNER: "checklist toggles never wait") and
 * goes back if the server refuses it.
 */
export function useToggleChecklist(company: number) {
  const client = useQueryClient();
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: ({ taskId, itemId, done }: { taskId: number; itemId: number; done: boolean }) =>
      api<Task>(`${tasksPath(company)}/${taskId}/checklist/${itemId}/`, { json: { is_done: done } }),
    onMutate: async ({ taskId, itemId, done }) => {
      const key = keys.task(company, taskId);
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<Task>(key);
      if (before) {
        client.setQueryData<Task>(key, {
          ...before,
          checklist: before.checklist.map((item) => (item.id === itemId ? { ...item, is_done: done } : item)),
        });
      }
      return { before };
    },
    onError: (_error, { taskId }, context) => {
      if (context?.before) client.setQueryData(keys.task(company, taskId), context.before);
    },
    onSuccess: refresh,
  });
}

export type NewTask = {
  title: string;
  due_at: string | null;
  repeat: Repeat;
  /** A colleague's membership: work given to someone else (needs tasks.assign). Left out: my own. */
  assignee_id?: number | null;
  priority?: Priority;
  proof?: Proof;
  needs_confirmation?: boolean;
  description?: string;
  checklist?: string[];
};

export function useCreateTask(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: (task: NewTask) => api<Task>(`${tasksPath(company)}/`, { json: task }),
    onSuccess: refresh,
  });
}

export type NewComment = { text: string; mentions: number[] };

export function useAddComment(company: number, taskId: number) {
  const client = useQueryClient();
  return useMutation({
    // The people picked with @ hear about it in the bot; a backend that doesn't know mentions yet
    // ignores the field and keeps the text.
    mutationFn: ({ text, mentions }: NewComment) =>
      api<Comment>(`${tasksPath(company)}/${taskId}/comments/`, { json: mentions.length ? { text, mentions } : { text } }),
    onSuccess: (comment) => {
      client.setQueryData<Comment[]>(keys.comments(company, taskId), (comments) => [
        ...(comments ?? []),
        comment,
      ]);
    },
  });
}

export function useMarkFeedRead(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ marked: number }>(`/companies/${company}/activity/read/`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.activity(company) });
      void client.invalidateQueries({ queryKey: keys.summary(company) });
    },
  });
}

export type Onboarding = { first_name: string; last_name: string; position_id: number | null };

export function useOnboard(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (details: Onboarding) =>
      api<Membership>(`/companies/${company}/onboarding/`, { json: details }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.me }),
  });
}

/**
 * Change the language: the app switches at once, the server saves it (and relabels the bot's
 * chat), and a refusal puts the old language back.
 */
export function useSetLanguage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (language: Language) => api<Me>("/me/", { method: "PATCH", json: { language } }),
    onMutate: async (language) => {
      await client.cancelQueries({ queryKey: keys.me });
      const before = client.getQueryData<Me>(keys.me);
      if (before) client.setQueryData<Me>(keys.me, { ...before, language });
      return { before };
    },
    onError: (_error, _language, context) => {
      if (context?.before) client.setQueryData(keys.me, context.before);
    },
    onSuccess: (me) => client.setQueryData(keys.me, me),
  });
}
