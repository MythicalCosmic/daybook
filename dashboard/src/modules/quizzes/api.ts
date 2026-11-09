/**
 * The quizzes, question bank, checks, skills and tutor endpoints as typed functions, and the
 * vue-query helpers the pages use. Keys start with `[companyId, "quizzes"]`, so the pulse keys in
 * `invalidates` (index.ts) refresh every query of the module, and switching company never shows
 * another's data. The tutor's chat goes through Ask AI's turn endpoints.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type {
  ChatMessage,
  Check,
  CheckInput,
  Conversation,
  DailySettings,
  DraftInput,
  DraftJob,
  DraftJobDetail,
  ImageRef,
  OwnerAttempt,
  Paginated,
  PersonSkills,
  PreviewItem,
  Question,
  QuestionInput,
  QuestionState,
  Quiz,
  QuizInput,
  QuizRow,
  Results,
  RoundDetail,
  RoundRow,
  SkillMatrix,
  Suggestion,
  TopicOption,
  Turn,
  Tutor,
} from "./types";

export const MODULE = "quizzes";

const path = (cid: number, rest: string) => ownerPath(cid, `learning/${rest}`);

export const quizzesApi = {
  questions: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<Paginated<Question>>(path(cid, "questions/"), params, { signal }),
  question: (cid: number, id: number) => http.get<Question>(path(cid, `questions/${id}/`)),
  createQuestion: (cid: number, input: QuestionInput) => http.post<Question>(path(cid, "questions/"), input),
  updateQuestion: (cid: number, id: number, input: QuestionInput) => http.patch<Question>(path(cid, `questions/${id}/`), input),
  deleteQuestion: (cid: number, id: number) => http.delete(path(cid, `questions/${id}/`)),
  bulk: (cid: number, ids: number[], state: QuestionState) => http.post<{ changed: number }>(path(cid, "questions/bulk/"), { ids, state }),
  uploadImage: (cid: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.form<ImageRef>(path(cid, "questions/images/"), form);
  },
  daily: (cid: number) => http.get<DailySettings>(path(cid, "questions/daily/")),
  updateDaily: (cid: number, input: Partial<Pick<DailySettings, "daily_question" | "daily_at" | "daily_position_ids">>) =>
    http.patch<DailySettings>(path(cid, "questions/daily/"), input),

  quizzes: (cid: number, params: Query = {}) => http.get<QuizRow[]>(path(cid, "quizzes/"), params),
  quiz: (cid: number, id: number) => http.get<Quiz>(path(cid, `quizzes/${id}/`)),
  createQuiz: (cid: number, input: QuizInput) => http.post<Quiz>(path(cid, "quizzes/"), input),
  updateQuiz: (cid: number, id: number, input: QuizInput) => http.patch<Quiz>(path(cid, `quizzes/${id}/`), input),
  deleteQuiz: (cid: number, id: number) => http.delete(path(cid, `quizzes/${id}/`)),
  quizAction: (cid: number, id: number, action: "publish" | "archive" | "restore") => http.post<Quiz>(path(cid, `quizzes/${id}/${action}/`), {}),
  preview: (cid: number, id: number) => http.get<{ questions: PreviewItem[] }>(path(cid, `quizzes/${id}/preview/`)),
  results: (cid: number, id: number, params: Query = {}) => http.get<Results>(path(cid, `quizzes/${id}/results/`), params),
  reset: (cid: number, id: number, member: number) => http.post<{ changed: number }>(path(cid, `quizzes/${id}/reset/`), { member }),
  attempt: (cid: number, id: number) => http.get<OwnerAttempt>(path(cid, `attempts/${id}/`)),

  checks: (cid: number, params: Query = {}) => http.get<Check[]>(path(cid, "checks/"), params),
  createCheck: (cid: number, input: CheckInput) => http.post<Check>(path(cid, "checks/"), input),
  updateCheck: (cid: number, id: number, input: CheckInput) => http.patch<Check>(path(cid, `checks/${id}/`), input),
  checkAction: (cid: number, id: number, action: "pause" | "resume" | "archive") => http.post<Check>(path(cid, `checks/${id}/${action}/`), {}),
  rounds: (cid: number, id: number) => http.get<RoundRow[]>(path(cid, `checks/${id}/rounds/`)),
  round: (cid: number, id: number, round: number) => http.get<RoundDetail>(path(cid, `checks/${id}/rounds/${round}/`)),

  skills: (cid: number, params: Query = {}) => http.get<SkillMatrix>(path(cid, "skills/"), params),
  personSkills: (cid: number, member: number) => http.get<PersonSkills>(path(cid, `skills/${member}/`)),

  suggestions: (cid: number, params: Query = {}) => http.get<Suggestion[]>(path(cid, "suggestions/"), params),
  decide: (cid: number, id: number, action: "accept" | "dismiss") => http.post<Suggestion>(path(cid, `suggestions/${id}/${action}/`), {}),

  drafts: (cid: number) => http.get<DraftJob[]>(path(cid, "drafts/")),
  draft: (cid: number, id: number) => http.get<DraftJobDetail>(path(cid, `drafts/${id}/`)),
  createDraft: (cid: number, input: DraftInput) => http.post<DraftJob>(path(cid, "drafts/"), input),

  tutor: (cid: number) => http.get<Tutor>(path(cid, "tutor/")),
  conversations: (cid: number) => http.get<Conversation[]>(path(cid, "tutor/conversations/")),
  startConversation: (cid: number) => http.post<Conversation>(path(cid, "tutor/conversations/"), {}),
  messages: (cid: number, conversation: number) => http.get<ChatMessage[]>(ownerPath(cid, `ai/conversations/${conversation}/messages/`)),
  ask: (cid: number, conversation: number, text: string, page: string) =>
    http.post<{ turn_id: number }>(ownerPath(cid, `ai/conversations/${conversation}/turns/`), { text, page }),
  turn: (cid: number, turn: number) => http.get<Turn>(ownerPath(cid, `ai/turns/${turn}/`)),

  /** The company's topics (the knowledge base keeps them; every picker shares them). */
  topics: (cid: number) => http.get<TopicOption[]>(ownerPath(cid, "knowledge/topics/")),
  /** Knowledge base pages to write questions from. */
  pages: (cid: number, q: string) => http.get<{ id: number; title: string }[] | Paginated<{ id: number; title: string }>>(ownerPath(cid, "knowledge/pages/"), { q, page_size: 20 }),
};

export const quizKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  of: (cid: number, resource: string, params: Record<string, unknown> = {}) => qk(cid, MODULE, resource, params),
};

function useResource<T>(
  resource: string,
  params: MaybeRefOrGetter<Record<string, unknown>>,
  fetcher: (cid: number, params: Record<string, unknown>, signal: AbortSignal) => Promise<T>,
  options: { enabled?: MaybeRefOrGetter<boolean>; keepPrevious?: boolean; staleTime?: number; refetchInterval?: MaybeRefOrGetter<number | false> } = {},
) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => quizKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
    refetchInterval: computed(() => (options.refetchInterval === undefined ? false : toValue(options.refetchInterval))),
  });
}

export const useQuestions = (params: MaybeRefOrGetter<Query>) =>
  useResource("questions", () => ({ ...toValue(params) }), (cid, p, signal) => quizzesApi.questions(cid, p as Query, signal), { keepPrevious: true });
export const useQuizzes = (params: MaybeRefOrGetter<Query> = {}) => useResource("quizzes", () => ({ ...toValue(params) }), (cid, p) => quizzesApi.quizzes(cid, p as Query));
export const useQuiz = (id: MaybeRefOrGetter<number>) => useResource("quiz", () => ({ id: toValue(id) }), (cid, p) => quizzesApi.quiz(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useResults = (id: MaybeRefOrGetter<number>, params: MaybeRefOrGetter<Query> = {}) =>
  useResource("results", () => ({ id: toValue(id), ...toValue(params) }), (cid, p) => quizzesApi.results(cid, Number(p.id), { branch: p.branch as string | undefined }), {
    enabled: () => toValue(id) > 0,
    keepPrevious: true,
  });
export const useAttempt = (id: MaybeRefOrGetter<number | null>) =>
  useResource("attempt", () => ({ id: toValue(id) }), (cid, p) => quizzesApi.attempt(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useChecks = () => useResource("checks", {}, (cid) => quizzesApi.checks(cid));
export const useRounds = (id: MaybeRefOrGetter<number | null>) => useResource("rounds", () => ({ id: toValue(id) }), (cid, p) => quizzesApi.rounds(cid, Number(p.id)), { enabled: () => !!toValue(id) });
export const useRound = (check: MaybeRefOrGetter<number | null>, round: MaybeRefOrGetter<number | null>) =>
  useResource("round", () => ({ check: toValue(check), round: toValue(round) }), (cid, p) => quizzesApi.round(cid, Number(p.check), Number(p.round)), {
    enabled: () => !!toValue(check) && !!toValue(round),
  });
export const useSkills = (params: MaybeRefOrGetter<Query>) => useResource("skills", () => ({ ...toValue(params) }), (cid, p) => quizzesApi.skills(cid, p as Query), { keepPrevious: true });
export const usePersonSkills = (member: MaybeRefOrGetter<number>) =>
  useResource("person", () => ({ member: toValue(member) }), (cid, p) => quizzesApi.personSkills(cid, Number(p.member)), { enabled: () => toValue(member) > 0 });
export const useSuggestions = (params: MaybeRefOrGetter<Query> = {}) => useResource("suggestions", () => ({ ...toValue(params) }), (cid, p) => quizzesApi.suggestions(cid, p as Query));
export const useDrafts = () => useResource("drafts", {}, (cid) => quizzesApi.drafts(cid));
export const useDraft = (id: MaybeRefOrGetter<number | null>, poll: MaybeRefOrGetter<number | false> = false) =>
  useResource("draft", () => ({ id: toValue(id) }), (cid, p) => quizzesApi.draft(cid, Number(p.id)), { enabled: () => !!toValue(id), refetchInterval: poll, staleTime: 0 });
export const useDaily = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("daily", {}, (cid) => quizzesApi.daily(cid), { enabled });
export const useTutor = () => useResource("tutor", {}, (cid) => quizzesApi.tutor(cid), { staleTime: 30_000 });
export const useConversations = (enabled: MaybeRefOrGetter<boolean> = true) => useResource("conversations", {}, (cid) => quizzesApi.conversations(cid), { enabled });
export const useTopics = () => useResource("topics", {}, (cid) => quizzesApi.topics(cid), { staleTime: 120_000 });

/** Refetch every query of the module and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: quizKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}
