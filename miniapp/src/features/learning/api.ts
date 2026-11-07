/**
 * The learning endpoints of the mini app (`/api/v1/companies/{id}/learning/…`, docs/PLAN-LEARNING.md
 * §13) as react-query hooks. Progress reports, saved answers and page views go through the retry
 * queue (`queue.ts`); everything else is a plain request. The whole module answers 404 while the
 * company has `learning` off: the feature is hidden then, and the cards render nothing on errors.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { send } from "./queue";
import type {
  Answer,
  AssignmentCard,
  AttemptPlay,
  AttemptResult,
  AttemptView,
  CheckEntry,
  CourseDetail,
  DailyResult,
  DailyView,
  LearningHome,
  LessonDetail,
  PageViewReport,
  ProgressAnswer,
  ProgressReport,
  QuizDetail,
} from "./types";

const base = (company: number) => `/companies/${company}/learning`;

export const learningKeys = {
  all: (company: number) => ["learning", company] as const,
  home: (company: number) => ["learning", company, "home"] as const,
  course: (company: number, id: number) => ["learning", company, "course", id] as const,
  lesson: (company: number, id: number, course: number | null) => ["learning", company, "lesson", id, course] as const,
  quiz: (company: number, id: number, assignment: number | null, entry: number | null) => ["learning", company, "quiz", id, assignment, entry] as const,
  quizzes: (company: number, id: number) => ["learning", company, "quiz", id] as const,
  attempt: (company: number, id: number) => ["learning", company, "attempt", id] as const,
  daily: (company: number) => ["learning", company, "daily"] as const,
  checks: (company: number) => ["learning", company, "checks"] as const,
};

/** Whether an attempt is still being answered (its questions come with it) or over (a result). */
export function isPlay(view: AttemptView | undefined): view is AttemptPlay {
  if (!view) return false;
  if ("state" in view && view.state !== "in_progress") return false;
  return "questions" in view && Array.isArray(view.questions);
}

/** `?a=1&b=2` from the values that are set. */
function query(params: Record<string, number | null | undefined>): string {
  const pairs = Object.entries(params).filter(([, value]) => value !== null && value !== undefined && value !== 0);
  return pairs.length ? `?${pairs.map(([name, value]) => `${name}=${value}`).join("&")}` : "";
}

// — Q1: courses and lessons —

export function useLearningHome(company: number, enabled = true) {
  return useQuery({ queryKey: learningKeys.home(company), queryFn: () => api<LearningHome>(`${base(company)}/`), enabled, staleTime: 30_000 });
}

export function useCourse(company: number, id: number) {
  return useQuery({ queryKey: learningKeys.course(company, id), queryFn: () => api<CourseDetail>(`${base(company)}/courses/${id}/`), enabled: id > 0 });
}

/** "Start the course": an optional course of the person's audience becomes theirs. */
export function useStartCourse(company: number, id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<AssignmentCard>(`${base(company)}/courses/${id}/start/`, { method: "POST" }),
    onSuccess: (assignment) => {
      const key = learningKeys.course(company, id);
      const before = client.getQueryData<CourseDetail>(key);
      if (before) client.setQueryData<CourseDetail>(key, { ...before, assignment, can_start: false });
    },
    onSettled: () => client.invalidateQueries({ queryKey: learningKeys.all(company) }),
  });
}

export function useLesson(company: number, id: number, course: number | null) {
  return useQuery({
    queryKey: learningKeys.lesson(company, id, course),
    queryFn: () => api<LessonDetail>(`${base(company)}/lessons/${id}/${query({ course })}`),
    enabled: id > 0,
    // A signed video link lasts 6 h; a page left open longer asks again when the video fails.
    staleTime: 5 * 60_000,
  });
}

/** One progress report through the queue (kept and sent again when the signal drops). */
export function reportProgress(company: number, lesson: number, report: ProgressReport): Promise<ProgressAnswer> {
  return send<ProgressAnswer>({
    kind: "progress",
    key: `progress:${lesson}:${report.session}`,
    path: `${base(company)}/lessons/${lesson}/progress/`,
    method: "POST",
    body: report,
  });
}

/** A certificate's fresh link: signed links expire, so the one in a cached list may be stale. */
export async function certificateLink(client: QueryClient, company: number, assignment: number): Promise<string> {
  const home = await client.fetchQuery({ queryKey: learningKeys.home(company), queryFn: () => api<LearningHome>(`${base(company)}/`), staleTime: 60_000 });
  const card = [...home.done, ...home.todo].find((row) => row.id === assignment);
  if (!card?.certificate_url) throw new Error("certificate missing");
  return card.certificate_url;
}

// — knowledge page views (Q1, always on) —

export function reportPageView(company: number, page: number, report: PageViewReport): Promise<void> {
  return send<void>({ kind: "view", key: `view:${page}:${report.session}`, path: `/companies/${company}/knowledge/pages/${page}/view/`, method: "POST", body: report });
}

// — Q2: quizzes, attempts, the question of the day, checks —

export function useQuiz(company: number, id: number, context: { assignment?: number | null; entry?: number | null } = {}) {
  const assignment = context.assignment ?? null;
  const entry = context.entry ?? null;
  return useQuery({
    queryKey: learningKeys.quiz(company, id, assignment, entry),
    queryFn: () => api<QuizDetail>(`${base(company)}/quizzes/${id}/${query({ assignment, entry })}`),
    enabled: id > 0,
  });
}

/** Start an attempt (or get the one in progress back); the player opens it from the cache. */
export function useStartAttempt(company: number, quiz: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (context: { assignment?: number | null; entry?: number | null }) => {
      const json: Record<string, number> = {};
      if (context.assignment) json.assignment = context.assignment;
      if (context.entry) json.entry = context.entry;
      return api<AttemptPlay>(`${base(company)}/quizzes/${quiz}/attempts/`, { method: "POST", json });
    },
    onSuccess: (play) => {
      client.setQueryData(learningKeys.attempt(company, play.id), play);
      void client.invalidateQueries({ queryKey: learningKeys.quizzes(company, quiz) });
    },
  });
}

export function useAttempt(company: number, id: number) {
  return useQuery({
    queryKey: learningKeys.attempt(company, id),
    queryFn: () => api<AttemptView>(`${base(company)}/attempts/${id}/`),
    enabled: id > 0,
    // The player keeps its own answers while it runs: a refetch must not undo a tap in flight.
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}

/** Autosave one answer (the newest of a question wins; kept while the signal is down); null takes it back. */
export function saveAnswer(company: number, attempt: number, question: number, answer: Answer | null): Promise<void> {
  return send<void>({
    kind: "answer",
    key: `answer:${attempt}:${question}`,
    path: `${base(company)}/attempts/${attempt}/answers/`,
    method: "PUT",
    body: { question, answer },
  });
}

/** The prefix of an attempt's answer saves in the queue (to wait for them before finishing). */
export const answersOf = (attempt: number) => `answer:${attempt}:`;

export function finishAttempt(company: number, attempt: number): Promise<AttemptResult> {
  return api<AttemptResult>(`${base(company)}/attempts/${attempt}/finish/`, { method: "POST" });
}

/** After an attempt is over: the course, the home lists and the quiz's own numbers change. */
export function afterAttempt(client: QueryClient, company: number, attempt: number, result: AttemptResult, quiz?: number | null): void {
  client.setQueryData(learningKeys.attempt(company, attempt), result);
  void client.invalidateQueries({ queryKey: learningKeys.home(company) });
  void client.invalidateQueries({ queryKey: learningKeys.checks(company) });
  void client.invalidateQueries({ predicate: (entry) => entry.queryKey[0] === "learning" && entry.queryKey[1] === company && entry.queryKey[2] === "course" });
  if (quiz) void client.invalidateQueries({ queryKey: learningKeys.quizzes(company, quiz) });
}

export function useDaily(company: number, enabled = true) {
  return useQuery({ queryKey: learningKeys.daily(company), queryFn: () => api<DailyView>(`${base(company)}/daily/`), enabled, staleTime: 60_000 });
}

/** Answer the question of the day: the card shows the result from the answer itself. */
export function useAnswerDaily(company: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: number; answer: Answer }) => api<DailyResult>(`${base(company)}/daily/${id}/answer/`, { method: "POST", json: { answer } }),
    onSuccess: (result, { id, answer }) => {
      const key = learningKeys.daily(company);
      const before = client.getQueryData<DailyView>(key);
      if (before?.daily && before.daily.id === id) {
        client.setQueryData<DailyView>(key, {
          streak: result.streak ?? before.streak,
          daily: { ...before.daily, answered: true, correct: result.correct, answer, right_answer: result.right_answer, explanation: result.explanation },
        });
      }
    },
  });
}

export function useChecks(company: number, enabled = true) {
  return useQuery({ queryKey: learningKeys.checks(company), queryFn: () => api<CheckEntry[]>(`${base(company)}/checks/`), enabled, staleTime: 60_000 });
}
