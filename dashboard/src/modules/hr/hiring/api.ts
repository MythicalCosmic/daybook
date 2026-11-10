/**
 * Hiring's endpoints (`hr/vacancies/`, `hr/applicants/`) as typed functions, and their vue-query
 * helpers. Keys start with `[companyId, "hr"]`, so the `hr.vacancies` and `hr.applicants` pulse
 * keys refresh everything here (the module invalidates on "hr").
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import type { Page } from "@/api/types";
import { useCompanyId } from "@/stores/company";

import type { Applicant, ApplicantDetail, ApplicantParams, PipelineStage, Vacancy, VacancyInput } from "./types";

const MODULE = "hr";
const path = (cid: number, rest: string) => ownerPath(cid, `hr/${rest}`);

/** A board shows a whole vacancy at once (the server allows up to 500 a page). */
export const BOARD_PAGE = 500;

export interface MoveInput {
  stage: PipelineStage;
  message?: string;
  /** Tell them in the bot; left out: for an interview or an offer, or with a message. */
  notify?: boolean | null;
}

export interface RejectInput {
  reason: string;
  message?: string;
  notify?: boolean;
}

export interface HireInput {
  branch_id?: number | null;
  message?: string;
}

export const hiringApi = {
  vacancies: (cid: number, params: { status?: string[]; q?: string } = {}, signal?: AbortSignal) =>
    http.get<Page<Vacancy>>(path(cid, "vacancies/"), { page_size: 100, ...params } as Query, { signal }),
  vacancy: (cid: number, id: number, signal?: AbortSignal) => http.get<Vacancy>(path(cid, `vacancies/${id}/`), undefined, { signal }),
  createVacancy: (cid: number, input: VacancyInput) => http.post<Vacancy>(path(cid, "vacancies/"), input),
  updateVacancy: (cid: number, id: number, input: Partial<VacancyInput>) => http.patch<Vacancy>(path(cid, `vacancies/${id}/`), input),
  removeVacancy: (cid: number, id: number) => http.delete<void>(path(cid, `vacancies/${id}/`)),
  setStatus: (cid: number, id: number, verb: "open" | "pause" | "close") => http.post<Vacancy>(path(cid, `vacancies/${id}/${verb}/`)),

  applicants: (cid: number, params: ApplicantParams, signal?: AbortSignal) => http.get<Page<Applicant>>(path(cid, "applicants/"), params as Query, { signal }),
  applicant: (cid: number, id: number, signal?: AbortSignal) => http.get<ApplicantDetail>(path(cid, `applicants/${id}/`), undefined, { signal }),
  move: (cid: number, id: number, input: MoveInput) => http.post<ApplicantDetail>(path(cid, `applicants/${id}/move/`), input),
  reject: (cid: number, id: number, input: RejectInput) => http.post<ApplicantDetail>(path(cid, `applicants/${id}/reject/`), input),
  hire: (cid: number, id: number, input: HireInput = {}) => http.post<ApplicantDetail>(path(cid, `applicants/${id}/hire/`), input),
  note: (cid: number, id: number, text: string) => http.post<ApplicantDetail>(path(cid, `applicants/${id}/notes/`), { text }),
};

export const hiringKeys = {
  all: (cid: number) => moduleKey(cid, MODULE),
  vacancies: (cid: number) => qk(cid, MODULE, "hiring-vacancies"),
  vacancy: (cid: number, id: number) => qk(cid, MODULE, "hiring-vacancy", { id }),
  applicants: (cid: number, params: ApplicantParams) => qk(cid, MODULE, "hiring-applicants", { ...params }),
  applicant: (cid: number, id: number) => qk(cid, MODULE, "hiring-applicant", { id }),
};

export function useVacancies() {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hiringKeys.vacancies(cid.value)),
    queryFn: async ({ signal }) => (await hiringApi.vacancies(cid.value, {}, signal)).results,
    enabled: computed(() => cid.value > 0),
    staleTime: 15_000,
  });
}

export function useVacancy(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hiringKeys.vacancy(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => hiringApi.vacancy(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 15_000,
  });
}

/** Every applicant of one vacancy, for its board. */
export function useBoard(vacancyId: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  const params = computed<ApplicantParams>(() => ({ vacancy: [toValue(vacancyId) ?? 0], page_size: BOARD_PAGE }));
  return useQuery({
    queryKey: computed(() => hiringKeys.applicants(cid.value, params.value)),
    queryFn: async ({ signal }) => hiringApi.applicants(cid.value, params.value, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(vacancyId)),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
}

export function useApplicant(id: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => hiringKeys.applicant(cid.value, toValue(id) ?? 0)),
    queryFn: ({ signal }) => hiringApi.applicant(cid.value, toValue(id)!, signal),
    enabled: computed(() => cid.value > 0 && !!toValue(id)),
    staleTime: 10_000,
  });
}

/** Refresh hiring (and the people, the sidebar badges and the inbox) once a change settles. */
export function useHiringRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: hiringKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "people"] });
    void client.invalidateQueries({ queryKey: [cid.value, "shell"] });
  };
}

/** A change on the current company that refreshes hiring when it settles. */
export function useHiringMutation<I, O>(run: (cid: number, input: I) => Promise<O>) {
  const cid = useCompanyId();
  const refresh = useHiringRefresh();
  return useMutation({ mutationFn: (input: I) => run(cid.value, input), onSettled: refresh });
}
