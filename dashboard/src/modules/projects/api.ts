/**
 * The projects endpoints (plan §13.3) as typed functions, and the vue-query helpers the pages use.
 * Keys start with `[companyId, "projects"]`, so the pulse keys `projects.projects` and
 * `projects.time` (index.ts `invalidates`) refresh everything here. The board moves cards
 * optimistically and snaps back when the server refuses.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import type {
  Board,
  BoardList,
  Card,
  CardDetail,
  CardInput,
  ExpenseOptions,
  Financials,
  Label,
  ListParams,
  Member,
  Milestone,
  MoveResult,
  PersonOption,
  ProjectDetail,
  ProjectFile,
  ProjectInput,
  ProjectItem,
  ProjectLink,
  ProjectOptions,
  ProjectSettings,
  ProjectsSummary,
  RoadmapRow,
  TimeEntry,
  Timeline,
  Timer,
  TimeWeek,
  Update,
} from "./types";

export const MODULE = "projects";

const p = (companyId: number, tail = "") => ownerPath(companyId, `projects/${tail}`);
const one = (companyId: number, projectId: number, tail = "") => p(companyId, `${projectId}/${tail}`);

// ─── Endpoints ──────────────────────────────────────────────────────────────

export function listProjects(companyId: number, params: ListParams = {}, signal?: AbortSignal): Promise<Page<ProjectItem>> {
  return http.get<Page<ProjectItem>>(
    p(companyId),
    {
      status: params.status,
      health: params.health,
      lead: params.lead,
      branch: params.branch,
      q: params.q,
      mine: params.mine ? 1 : undefined,
      archived: params.archived ? 1 : undefined,
      ordering: params.ordering,
      page_size: 200,
    },
    { signal },
  );
}

export const getSummary = (companyId: number, signal?: AbortSignal) => http.get<ProjectsSummary>(p(companyId, "summary/"), undefined, { signal });
export const getPeople = (companyId: number, signal?: AbortSignal) => http.get<PersonOption[]>(p(companyId, "people/"), undefined, { signal });
export const getOptions = (companyId: number, signal?: AbortSignal) => http.get<ProjectOptions>(p(companyId, "options/"), undefined, { signal });
export const getRoadmap = (companyId: number, all = false, signal?: AbortSignal) =>
  http.get<{ rows: RoadmapRow[] }>(p(companyId, "roadmap/"), { all: all ? 1 : undefined }, { signal });
export const getSettings = (companyId: number, signal?: AbortSignal) => http.get<ProjectSettings>(p(companyId, "settings/"), undefined, { signal });
export const saveSettings = (companyId: number, body: Partial<ProjectSettings>) => http.patch<ProjectSettings>(p(companyId, "settings/"), body);

export const createProject = (companyId: number, body: ProjectInput) => http.post<ProjectDetail>(p(companyId), body);
export const getProject = (companyId: number, id: number, signal?: AbortSignal) => http.get<ProjectDetail>(one(companyId, id), undefined, { signal });
export const updateProject = (companyId: number, id: number, body: Partial<ProjectInput>) => http.patch<ProjectDetail>(one(companyId, id), body);
export const archiveProject = (companyId: number, id: number) => http.post<ProjectDetail>(one(companyId, id, "archive/"));
export const restoreProject = (companyId: number, id: number) => http.post<ProjectDetail>(one(companyId, id, "restore/"));
export const scheduleProject = (companyId: number, id: number, start_on: string, end_on: string) =>
  http.post<ProjectItem>(one(companyId, id, "schedule/"), { start_on, end_on });

export const getBoard = (companyId: number, id: number, signal?: AbortSignal) => http.get<Board>(one(companyId, id, "board/"), undefined, { signal });
export const listCards = (companyId: number, id: number, signal?: AbortSignal) => http.get<Card[]>(one(companyId, id, "cards/"), undefined, { signal });
export const createCard = (companyId: number, id: number, body: CardInput) => http.post<Card>(one(companyId, id, "cards/"), body);
export const getCard = (companyId: number, id: number, taskId: number, signal?: AbortSignal) =>
  http.get<CardDetail>(one(companyId, id, `cards/${taskId}/`), undefined, { signal });
export const updateCard = (companyId: number, id: number, taskId: number, body: Partial<CardInput>) => http.patch<Card>(one(companyId, id, `cards/${taskId}/`), body);
/** Errors here are shown by the board itself (it opens the card on `needs_proof`), not toasted. */
export const moveCard = (companyId: number, id: number, taskId: number, list: number, position: number) =>
  http.post<MoveResult>(one(companyId, id, `cards/${taskId}/move/`), { list, position }, { toast: false });
export const scheduleCard = (companyId: number, id: number, taskId: number, start_on: string, end_on: string) =>
  http.post<Card>(one(companyId, id, `cards/${taskId}/schedule/`), { start_on, end_on });

export const createList = (companyId: number, id: number, body: { name: string; wip_limit?: number | null }) => http.post<BoardList>(one(companyId, id, "lists/"), body);
export const updateList = (companyId: number, id: number, listId: number, body: { name?: string; wip_limit?: number | null }) =>
  http.patch<BoardList>(one(companyId, id, `lists/${listId}/`), body);
export const deleteList = (companyId: number, id: number, listId: number) => http.delete(one(companyId, id, `lists/${listId}/`));
export const reorderLists = (companyId: number, id: number, ids: number[]) => http.post<BoardList[]>(one(companyId, id, "lists/reorder/"), { ids });

export const listMilestones = (companyId: number, id: number, signal?: AbortSignal) => http.get<Milestone[]>(one(companyId, id, "milestones/"), undefined, { signal });
export const createMilestone = (companyId: number, id: number, body: Partial<Milestone>) => http.post<Milestone>(one(companyId, id, "milestones/"), body);
export const updateMilestone = (companyId: number, id: number, milestoneId: number, body: Partial<Milestone>) =>
  http.patch<Milestone>(one(companyId, id, `milestones/${milestoneId}/`), body);
export const deleteMilestone = (companyId: number, id: number, milestoneId: number) => http.delete(one(companyId, id, `milestones/${milestoneId}/`));

export const createLabel = (companyId: number, id: number, body: { name: string; color?: string }) => http.post<Label>(one(companyId, id, "labels/"), body);
export const updateLabel = (companyId: number, id: number, labelId: number, body: { name?: string; color?: string }) =>
  http.patch<Label>(one(companyId, id, `labels/${labelId}/`), body);
export const deleteLabel = (companyId: number, id: number, labelId: number) => http.delete(one(companyId, id, `labels/${labelId}/`));

export const listMembers = (companyId: number, id: number, signal?: AbortSignal) => http.get<Member[]>(one(companyId, id, "members/"), undefined, { signal });
export const addMember = (companyId: number, id: number, membership: number, role: "member" | "viewer" = "member") =>
  http.post<Member[]>(one(companyId, id, "members/"), { membership, role });
export const setMemberRole = (companyId: number, id: number, rowId: number, role: "member" | "viewer") => http.patch<Member[]>(one(companyId, id, `members/${rowId}/`), { role });
export const removeMember = (companyId: number, id: number, rowId: number) => http.delete(one(companyId, id, `members/${rowId}/`));

export const listUpdates = (companyId: number, id: number, signal?: AbortSignal) => http.get<Update[]>(one(companyId, id, "updates/"), undefined, { signal });
export const postUpdate = (companyId: number, id: number, body: { health: string; text: string }) => http.post<Update>(one(companyId, id, "updates/"), body);

export const listFiles = (companyId: number, id: number, signal?: AbortSignal) => http.get<ProjectFile[]>(one(companyId, id, "files/"), undefined, { signal });
export function uploadFile(companyId: number, id: number, file: File): Promise<ProjectFile> {
  const form = new FormData();
  form.append("file", file);
  form.append("name", file.name);
  return http.form<ProjectFile>(one(companyId, id, "files/"), form);
}
export const deleteFile = (companyId: number, id: number, fileId: number) => http.delete(one(companyId, id, `files/${fileId}/`));
export const listLinks = (companyId: number, id: number, signal?: AbortSignal) => http.get<ProjectLink[]>(one(companyId, id, "links/"), undefined, { signal });
export const addLink = (companyId: number, id: number, body: { title: string; url: string }) => http.post<ProjectLink>(one(companyId, id, "links/"), body);
export const deleteLink = (companyId: number, id: number, linkId: number) => http.delete(one(companyId, id, `links/${linkId}/`));

export const getFinancials = (companyId: number, id: number, signal?: AbortSignal) => http.get<Financials>(one(companyId, id, "financials/"), undefined, { signal });
export const getExpenseOptions = (companyId: number, id: number, signal?: AbortSignal) =>
  http.get<ExpenseOptions>(one(companyId, id, "expense-options/"), undefined, { signal });
export const addExpense = (
  companyId: number,
  id: number,
  body: { amount: string; account: number; category: number; occurred_on: string; description?: string; counterparty?: number | null },
) => http.post<{ id: number; base_amount: string }>(one(companyId, id, "expenses/"), body);

export const getTimeline = (companyId: number, id: number, signal?: AbortSignal) => http.get<Timeline>(one(companyId, id, "timeline/"), undefined, { signal });

export const getTimeWeek = (companyId: number, params: { week?: string; project?: number; person?: number[] }, signal?: AbortSignal) =>
  http.get<TimeWeek>(p(companyId, "time/"), { week: params.week, project: params.project, person: params.person }, { signal });
export const logTime = (
  companyId: number,
  body: { day: string; minutes: number; project?: number | null; task?: number | null; note?: string; billable?: boolean; person?: number | null },
) => http.post<TimeEntry>(p(companyId, "time/"), body);
export const updateTime = (companyId: number, entryId: number, body: { minutes?: number; day?: string; note?: string; billable?: boolean }) =>
  http.patch<TimeEntry>(p(companyId, `time/${entryId}/`), body);
export const deleteTime = (companyId: number, entryId: number) => http.delete(p(companyId, `time/${entryId}/`));
export const listTimers = (companyId: number, signal?: AbortSignal) => http.get<Timer[]>(p(companyId, "timers/"), undefined, { signal });
export const startTimer = (companyId: number, body: { task?: number | null; project?: number | null; note?: string }) => http.post<Timer>(p(companyId, "timers/"), body);
export const stopTimer = (companyId: number) => http.post<TimeEntry | undefined>(p(companyId, "timers/stop/"));

// ─── Keys ───────────────────────────────────────────────────────────────────

export const projectKeys = {
  all: (companyId: number) => moduleKey(companyId, MODULE),
  list: (companyId: number, params: ListParams) => qk(companyId, MODULE, "list", { ...params }),
  summary: (companyId: number) => qk(companyId, MODULE, "summary"),
  people: (companyId: number) => qk(companyId, MODULE, "people"),
  options: (companyId: number) => qk(companyId, MODULE, "options"),
  roadmap: (companyId: number, all: boolean) => qk(companyId, MODULE, "roadmap", { all }),
  settings: (companyId: number) => qk(companyId, MODULE, "settings"),
  project: (companyId: number, id: number) => qk(companyId, MODULE, "project", { id }),
  board: (companyId: number, id: number) => qk(companyId, MODULE, "board", { id }),
  cards: (companyId: number, id: number) => qk(companyId, MODULE, "cards", { id }),
  card: (companyId: number, id: number, taskId: number) => qk(companyId, MODULE, "card", { id, taskId }),
  milestones: (companyId: number, id: number) => qk(companyId, MODULE, "milestones", { id }),
  members: (companyId: number, id: number) => qk(companyId, MODULE, "members", { id }),
  updates: (companyId: number, id: number) => qk(companyId, MODULE, "updates", { id }),
  files: (companyId: number, id: number) => qk(companyId, MODULE, "files", { id }),
  links: (companyId: number, id: number) => qk(companyId, MODULE, "links", { id }),
  financials: (companyId: number, id: number) => qk(companyId, MODULE, "financials", { id }),
  expenseOptions: (companyId: number, id: number) => qk(companyId, MODULE, "expense-options", { id }),
  timeline: (companyId: number, id: number) => qk(companyId, MODULE, "timeline", { id }),
  time: (companyId: number, params: Record<string, unknown>) => qk(companyId, MODULE, "time", params),
  timers: (companyId: number) => qk(companyId, MODULE, "timers"),
};

// ─── Queries ────────────────────────────────────────────────────────────────

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

function enabledFor(companyId: { value: number }, extra: MaybeRefOrGetter<boolean> = true) {
  return computed(() => companyId.value > 0 && toValue(extra));
}

export function useProjects(params: MaybeRefOrGetter<ListParams>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.list(companyId.value, toValue(params))),
    queryFn: ({ signal }) => listProjects(companyId.value, toValue(params), signal),
    enabled: enabledFor(companyId),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useSummary() {
  const companyId = useCompanyId();
  return useQuery({ queryKey: computed(() => projectKeys.summary(companyId.value)), queryFn: ({ signal }) => getSummary(companyId.value, signal), enabled: enabledFor(companyId), staleTime: 15_000 });
}

export function usePeople() {
  const companyId = useCompanyId();
  return useQuery({ queryKey: computed(() => projectKeys.people(companyId.value)), queryFn: ({ signal }) => getPeople(companyId.value, signal), enabled: enabledFor(companyId), staleTime: 60_000 });
}

export function useOptions() {
  const companyId = useCompanyId();
  return useQuery({ queryKey: computed(() => projectKeys.options(companyId.value)), queryFn: ({ signal }) => getOptions(companyId.value, signal), enabled: enabledFor(companyId), staleTime: 60_000 });
}

export function useRoadmap(all: MaybeRefOrGetter<boolean>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.roadmap(companyId.value, toValue(all))),
    queryFn: ({ signal }) => getRoadmap(companyId.value, toValue(all), signal),
    enabled: enabledFor(companyId),
    placeholderData: keepPreviousData,
  });
}

export function useProject(id: MaybeRefOrGetter<number>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.project(companyId.value, toValue(id))),
    queryFn: ({ signal }) => getProject(companyId.value, toValue(id), signal),
    enabled: enabledFor(companyId, () => toValue(id) > 0),
    staleTime: 10_000,
  });
}

export function useBoard(id: MaybeRefOrGetter<number>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.board(companyId.value, toValue(id))),
    queryFn: ({ signal }) => getBoard(companyId.value, toValue(id), signal),
    enabled: enabledFor(companyId, () => toValue(id) > 0),
    staleTime: 5_000,
  });
}

export function useCard(id: MaybeRefOrGetter<number>, taskId: MaybeRefOrGetter<number | null>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.card(companyId.value, toValue(id), toValue(taskId) ?? 0)),
    queryFn: ({ signal }) => getCard(companyId.value, toValue(id), toValue(taskId) ?? 0, signal),
    enabled: enabledFor(companyId, () => toValue(id) > 0 && (toValue(taskId) ?? 0) > 0),
  });
}

function useProjectQuery<T>(resource: keyof typeof projectKeys, id: MaybeRefOrGetter<number>, fetch: (cid: number, pid: number, signal?: AbortSignal) => Promise<T>, enabled: MaybeRefOrGetter<boolean> = true) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => qk(companyId.value, MODULE, resource, { id: toValue(id) })),
    queryFn: ({ signal }) => fetch(companyId.value, toValue(id), signal),
    enabled: enabledFor(companyId, () => toValue(id) > 0 && toValue(enabled)),
    staleTime: 10_000,
  });
}

export const useMilestones = (id: MaybeRefOrGetter<number>) => useProjectQuery("milestones", id, listMilestones);
export const useMembers = (id: MaybeRefOrGetter<number>) => useProjectQuery("members", id, listMembers);
export const useUpdates = (id: MaybeRefOrGetter<number>) => useProjectQuery("updates", id, listUpdates);
export const useFiles = (id: MaybeRefOrGetter<number>) => useProjectQuery("files", id, listFiles);
export const useLinks = (id: MaybeRefOrGetter<number>) => useProjectQuery("links", id, listLinks);
export const useCards = (id: MaybeRefOrGetter<number>) => useProjectQuery("cards", id, listCards);
export const useTimeline = (id: MaybeRefOrGetter<number>) => useProjectQuery("timeline", id, getTimeline);
export const useFinancials = (id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) => useProjectQuery("financials", id, getFinancials, enabled);
export const useExpenseOptions = (id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean>) => useProjectQuery("expenseOptions", id, getExpenseOptions, enabled);

export function useTimeWeek(params: MaybeRefOrGetter<{ week?: string; project?: number; person?: number[] }>) {
  const companyId = useCompanyId();
  return useQuery({
    queryKey: computed(() => projectKeys.time(companyId.value, { ...toValue(params) })),
    queryFn: ({ signal }) => getTimeWeek(companyId.value, toValue(params), signal),
    enabled: enabledFor(companyId),
    placeholderData: keepPreviousData,
  });
}

export function useTimers() {
  const companyId = useCompanyId();
  return useQuery({ queryKey: computed(() => projectKeys.timers(companyId.value)), queryFn: ({ signal }) => listTimers(companyId.value, signal), enabled: enabledFor(companyId), staleTime: 10_000 });
}

export function useSettings() {
  const companyId = useCompanyId();
  return useQuery({ queryKey: computed(() => projectKeys.settings(companyId.value)), queryFn: ({ signal }) => getSettings(companyId.value, signal), enabled: enabledFor(companyId) });
}

// ─── Mutations ──────────────────────────────────────────────────────────────

/** Refetch everything of the module (after a change elsewhere in the project). */
export function useRefreshProjects() {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return () => client.invalidateQueries({ queryKey: projectKeys.all(companyId.value) });
}

/** A card moved on the board: the cache moves it at once, the server confirms or it snaps back. */
export function applyMove(board: Board, card: Card, listId: number, position: number): Board {
  return { ...board, cards: board.cards.map((c) => (c.id === card.id ? { ...c, list_id: listId, position } : c)) };
}

export function useMoveCard(projectId: MaybeRefOrGetter<number>) {
  const client = useQueryClient();
  const companyId = useCompanyId();
  const refresh = useRefreshProjects();
  return useMutation({
    mutationFn: ({ card, listId, position }: { card: Card; listId: number; position: number }) =>
      moveCard(companyId.value, toValue(projectId), card.id, listId, position),
    onMutate: async ({ card, listId, position }) => {
      const key = projectKeys.board(companyId.value, toValue(projectId));
      await client.cancelQueries({ queryKey: key });
      const snapshot = client.getQueryData<Board>(key);
      if (snapshot) client.setQueryData<Board>(key, applyMove(snapshot, card, listId, position));
      return { snapshot, key };
    },
    onSuccess: (result, _vars, context) => {
      const board = context?.key ? client.getQueryData<Board>(context.key) : undefined;
      if (board && context?.key) client.setQueryData<Board>(context.key, { ...board, cards: board.cards.map((c) => (c.id === result.card.id ? result.card : c)) });
    },
    onError: (_error, _vars, context) => {
      if (context?.snapshot && context.key) client.setQueryData(context.key, context.snapshot);
    },
    onSettled: () => void refresh(),
  });
}

export function useCreateCard(projectId: MaybeRefOrGetter<number>) {
  const client = useQueryClient();
  const companyId = useCompanyId();
  return useMutation({
    mutationFn: (body: CardInput) => createCard(companyId.value, toValue(projectId), body),
    onSuccess: (card) => {
      const key = projectKeys.board(companyId.value, toValue(projectId));
      const board = client.getQueryData<Board>(key);
      if (board) client.setQueryData<Board>(key, { ...board, cards: [...board.cards, card] });
      void client.invalidateQueries({ queryKey: projectKeys.all(companyId.value) });
    },
  });
}

/** A mutation that refreshes the module afterwards. */
export function useProjectMutation<V, R>(fn: (companyId: number, vars: V) => Promise<R>) {
  const companyId = useCompanyId();
  const refresh = useRefreshProjects();
  return useMutation({ mutationFn: (vars: V) => fn(companyId.value, vars), onSuccess: () => void refresh() });
}
