/**
 * Topics (docs/PLAN-LEARNING.md §2.5): the subjects pages, lessons and questions are about, and
 * their API. Their colours are the shared palette (`@/lib/topicColors`).
 */
import { http, ownerPath } from "@/api/http";

export { TOPIC_COLOR_KEYS, TOPIC_COLORS, topicColor, type TopicColor } from "@/lib/topicColors";

export interface Topic {
  id: number;
  name: string;
  color: string;
  description: string;
  position: number;
  archived: boolean;
  page_count: number;
  lesson_count: number;
  question_count: number;
}

const path = (cid: number, rest = "") => ownerPath(cid, `knowledge/topics/${rest}`);

export const topicsApi = {
  list: (cid: number, archived = false) => http.get<Topic[]>(path(cid), { archived: archived || undefined }),
  create: (cid: number, input: { name: string; color?: string; description?: string }) => http.post<Topic>(path(cid), input),
  update: (cid: number, id: number, input: { name?: string; color?: string; description?: string }) => http.patch<Topic>(path(cid, `${id}/`), input),
  archive: (cid: number, id: number) => http.post<Topic>(path(cid, `${id}/archive/`)),
  restore: (cid: number, id: number) => http.post<Topic>(path(cid, `${id}/restore/`)),
  reorder: (cid: number, ids: number[]) => http.post(path(cid, "reorder/"), { ids }),
  pharmacy: (cid: number) => http.post<Topic[]>(path(cid, "pharmacy/")),
};
