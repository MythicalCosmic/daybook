import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Activity,
  Comment,
  Language,
  Me,
  Membership,
  Page,
  Period,
  Position,
  Repeat,
  Summary,
  Task,
  TeamStats,
} from "./types";

export const keys = {
  me: ["me"] as const,
  summary: (company: number) => ["summary", company] as const,
  tasks: (company: number) => ["tasks", company] as const,
  board: (company: number) => ["tasks", company, "board"] as const,
  review: (company: number) => ["tasks", company, "review"] as const,
  task: (company: number, id: number) => ["tasks", company, "detail", id] as const,
  comments: (company: number, id: number) => ["tasks", company, "comments", id] as const,
  activity: (company: number) => ["activity", company] as const,
  positions: (company: number) => ["positions", company] as const,
  team: (company: number, period: Period) => ["team", company, period] as const,
};

const tasksPath = (company: number) => `/companies/${company}/tasks`;

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

export function usePositions(company: number) {
  return useQuery({
    queryKey: keys.positions(company),
    queryFn: () => api<Position[]>(`/companies/${company}/positions/`),
  });
}

/** After anything changes a task: refresh lists, numbers and the feed. */
function useRefreshAfterTaskChange(company: number) {
  const client = useQueryClient();
  return (task?: Task) => {
    if (task) client.setQueryData(keys.task(company, task.id), task);
    void client.invalidateQueries({ queryKey: keys.tasks(company) });
    void client.invalidateQueries({ queryKey: keys.summary(company) });
    void client.invalidateQueries({ queryKey: keys.activity(company) });
  };
}

type ActionInput =
  | { taskId: number; action: "start" | "confirm" | "snooze" }
  | { taskId: number; action: "complete"; proofText: string; photo: File | null }
  | { taskId: number; action: "return"; reason: string }
  | { taskId: number; action: "cancel"; stopRepeating?: boolean };

export function useTaskAction(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: (input: ActionInput) => {
      const path = `${tasksPath(company)}/${input.taskId}/${input.action}/`;
      switch (input.action) {
        case "complete": {
          const form = new FormData();
          form.append("proof_text", input.proofText);
          if (input.photo) form.append("proof_photo", input.photo);
          return api<Task>(path, { method: "POST", form });
        }
        case "return":
          return api<Task>(path, { json: { reason: input.reason } });
        case "cancel":
          return api<Task>(path, { json: { stop_repeating: input.stopRepeating ?? false } });
        default:
          return api<Task>(path, { method: "POST" });
      }
    },
    onSuccess: refresh,
  });
}

export function useToggleChecklist(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: ({ taskId, itemId, done }: { taskId: number; itemId: number; done: boolean }) =>
      api<Task>(`${tasksPath(company)}/${taskId}/checklist/${itemId}/`, { json: { is_done: done } }),
    onSuccess: refresh,
  });
}

export type NewTask = { title: string; due_at: string | null; repeat: Repeat };

export function useCreateTask(company: number) {
  const refresh = useRefreshAfterTaskChange(company);
  return useMutation({
    mutationFn: (task: NewTask) => api<Task>(`${tasksPath(company)}/`, { json: task }),
    onSuccess: refresh,
  });
}

export function useAddComment(company: number, taskId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<Comment>(`${tasksPath(company)}/${taskId}/comments/`, { json: { text } }),
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

export function useSetLanguage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (language: Language) => api<Me>("/me/", { method: "PATCH", json: { language } }),
    onSuccess: (me) => client.setQueryData(keys.me, me),
  });
}
