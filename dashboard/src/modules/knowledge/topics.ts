/**
 * Topics (docs/PLAN-LEARNING.md §2.5): the subjects pages, lessons and questions are about. The
 * backend stores a palette key (`apps/knowledge/topics.py` COLORS); these are the colours they
 * show as, mid tones that read on both the light and the dark theme.
 */
import { http, ownerPath } from "@/api/http";

export const TOPIC_COLORS = {
  gray: "#8b8d98",
  red: "#e5484d",
  orange: "#f76b15",
  amber: "#e2a336",
  green: "#30a46c",
  teal: "#12a594",
  sky: "#3aa8d8",
  blue: "#3e63dd",
  indigo: "#5b5bd6",
  violet: "#8e4ec6",
  pink: "#d6409f",
} as const;

export type TopicColor = keyof typeof TOPIC_COLORS;

export const TOPIC_COLOR_KEYS = Object.keys(TOPIC_COLORS) as TopicColor[];

/** The CSS colour of a palette key ("" and unknown keys: the neutral grey). */
export function topicColor(key: string | null | undefined): string {
  return TOPIC_COLORS[(key as TopicColor) || "gray"] ?? TOPIC_COLORS.gray;
}

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
