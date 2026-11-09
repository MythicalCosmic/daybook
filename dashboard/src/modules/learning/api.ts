/**
 * The learning owner endpoints (courses, lessons, videos, who watched what) as typed functions,
 * and the vue-query helpers the pages use. Keys start with `[companyId, "learning"]`, so the
 * `learning.courses` / `learning.lessons` pulse keys (`invalidates` in index.ts) refresh every
 * query of the module, and switching company never shows another's training.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { http, ownerPath, request, type Query } from "@/api/http";
import { moduleKey, qk } from "@/api/keys";
import { useCompanyId } from "@/stores/company";

import type {
  AssignmentRow,
  Candidate,
  ChunkResult,
  CourseDetail,
  CourseInput,
  CoursePeople,
  CourseRow,
  FileLink,
  LearningSettings,
  LessonDetail,
  LessonInput,
  LessonRow,
  Overview,
  PeopleBucket,
  PeopleGrid,
  PersonPage,
  Pick,
  StepKind,
  Topic,
  Video,
  ViewerState,
  Viewers,
} from "./types";

export const MODULE = "learning";

const path = (cid: number, rest: string) => ownerPath(cid, `learning/${rest}`);

export const learningApi = {
  overview: (cid: number, params: Query = {}) => http.get<Overview>(path(cid, "overview/"), params),

  courses: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<CourseRow[]>(path(cid, "courses/"), params, { signal }),
  course: (cid: number, id: number) => http.get<CourseDetail>(path(cid, `courses/${id}/`)),
  createCourse: (cid: number, input: CourseInput) => http.post<CourseDetail>(path(cid, "courses/"), input),
  updateCourse: (cid: number, id: number, input: CourseInput) => http.patch<CourseDetail>(path(cid, `courses/${id}/`), input),
  courseAction: (cid: number, id: number, action: "publish" | "archive" | "restore") => http.post<CourseDetail>(path(cid, `courses/${id}/${action}/`)),
  addStep: (cid: number, id: number, input: { kind: StepKind; target_id: number; required?: boolean }) =>
    http.post<CourseDetail>(path(cid, `courses/${id}/steps/`), input),
  updateStep: (cid: number, id: number, stepId: number, input: { required: boolean }) => http.patch<CourseDetail>(path(cid, `courses/${id}/steps/${stepId}/`), input),
  removeStep: (cid: number, id: number, stepId: number) => http.delete<CourseDetail>(path(cid, `courses/${id}/steps/${stepId}/`)),
  reorderSteps: (cid: number, id: number, ids: number[]) => http.post<CourseDetail>(path(cid, `courses/${id}/steps/reorder/`), { ids }),
  people: (cid: number, id: number, state?: PeopleBucket | null) => http.get<CoursePeople>(path(cid, `courses/${id}/people/`), { state: state ?? undefined }),
  candidates: (cid: number, id: number, q = "") => http.get<Candidate[]>(path(cid, `courses/${id}/candidates/`), { q: q || undefined }),
  assign: (cid: number, id: number, input: { member_ids: number[]; due_on?: string | null }) => http.post<{ count: number }>(path(cid, `courses/${id}/assign/`), input),
  remind: (cid: number, id: number, memberIds?: number[]) => http.post<{ count: number }>(path(cid, `courses/${id}/remind/`), { member_ids: memberIds ?? null }),

  exempt: (cid: number, id: number, reason: string) => http.post<AssignmentRow>(path(cid, `assignments/${id}/exempt/`), { reason }),
  cancel: (cid: number, id: number) => http.post<AssignmentRow>(path(cid, `assignments/${id}/cancel/`)),
  moveDue: (cid: number, id: number, dueOn: string | null) => http.post<AssignmentRow>(path(cid, `assignments/${id}/due/`), { due_on: dueOn }),
  certificate: (cid: number, id: number) => http.get<FileLink>(path(cid, `assignments/${id}/certificate/`)),

  lessons: (cid: number, params: Query = {}, signal?: AbortSignal) => http.get<LessonRow[]>(path(cid, "lessons/"), params, { signal }),
  lesson: (cid: number, id: number) => http.get<LessonDetail>(path(cid, `lessons/${id}/`)),
  createLesson: (cid: number, input: LessonInput) => http.post<LessonDetail>(path(cid, "lessons/"), input),
  updateLesson: (cid: number, id: number, input: LessonInput) => http.patch<LessonDetail>(path(cid, `lessons/${id}/`), input),
  lessonAction: (cid: number, id: number, action: "publish" | "archive" | "restore") => http.post<LessonDetail>(path(cid, `lessons/${id}/${action}/`)),
  deleteLesson: (cid: number, id: number) => http.delete(path(cid, `lessons/${id}/`)),
  viewers: (cid: number, id: number, state?: ViewerState | null) => http.get<Viewers>(path(cid, `lessons/${id}/viewers/`), { state: state ?? undefined }),

  video: (cid: number, id: number) => http.get<Video>(path(cid, `videos/${id}/`)),
  startUpload: (cid: number, input: { name: string; size: number }) => http.post<Video>(path(cid, "videos/"), input),
  /**
   * One piece of an upload as raw bytes. The shared client sends JSON or forms; a Blob goes in
   * the same body slot (fetch takes either), so the token and its refresh work as for any call.
   */
  chunk: (cid: number, id: number, offset: number, piece: Blob, signal?: AbortSignal) =>
    request<ChunkResult>(path(cid, `videos/${id}/chunk/`), {
      method: "PUT",
      query: { offset },
      form: piece as unknown as FormData,
      headers: { "Content-Type": "application/octet-stream" },
      toast: false,
      signal,
    }),
  finishUpload: (cid: number, id: number) => http.post<Video>(path(cid, `videos/${id}/finish/`)),
  deleteVideo: (cid: number, id: number) => http.delete(path(cid, `videos/${id}/`)),

  grid: (cid: number, params: Query = {}) => http.get<PeopleGrid>(path(cid, "people/"), params),
  person: (cid: number, id: number) => http.get<PersonPage>(path(cid, `people/${id}/`)),
  targets: (cid: number, kind: StepKind, q = "") => http.get<Pick[]>(path(cid, "step-targets/"), { kind, q: q || undefined }),
  settings: (cid: number) => http.get<LearningSettings>(path(cid, "settings/")),
  updateSettings: (cid: number, input: Partial<LearningSettings>) => http.patch<LearningSettings>(path(cid, "settings/"), input),

  /** The knowledge base's topics (shared by pages, lessons and questions). */
  topics: (cid: number) => http.get<Topic[]>(ownerPath(cid, "knowledge/topics/")),
};

export const learningKeys = {
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
    queryKey: computed(() => learningKeys.of(cid.value, resource, toValue(params))),
    queryFn: ({ signal }) => fetcher(cid.value, toValue(params), signal),
    enabled: computed(() => cid.value > 0 && (options.enabled === undefined || toValue(options.enabled))),
    placeholderData: options.keepPrevious ? keepPreviousData : undefined,
    staleTime: options.staleTime ?? 20_000,
    refetchInterval: computed(() => (options.refetchInterval === undefined ? false : toValue(options.refetchInterval))),
  });
}

export const useOverview = (params: MaybeRefOrGetter<Query>) =>
  useResource("overview", () => ({ ...toValue(params) }), (cid, p) => learningApi.overview(cid, p as Query), { keepPrevious: true });
export const useCourses = (params: MaybeRefOrGetter<Query>) =>
  useResource("courses", () => ({ ...toValue(params) }), (cid, p, signal) => learningApi.courses(cid, p as Query, signal), { keepPrevious: true });
export const useCourse = (id: MaybeRefOrGetter<number>) =>
  useResource("course", () => ({ id: toValue(id) }), (cid, p) => learningApi.course(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useCoursePeople = (id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("coursePeople", () => ({ id: toValue(id) }), (cid, p) => learningApi.people(cid, Number(p.id)), { enabled: () => toValue(id) > 0 && toValue(enabled) });
export const useLessons = (params: MaybeRefOrGetter<Query>) =>
  useResource("lessons", () => ({ ...toValue(params) }), (cid, p, signal) => learningApi.lessons(cid, p as Query, signal), { keepPrevious: true });
export const useLesson = (id: MaybeRefOrGetter<number>, refetchInterval: MaybeRefOrGetter<number | false> = false) =>
  useResource("lesson", () => ({ id: toValue(id) }), (cid, p) => learningApi.lesson(cid, Number(p.id)), { enabled: () => toValue(id) > 0, refetchInterval });
export const useViewers = (id: MaybeRefOrGetter<number>, enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("viewers", () => ({ id: toValue(id) }), (cid, p) => learningApi.viewers(cid, Number(p.id)), { enabled: () => toValue(id) > 0 && toValue(enabled) });
export const useGrid = (params: MaybeRefOrGetter<Query>) =>
  useResource("grid", () => ({ ...toValue(params) }), (cid, p) => learningApi.grid(cid, p as Query), { keepPrevious: true });
export const usePerson = (id: MaybeRefOrGetter<number>) =>
  useResource("person", () => ({ id: toValue(id) }), (cid, p) => learningApi.person(cid, Number(p.id)), { enabled: () => toValue(id) > 0 });
export const useLearningSettings = (enabled: MaybeRefOrGetter<boolean> = true) =>
  useResource("settings", {}, (cid) => learningApi.settings(cid), { enabled, staleTime: 60_000 });
export const useTopics = () => useResource("topics", {}, (cid) => learningApi.topics(cid), { staleTime: 60_000 });

/** Refetch every learning query and the sidebar pulse (after a write). */
export function useRefresh() {
  const client = useQueryClient();
  const cid = useCompanyId();
  return () => {
    void client.invalidateQueries({ queryKey: learningKeys.all(cid.value) });
    void client.invalidateQueries({ queryKey: [cid.value, "shell", "pulse"] });
  };
}
