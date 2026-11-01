/**
 * The AI endpoints (`/api/v1/owner/companies/{cid}/ai/…`, briefs/ai-contract.md §5) and the
 * vue-query helpers the pages use. Keys start with `[companyId, "ai"]`, so the `ai` pulse key
 * refreshes everything here. Drafts poll every second while the AI works on them and give up after
 * 90 s; the activity feed polls every 10 s while the page is in view and keeps its older pages.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyStore } from "@/stores/company";

import { arrivals, DRAFT_POLL_MS, mergeActivity, pollDecision, TURN_POLL_MS, turnIsLive } from "./lib";
import type {
  ActivityItem,
  ActivityPage,
  Agent,
  AgentPatch,
  AiDraft,
  AiSettings,
  AiSettingsPatch,
  AiStatus,
  ApplyDraft,
  ApplyResult,
  ChatMessage,
  Conversation,
  DraftSource,
  DraftStatus,
  Turn,
} from "./types";

export const MODULE = "ai";
const path = (cid: number, rest = "") => ownerPath(cid, `ai/${rest}`);

/** A list endpoint may answer with a page or a plain array. */
function rows<T>(body: Page<T> | T[]): T[] {
  return Array.isArray(body) ? body : body.results;
}

export interface DraftFilters {
  status?: DraftStatus | "";
  source?: DraftSource | "";
  author?: number | null;
  page?: number;
  page_size?: number;
}

export const aiApi = {
  status: (cid: number, signal?: AbortSignal) => http.get<AiStatus>(path(cid, "status/"), undefined, { signal }),
  settings: (cid: number, signal?: AbortSignal) => http.get<AiSettings>(path(cid, "settings/"), undefined, { signal }),
  saveSettings: (cid: number, patch: AiSettingsPatch) => http.patch<AiSettings>(path(cid, "settings/"), patch),
  enable: (cid: number) => http.post<AiStatus>(path(cid, "settings/enable/"), { accept_terms: true }),
  disable: (cid: number) => http.post<AiStatus>(path(cid, "settings/disable/")),

  agents: (cid: number, signal?: AbortSignal) => http.get<Agent[] | Page<Agent>>(path(cid, "agents/"), undefined, { signal }).then(rows),
  patchAgent: (cid: number, key: string, patch: AgentPatch) => http.patch<Agent>(path(cid, `agents/${key}/`), patch),
  runAgent: (cid: number, key: string) => http.post<{ queued: boolean }>(path(cid, `agents/${key}/run/`)),
  activity: (cid: number, params: { agent?: string; limit?: number; before?: number }, signal?: AbortSignal) =>
    http.get<ActivityPage>(path(cid, "activity/"), params, { signal }),

  drafts: (cid: number, params: DraftFilters, signal?: AbortSignal) => http.get<Page<AiDraft>>(path(cid, "task-drafts/"), { ...params }, { signal }),
  draft: (cid: number, id: number, signal?: AbortSignal) => http.get<AiDraft>(path(cid, `task-drafts/${id}/`), undefined, { signal }),
  /** The refusals (ai_off, limit_reached, text_too_long…) are explained where the text was typed. */
  fromText: (cid: number, text: string) => http.post<AiDraft>(path(cid, "task-drafts/"), { text }, { toast: false }),
  fromAudio: (cid: number, form: FormData) => http.form<AiDraft>(path(cid, "task-drafts/"), form, { toast: false }),
  apply: (cid: number, id: number, body: { drafts?: ApplyDraft[] }) => http.post<ApplyResult>(path(cid, `task-drafts/${id}/apply/`), body),
  discard: (cid: number, id: number) => http.post<void>(path(cid, `task-drafts/${id}/discard/`)),

  conversations: (cid: number, signal?: AbortSignal) => http.get<Conversation[] | Page<Conversation>>(path(cid, "conversations/"), undefined, { signal }).then(rows),
  newConversation: (cid: number) => http.post<Conversation>(path(cid, "conversations/"), {}),
  messages: (cid: number, id: number, signal?: AbortSignal) =>
    http.get<ChatMessage[] | Page<ChatMessage>>(path(cid, `conversations/${id}/messages/`), undefined, { signal }).then(rows),
  sendTurn: (cid: number, conversation: number, body: { text: string; page?: string }) =>
    http.post<{ turn_id: number }>(path(cid, `conversations/${conversation}/turns/`), body),
  turn: (cid: number, id: number, signal?: AbortSignal) => http.get<Turn>(path(cid, `turns/${id}/`), undefined, { signal }),
  cancelTurn: (cid: number, id: number) => http.post<void>(path(cid, `turns/${id}/cancel/`), {}, { toast: false }),
};

export const aiKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  status: (cid: number) => qk(cid, MODULE, "status"),
  settings: (cid: number) => qk(cid, MODULE, "settings"),
  agents: (cid: number) => qk(cid, MODULE, "agents"),
  activity: (cid: number, agent: string, limit: number) => qk(cid, MODULE, "activity", { agent, limit }),
  drafts: (cid: number, filters: DraftFilters) => qk(cid, MODULE, "drafts", { ...filters }),
  draft: (cid: number, id: number) => qk(cid, MODULE, "draft", { id }),
  conversations: (cid: number) => qk(cid, MODULE, "conversations"),
  messages: (cid: number, id: number) => qk(cid, MODULE, "messages", { id }),
  turn: (cid: number, id: number) => qk(cid, MODULE, "turn", { id }),
};

export function useCompanyId() {
  const company = useCompanyStore();
  return computed(() => company.currentId ?? 0);
}

// ─── Status, settings, agents ───────────────────────────────────────────────

export function useAiStatus() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.status(cid.value)),
    queryFn: ({ signal }) => aiApi.status(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 30_000,
  });
}

export function useAiSettings(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.settings(cid.value)),
    queryFn: ({ signal }) => aiApi.settings(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 60_000,
  });
}

/** While an agent works (or was just asked to), its card refreshes every few seconds. */
export const AGENTS_BUSY_POLL_MS = 4000;

export function useAgents() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.agents(cid.value)),
    queryFn: ({ signal }) => aiApi.agents(cid.value, signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 15_000,
    refetchInterval: (query) => ((query.state.data ?? []).some((agent) => agent.running) ? AGENTS_BUSY_POLL_MS : 60_000),
  });
}

/** Switch an agent or change its settings: the card changes at once and goes back if refused. */
export function usePatchAgent() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ key, patch }: { key: string; patch: AgentPatch }) => aiApi.patchAgent(cid.value, key, patch),
    onMutate: async ({ key, patch }) => {
      const queryKey = aiKeys.agents(cid.value);
      await client.cancelQueries({ queryKey });
      const before = client.getQueryData<Agent[]>(queryKey);
      if (before) {
        client.setQueryData<Agent[]>(
          queryKey,
          before.map((agent) => (agent.key === key ? { ...agent, ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}), config: { ...agent.config, ...patch.config } } : agent)),
        );
      }
      return { before };
    },
    onError: (_error, _input, context) => {
      if (context?.before) client.setQueryData(aiKeys.agents(cid.value), context.before);
    },
    onSuccess: (agent) => {
      client.setQueryData<Agent[]>(aiKeys.agents(cid.value), (list) => list?.map((item) => (item.key === agent.key ? agent : item)));
      void client.invalidateQueries({ queryKey: aiKeys.status(cid.value) });
    },
  });
}

export function useRunAgent() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => aiApi.runAgent(cid.value, key),
    onSuccess: (_result, key) => {
      // The run is queued: show the card working until the next answer says otherwise.
      client.setQueryData<Agent[]>(aiKeys.agents(cid.value), (list) => list?.map((agent) => (agent.key === key ? { ...agent, running: true } : agent)));
      setTimeout(() => void client.invalidateQueries({ queryKey: aiKeys.agents(cid.value) }), 1500);
    },
  });
}

// ─── Activity ───────────────────────────────────────────────────────────────

export const ACTIVITY_POLL_MS = 10_000;

/**
 * The feed: the newest page polled every 10 s while the page is in view (vue-query skips the
 * interval while the tab is hidden), older pages added below on demand, each item once. `fresh`
 * names the items that arrived since the last poll, for the slide-in.
 */
export function useActivityFeed(agent: MaybeRefOrGetter<string | null>, options: { limit?: number; live?: MaybeRefOrGetter<boolean> } = {}) {
  const cid = useCompanyId();
  const limit = options.limit ?? 30;
  const head = useQuery({
    queryKey: computed(() => aiKeys.activity(cid.value, toValue(agent) ?? "", limit)),
    queryFn: ({ signal }) => aiApi.activity(cid.value, { agent: toValue(agent) || undefined, limit }, signal),
    enabled: computed(() => cid.value > 0),
    refetchInterval: () => (toValue(options.live ?? true) ? ACTIVITY_POLL_MS : false),
  });
  const items = shallowRef<ActivityItem[]>([]);
  const fresh = ref<number[]>([]);
  /** Where the next older page starts; null when there is none. */
  const cursor = ref<number | null>(null);
  const olderPages = ref(0);
  const loadingOlder = ref(false);
  const olderFailed = ref(false);

  watch([cid, () => toValue(agent)], () => {
    items.value = [];
    fresh.value = [];
    cursor.value = null;
    olderPages.value = 0;
  });
  watch(
    () => head.data.value,
    (page) => {
      if (!page) return;
      const merged = mergeActivity(items.value, page.results);
      fresh.value = arrivals(items.value, merged);
      items.value = merged;
      if (olderPages.value === 0) cursor.value = page.next_before;
    },
    { immediate: true },
  );

  async function loadOlder(): Promise<void> {
    const before = cursor.value;
    if (before === null || loadingOlder.value) return;
    loadingOlder.value = true;
    olderFailed.value = false;
    try {
      const page = await aiApi.activity(cid.value, { agent: toValue(agent) || undefined, limit, before });
      items.value = mergeActivity(items.value, page.results);
      fresh.value = [];
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
    fresh,
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

// ─── Drafts ─────────────────────────────────────────────────────────────────

export function useDrafts(filters: MaybeRefOrGetter<DraftFilters>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.drafts(cid.value, toValue(filters))),
    queryFn: ({ signal }) => aiApi.drafts(cid.value, toValue(filters), signal),
    enabled: computed(() => cid.value > 0),
    placeholderData: keepPreviousData,
    // Notes the AI is still working on update on their own.
    refetchInterval: (query) => ((query.state.data?.results ?? []).some((draft) => ["queued", "transcribing", "thinking"].includes(draft.status)) ? 3000 : 30_000),
  });
}

/**
 * One draft, polled every second while the AI works on it. After 90 s without an answer it stops
 * and says so (`gaveUp`); `retry()` waits another 90 s.
 */
export function useDraft(id: MaybeRefOrGetter<number | null>) {
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
    queryKey: computed(() => aiKeys.draft(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => aiApi.draft(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id) && !gaveUp.value),
    refetchInterval: (q) => {
      const decision = pollDecision(q.state.data?.status, Date.now() - startedAt.value);
      if (decision === "give_up") gaveUp.value = true;
      return decision === "poll" ? DRAFT_POLL_MS : false;
    },
  });
  function retry(): void {
    startedAt.value = Date.now();
    gaveUp.value = false;
    void query.refetch();
  }
  return { ...query, gaveUp, retry };
}

/** After a draft changes: its own cache, the voice notes list and (for tasks made) the tasks lists. */
function useDraftRefresh() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return (draft: AiDraft, madeTasks: boolean) => {
    client.setQueryData(aiKeys.draft(cid.value, draft.id), draft);
    void client.invalidateQueries({ queryKey: qk(cid.value, MODULE, "drafts").slice(0, 3) });
    void client.invalidateQueries({ queryKey: aiKeys.agents(cid.value) });
    // The tasks module's queries all start with [companyId, "tasks"]: its lists show the new work.
    if (madeTasks) void client.invalidateQueries({ queryKey: moduleKey(cid.value, "tasks") });
  };
}

export function useApplyDraft() {
  const cid = useCompanyId();
  const refresh = useDraftRefresh();
  return useMutation({
    mutationFn: ({ id, drafts }: { id: number; drafts?: ApplyDraft[] }) => aiApi.apply(cid.value, id, drafts ? { drafts } : {}),
    onSuccess: (result) => refresh(result.draft, result.created.length > 0),
  });
}

export function useDiscardDraft() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => aiApi.discard(cid.value, id),
    onSuccess: (_result, id) => {
      client.setQueryData<AiDraft>(aiKeys.draft(cid.value, id), (draft) => (draft ? { ...draft, status: "discarded" } : draft));
      void client.invalidateQueries({ queryKey: qk(cid.value, MODULE, "drafts").slice(0, 3) });
    },
  });
}

/** Send a recording or typed text; the answer (202) seeds the draft's cache so polling starts from it. */
export function useCreateDraft() {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { text: string } | { audio: Blob; seconds: number; language: string; filename: string }) => {
      if ("text" in input) return aiApi.fromText(cid.value, input.text);
      const form = new FormData();
      form.append("audio", input.audio, input.filename);
      form.append("seconds", String(Math.max(1, Math.round(input.seconds))));
      form.append("language", input.language);
      return aiApi.fromAudio(cid.value, form);
    },
    onSuccess: (draft) => {
      client.setQueryData(aiKeys.draft(cid.value, draft.id), draft);
      void client.invalidateQueries({ queryKey: qk(cid.value, MODULE, "drafts").slice(0, 3) });
    },
  });
}

// ─── Ask AI ─────────────────────────────────────────────────────────────────

export function useConversations(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.conversations(cid.value)),
    queryFn: ({ signal }) => aiApi.conversations(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 30_000,
  });
}

export function useMessages(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.messages(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => aiApi.messages(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
  });
}

/** A turn being answered: polled every second until it is done, failed or cancelled. */
export function useTurn(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => aiKeys.turn(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => aiApi.turn(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    refetchInterval: (query) => (turnIsLive(query.state.data?.status) || !query.state.data ? TURN_POLL_MS : false),
  });
}
