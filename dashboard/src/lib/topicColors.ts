/**
 * The palette topics and courses are coloured from (docs/PLAN-LEARNING.md §2.5). The backend
 * stores a key (`apps/knowledge/topics.py` COLORS); these are the colours they show as, mid tones
 * that read on both the light and the dark theme. Shared by the knowledge and learning modules.
 */
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
