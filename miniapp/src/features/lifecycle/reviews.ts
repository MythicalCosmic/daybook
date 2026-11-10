/**
 * My performance reviews (`/companies/<id>/lifecycle/reviews/…`, backend/apps/lifecycle/review_api.py,
 * PLAN-OWNER §13.4 "Self-review forms and my goals") as react-query hooks, and the plain logic of
 * the answering steps. Hand-written: the generated schema doesn't have them yet. Only my own
 * reviews ever come here; my reviewer's part only once it is published.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";

export type ReviewState = "todo" | "draft" | "sent" | "published";
export type ReviewOutcome = "none" | "raise" | "bonus" | "promotion" | "improvement_plan";
export type OutcomeState = "waiting" | "approved" | "applied" | "rejected";
export type GoalStatus = "open" | "done" | "missed";

export type ReviewAnswer = { rating?: number | null; text?: string };
export type ReviewAnswers = Record<string, ReviewAnswer>;
export type ReviewQuestion = { id: string; kind: "rating" | "text"; text: string; key: string };

export type MyReviewRound = {
  id: number;
  name: string;
  status: "draft" | "self" | "manager" | "closed";
  period_start: string;
  period_end: string;
  self_due_on: string;
};

export type MyReviewRow = {
  id: number;
  round: MyReviewRound;
  state: ReviewState;
  /** The round is open and I haven't sent my answers. */
  can_answer: boolean;
  self_sent_at: string | null;
  published_at: string | null;
  acknowledged_at: string | null;
  /** Published only. */
  rating: number | null;
  outcome: ReviewOutcome | null;
  /** My deadline passed and I haven't answered. */
  late: boolean;
};

export type MyGoal = {
  id: number;
  title: string;
  target: string | null;
  unit: string;
  progress: string | null;
  due_on: string;
  status: GoalStatus;
  note: string;
  closed_at: string | null;
  round?: string;
  review_id?: number;
};

export type MyReviewKpis = {
  start: string;
  end: string;
  tasks: { total: number; on_time: number; late: number; missed: number; on_time_percent: string | null };
  attendance: { scheduled_days: number; attended_days: number; absent_days: number; late_arrivals: number } | null;
  discipline: { records: number };
  learning: { completed: number; open: number; late: number } | null;
};

export type MyReview = MyReviewRow & {
  questions: ReviewQuestion[];
  answers: ReviewAnswers;
  self_saved_at: string | null;
  reviewer: string | null;
  manager_answers: ReviewAnswers | null;
  summary: string | null;
  raise_percent: string | null;
  bonus: { id: number; amount: string; currency: string; status: string; period: string } | null;
  change: { status: OutcomeState | null; effective_on: string | null; position: string | null; pay_before: string | null; pay_after: string | null; currency: string | null } | null;
  goals: MyGoal[];
  kpis: MyReviewKpis | null;
};

export type MyReviews = { open: MyReviewRow[]; past: MyReviewRow[]; goals: MyGoal[] };

export const reviewKeys = {
  list: (company: number) => ["lifecycle", company, "reviews"] as const,
  one: (company: number, id: number) => ["lifecycle", company, "review", id] as const,
};

const base = (company: number) => `/companies/${company}/lifecycle/reviews`;

/** My rounds still open, my published reviews and my open goals. Home, Me and the pages share one copy. */
export function useMyReviews(company: number, enabled = true) {
  return useQuery({ queryKey: reviewKeys.list(company), queryFn: () => api<MyReviews>(`${base(company)}/`), staleTime: 60_000, enabled });
}

export function useMyReview(company: number, id: number) {
  return useQuery({ queryKey: reviewKeys.one(company, id), queryFn: () => api<MyReview>(`${base(company)}/${id}/`), staleTime: 30_000 });
}

/** Every write answers with the whole review: it replaces the copy, and the list refreshes. */
function useReviewWrite<V>(company: number, id: number, run: (variables: V) => Promise<MyReview>, refreshList: boolean) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (review) => {
      client.setQueryData(reviewKeys.one(company, id), review);
      if (refreshList) void client.invalidateQueries({ queryKey: reviewKeys.list(company) });
    },
  });
}

/** My draft, kept as I go (nobody sees it). */
export function useSaveAnswers(company: number, id: number) {
  return useReviewWrite(company, id, (answers: ReviewAnswers) => api<MyReview>(`${base(company)}/${id}/`, { method: "PATCH", json: { answers } }), false);
}

/** I send my answers: every rating given; they can't change after that. */
export function useSendAnswers(company: number, id: number) {
  return useReviewWrite(company, id, (answers: ReviewAnswers) => api<MyReview>(`${base(company)}/${id}/send/`, { json: { answers } }), true);
}

/** "Tanishdim": I have read my published review. */
export function useAcknowledgeReview(company: number, id: number) {
  return useReviewWrite(company, id, () => api<MyReview>(`${base(company)}/${id}/acknowledge/`, { method: "POST" }), true);
}

// — The answering steps —

/** The rating questions still without a rating (sending needs them all). */
export function unrated(questions: ReviewQuestion[], answers: ReviewAnswers): string[] {
  return questions.filter((question) => question.kind === "rating" && !answers[question.id]?.rating).map((question) => question.id);
}

/** How many questions have an answer. */
export function answered(questions: ReviewQuestion[], answers: ReviewAnswers): number {
  return questions.filter((question) => (question.kind === "rating" ? !!answers[question.id]?.rating : !!answers[question.id]?.text?.trim())).length;
}

/** Only the answers that say something (an empty comment isn't sent). */
export function cleanAnswers(answers: ReviewAnswers): ReviewAnswers {
  const found: ReviewAnswers = {};
  for (const [id, answer] of Object.entries(answers)) {
    const text = answer.text?.trim() ?? "";
    if (answer.rating || text) found[id] = { rating: answer.rating ?? null, text };
  }
  return found;
}

/** The first question to show when coming back to a draft: the first without an answer. */
export function resumeStep(questions: ReviewQuestion[], answers: ReviewAnswers): number {
  const index = questions.findIndex((question) => (question.kind === "rating" ? !answers[question.id]?.rating : !answers[question.id]?.text?.trim()));
  return index === -1 ? questions.length : index;
}

/** Things to read on Home and Me: reviews to answer, and published ones I haven't read. */
export function waitingCount(data: MyReviews | undefined): number {
  if (!data) return 0;
  return data.open.filter((row) => row.can_answer).length + data.past.filter((row) => !row.acknowledged_at).length;
}

/**
 * A date or a round's name that never breaks inside "9-noyabr", "3-chorak" or "1 ноября" (a no-break
 * hyphen after a number, a no-break space between a number and a word).
 */
export function noBreak(text: string): string {
  return text.replace(/(\d)-(\p{L})/gu, "$1\u2011$2").replace(/(\d) (\p{L})/gu, "$1\u00a0$2");
}
