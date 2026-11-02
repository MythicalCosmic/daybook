/** The record feature's translator and the words its screens share. */
import { MessageSquareWarning, ShieldAlert, TriangleAlert, type LucideIcon } from "lucide-react";

import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { DisciplinaryRecord } from "./api";
import { messages } from "./messages";

export type RecordKey = keyof typeof messages.en;
export type RecordT = FeatureTranslate<RecordKey>;

export const useRecordT = (): RecordT => useFeatureT(messages);

export const kindLabel = (t: RecordT, kind: DisciplinaryRecord["kind"]): string => t(`kind.${kind}` as RecordKey);

export const categoryLabel = (t: RecordT, category: DisciplinaryRecord["category"]): string => t(`category.${category}` as RecordKey);

/** A spoken warning, a written one, a heavier one: a quiet difference, not an alarm. */
export function kindIcon(kind: DisciplinaryRecord["kind"]): LucideIcon {
  if (kind === "verbal_warning") return MessageSquareWarning;
  if (kind === "final_warning" || kind === "reprimand") return ShieldAlert;
  return TriangleAlert;
}
