/**
 * The employee projects endpoints (`/api/v1/companies/{id}/projects/…`, PLAN-OWNER §13.3), typed
 * by hand from `apps/projects/serializers.py` until the regenerated schema has them. Money never
 * reaches the mini app; days are company-local "YYYY-MM-DD".
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type Health = "on_track" | "at_risk" | "off_track";
export type ProjectStatus = "planning" | "active" | "on_hold" | "completed" | "cancelled";
export type CardStatus = "todo" | "in_progress" | "review" | "returned" | "done" | "cancelled";

export type Person = { id: number; name: string; photo_url: string | null };

export type Project = {
  id: number;
  key: string;
  name: string;
  color: string;
  icon: string;
  status: ProjectStatus;
  lead: Person | null;
  due_on: string | null;
  progress: { done: number; total: number; overdue: number; percent: number };
  health: Health | null;
  members: Person[];
  member_count: number;
  next_milestone: { id: number; name: string; due_on: string | null } | null;
  my_role: "lead" | "member" | "viewer" | null;
  my_open: number;
};

export type BoardList = { id: number; name: string; position: number; is_done: boolean; wip_limit: number | null };
export type Label = { id: number; name: string; color: string };

export type Card = {
  id: number;
  number: number | null;
  key: string;
  title: string;
  list_id: number | null;
  position: number;
  status: CardStatus;
  priority: "low" | "normal" | "high" | "urgent";
  due_at: string | null;
  assignee: Person | null;
  label_ids: number[];
  milestone_id: number | null;
  checklist_done: number;
  checklist_total: number;
  comments: number;
  proof: "none" | "photo" | "text" | "any";
  overdue: boolean;
  minutes: number;
  can_move: boolean;
};

export type Board = {
  project: Omit<Project, "my_open">;
  lists: BoardList[];
  cards: Card[];
  labels: Label[];
  people: Person[];
  capabilities: { manage: boolean; edit_cards: boolean; post_update: boolean };
};

export type Update = { id: number; health: Health; text: string; author: Person | null; created_at: string };

export type TimeEntry = {
  id: number;
  project: { id: number; name: string } | null;
  project_key: string | null;
  task: { id: number; name: string } | null;
  day: string;
  minutes: number;
  note: string;
};

export type Timer = {
  id: number;
  project: { id: number; name: string } | null;
  project_key: string | null;
  task: { id: number; name: string } | null;
  task_key: string | null;
  started_at: string;
};

export type MyWeek = { start: string; end: string; days: number[]; total: number; entries: TimeEntry[] };

const base = (company: number) => `/companies/${company}/projects`;

export const projectKeys = {
  all: (company: number) => ["projects", company] as const,
  mine: (company: number) => ["projects", company, "mine"] as const,
  board: (company: number, id: number) => ["projects", company, "board", id] as const,
  updates: (company: number, id: number) => ["projects", company, "updates", id] as const,
  timer: (company: number) => ["projects", company, "timer"] as const,
  week: (company: number) => ["projects", company, "week"] as const,
};

export const listMine = (company: number) => api<Project[]>(`${base(company)}/`);
export const getBoard = (company: number, id: number) => api<Board>(`${base(company)}/${id}/board/`);
export const moveCard = (company: number, id: number, taskId: number, list: number, position: number) =>
  api<{ card: Card; message: string }>(`${base(company)}/${id}/cards/${taskId}/move/`, { method: "POST", json: { list, position } });
export const listUpdates = (company: number, id: number) => api<Update[]>(`${base(company)}/${id}/updates/`);
export const postUpdate = (company: number, id: number, health: Health, text: string) =>
  api<Update>(`${base(company)}/${id}/updates/`, { method: "POST", json: { health, text } });
export const getTimer = (company: number) => api<{ timer: Timer | null }>(`${base(company)}/timer/`);
export const startTimer = (company: number, body: { task?: number | null; project?: number | null }) =>
  api<{ timer: Timer }>(`${base(company)}/timer/`, { method: "POST", json: body });
export const stopTimer = (company: number) => api<TimeEntry | undefined>(`${base(company)}/timer/stop/`, { method: "POST" });
export const getWeek = (company: number) => api<MyWeek>(`${base(company)}/time/`);
export const logTime = (company: number, body: { day: string; minutes: number; project?: number | null; task?: number | null; note?: string }) =>
  api<TimeEntry>(`${base(company)}/time/`, { method: "POST", json: body });

export function useMyProjects(company: number, enabled = true) {
  return useQuery({ queryKey: projectKeys.mine(company), queryFn: () => listMine(company), enabled, staleTime: 30_000 });
}

/** One project's board (`id` 0: nothing loads). `staleTime` lets a glance reuse a fresh copy. */
export function useBoard(company: number, id: number, { staleTime }: { staleTime?: number } = {}) {
  return useQuery({ queryKey: projectKeys.board(company, id), queryFn: () => getBoard(company, id), enabled: id > 0, staleTime });
}

export function useUpdates(company: number, id: number) {
  return useQuery({ queryKey: projectKeys.updates(company, id), queryFn: () => listUpdates(company, id), enabled: id > 0 });
}

export function useTimer(company: number, enabled = true) {
  return useQuery({ queryKey: projectKeys.timer(company), queryFn: () => getTimer(company).then((r) => r.timer), staleTime: 15_000, enabled });
}

export function useWeek(company: number, enabled = true) {
  return useQuery({ queryKey: projectKeys.week(company), queryFn: () => getWeek(company), enabled });
}

export type TimerAction = { kind: "start"; task: number } | { kind: "stop" };

/** Start my timer on a card (a running one is stopped and logged first) or stop it. */
export function useTimerAction(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (action: TimerAction): Promise<TimeEntry | null> => {
      if (action.kind === "start") {
        await startTimer(company, { task: action.task });
        return null;
      }
      return (await stopTimer(company)) ?? null;
    },
    // The timer, the cards' logged time and the week all change.
    onSettled: () => client.invalidateQueries({ queryKey: projectKeys.all(company) }),
  });
}

/** After any change: everything projects shows refreshes. */
export function useRefresh(company: number) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: projectKeys.all(company) });
}

/** Move a card: the board changes at once and snaps back if the server says no. */
export function useMoveCard(company: number, projectId: number) {
  const client = useQueryClient();
  const refresh = useRefresh(company);
  return useMutation({
    mutationFn: ({ card, list, position }: { card: Card; list: number; position: number }) => moveCard(company, projectId, card.id, list, position),
    onMutate: async ({ card, list, position }) => {
      const key = projectKeys.board(company, projectId);
      await client.cancelQueries({ queryKey: key });
      const snapshot = client.getQueryData<Board>(key);
      if (snapshot) client.setQueryData<Board>(key, { ...snapshot, cards: snapshot.cards.map((c) => (c.id === card.id ? { ...c, list_id: list, position } : c)) });
      return { snapshot, key };
    },
    onSuccess: (result, _vars, context) => {
      const board = context ? client.getQueryData<Board>(context.key) : undefined;
      if (board && context) client.setQueryData<Board>(context.key, { ...board, cards: board.cards.map((c) => (c.id === result.card.id ? result.card : c)) });
    },
    onError: (_error, _vars, context) => {
      if (context?.snapshot) client.setQueryData(context.key, context.snapshot);
    },
    onSettled: () => void refresh(),
  });
}
