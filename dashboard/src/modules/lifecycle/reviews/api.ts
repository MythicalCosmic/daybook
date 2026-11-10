/**
 * The performance review endpoints (`lifecycle/review-rounds/…`, `lifecycle/reviews/…`,
 * `lifecycle/review-goals/…`) as typed functions and vue-query helpers. Keys start with
 * `[companyId, "lifecycle"]`, so the `lifecycle.reviews` pulse refreshes them with the rest of the
 * module; a decision on a raise or a bonus also refreshes job changes and payroll.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import { MODULE } from "../api";
import type { CareerReview, Goal, ManagerInput, Preview, Question, Results, Review, ReviewRow, Round, RoundInput, RoundStatus, RoundUpdate, RowParams } from "./types";

const path = (cid: number, rest: string) => ownerPath(cid, `lifecycle/${rest}`);

export const reviewsApi = {
  rounds: (cid: number, status?: RoundStatus[], signal?: AbortSignal) => http.get<Round[]>(path(cid, "review-rounds/"), status?.length ? { status } : undefined, { signal }),
  round: (cid: number, id: number, signal?: AbortSignal) => http.get<Round>(path(cid, `review-rounds/${id}/`), undefined, { signal }),
  template: (cid: number, signal?: AbortSignal) => http.get<Question[]>(path(cid, "review-rounds/template/"), undefined, { signal }),
  preview: (cid: number, params: { position?: number[]; branch?: number[]; period_end?: string }, signal?: AbortSignal) =>
    http.get<Preview>(path(cid, "review-rounds/preview/"), params as Query, { signal }),
  createRound: (cid: number, input: RoundInput) => http.post<Round>(path(cid, "review-rounds/"), input),
  updateRound: (cid: number, id: number, input: RoundUpdate) => http.patch<Round>(path(cid, `review-rounds/${id}/`), input),
  deleteRound: (cid: number, id: number) => http.delete<void>(path(cid, `review-rounds/${id}/`)),
  openRound: (cid: number, id: number) => http.post<Round>(path(cid, `review-rounds/${id}/open/`)),
  advanceRound: (cid: number, id: number) => http.post<Round>(path(cid, `review-rounds/${id}/advance/`)),
  closeRound: (cid: number, id: number) => http.post<Round>(path(cid, `review-rounds/${id}/close/`)),
  remind: (cid: number, id: number) => http.post<{ people: number; reviewers: number }>(path(cid, `review-rounds/${id}/remind/`)),
  rows: (cid: number, id: number, params: RowParams, signal?: AbortSignal) => http.get<ReviewRow[]>(path(cid, `review-rounds/${id}/reviews/`), params as Query, { signal }),
  results: (cid: number, id: number, signal?: AbortSignal) => http.get<Results>(path(cid, `review-rounds/${id}/results/`), undefined, { signal }),

  review: (cid: number, id: number, signal?: AbortSignal) => http.get<Review>(path(cid, `reviews/${id}/`), undefined, { signal }),
  saveReview: (cid: number, id: number, input: ManagerInput) => http.patch<Review>(path(cid, `reviews/${id}/`), input),
  publish: (cid: number, id: number) => http.post<Review>(path(cid, `reviews/${id}/publish/`)),
  reassign: (cid: number, id: number, reviewerId: number) => http.post<ReviewRow>(path(cid, `reviews/${id}/reviewer/`), { reviewer_id: reviewerId }),
  remove: (cid: number, id: number) => http.delete<void>(path(cid, `reviews/${id}/`)),
  updateGoal: (cid: number, id: number, input: { progress?: string | null; status?: Goal["status"]; note?: string }) => http.patch<Goal>(path(cid, `review-goals/${id}/`), input),
  personReviews: (cid: number, memberId: number, signal?: AbortSignal) => http.get<CareerReview[]>(path(cid, `people/${memberId}/reviews/`), undefined, { signal }),
};

export const reviewKeys = {
  rounds: (cid: number, status?: RoundStatus[]) => qk(cid, MODULE, "review-rounds", { status: status ?? [] }),
  round: (cid: number, id: number) => qk(cid, MODULE, "review-round", { id }),
  template: (cid: number) => qk(cid, MODULE, "review-template"),
  preview: (cid: number, params: { position?: number[]; branch?: number[]; period_end?: string }) => qk(cid, MODULE, "review-preview", { ...params }),
  rows: (cid: number, id: number, params: RowParams) => qk(cid, MODULE, "review-rows", { id, ...params }),
  results: (cid: number, id: number) => qk(cid, MODULE, "review-results", { id }),
  review: (cid: number, id: number) => qk(cid, MODULE, "review", { id }),
  person: (cid: number, memberId: number) => qk(cid, MODULE, "review-person", { memberId }),
};

export function useRounds(status?: MaybeRefOrGetter<RoundStatus[] | undefined>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.rounds(cid.value, toValue(status))),
    queryFn: ({ signal }) => reviewsApi.rounds(cid.value, toValue(status), signal),
    enabled: computed(() => cid.value > 0),
    staleTime: 15_000,
  });
}

export function useRound(id: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.round(cid.value, toValue(id))),
    queryFn: ({ signal }) => reviewsApi.round(cid.value, toValue(id), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    staleTime: 10_000,
  });
}

export function useTemplate(enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.template(cid.value)),
    queryFn: ({ signal }) => reviewsApi.template(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    staleTime: 10 * 60_000,
  });
}

export function usePreview(params: MaybeRefOrGetter<{ position?: number[]; branch?: number[]; period_end?: string }>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.preview(cid.value, toValue(params))),
    queryFn: ({ signal }) => reviewsApi.preview(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useRows(id: MaybeRefOrGetter<number>, params: MaybeRefOrGetter<RowParams>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.rows(cid.value, toValue(id), toValue(params))),
    queryFn: ({ signal }) => reviewsApi.rows(cid.value, toValue(id), toValue(params), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}

export function useResults(id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.results(cid.value, toValue(id))),
    queryFn: ({ signal }) => reviewsApi.results(cid.value, toValue(id), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0 && toValue(enabled)),
    staleTime: 15_000,
  });
}

export function useReview(id: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.review(cid.value, toValue(id))),
    queryFn: ({ signal }) => reviewsApi.review(cid.value, toValue(id), signal),
    enabled: computed(() => cid.value > 0 && toValue(id) > 0),
    staleTime: 10_000,
  });
}

export function usePersonReviews(memberId: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => reviewKeys.person(cid.value, toValue(memberId))),
    queryFn: ({ signal }) => reviewsApi.personReviews(cid.value, toValue(memberId), signal),
    enabled: computed(() => cid.value > 0 && toValue(memberId) > 0 && toValue(enabled)),
    staleTime: 30_000,
  });
}

/** Reviews, job changes (a raise or a promotion), payroll (a bonus) and the shell's badges. */
export function useReviewRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: [cid.value, MODULE] });
    void client.invalidateQueries({ queryKey: [cid.value, "payroll"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
  };
}

export function useReviewMutation<I, O>(run: (cid: number, input: I) => Promise<O>, options: { refresh?: boolean } = {}) {
  const cid = useCompanyId();
  const refresh = useReviewRefresh();
  return useMutation({ mutationFn: (input: I) => run(cid.value, input), onSettled: options.refresh === false ? undefined : refresh });
}

/** Keep the reviewer's draft as they type: the saved review replaces the cached one, nothing else reloads. */
export function useSaveReview(id: MaybeRefOrGetter<number>) {
  const cid = useCompanyId();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ManagerInput) => reviewsApi.saveReview(cid.value, toValue(id), input),
    onSuccess: (review) => client.setQueryData(reviewKeys.review(cid.value, review.id), review),
  });
}
