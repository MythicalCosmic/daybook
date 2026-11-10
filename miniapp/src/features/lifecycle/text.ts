/** The lifecycle feature's translator and the words its screens share. */
import { FileText, KeyRound, ListChecks, MessageSquareWarning, Package, ShieldAlert, TriangleAlert, type LucideIcon } from "lucide-react";

import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { Lang } from "../../i18n";
import { formatMoney } from "../../lib/money";
import type { DisciplinaryRecord, ExitReason, JobPay, MyHandoverItem, Recommend } from "./api";
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

// — My leaving —

/** A handover item's name: its own (equipment, HR's items), else the standard one for its kind. */
export const handoverLabel = (t: RecordT, item: Pick<MyHandoverItem, "kind" | "title">): string =>
  item.title || t(`handover.${item.kind}` as RecordKey);

const HANDOVER_ICONS: Record<MyHandoverItem["kind"], LucideIcon> = {
  equipment: Package,
  tasks: ListChecks,
  keys: KeyRound,
  documents: FileText,
  other: FileText,
};

export const handoverIcon = (kind: MyHandoverItem["kind"]): LucideIcon => HANDOVER_ICONS[kind];

export const exitReasonLabel = (t: RecordT, reason: ExitReason): string => t(`exit.reason.${reason}` as RecordKey);

export const recommendLabel = (t: RecordT, answer: Recommend): string => t(`exit.recommend.${answer}` as RecordKey);

/**
 * "Juma, 20-noyabr" with a no-break hyphen, so a title never wraps between "20-" and "noyabr"
 * (Uzbek dates join the day and the month with a hyphen).
 */
export const keepTogether = (text: string): string => text.replace(/(\d)-(\p{L})/gu, "$1‑$2");

/** "Today", "Tomorrow", "12 days left": how near the last day is (never negative). */
export function daysLeftText(t: RecordT, days: number): string {
  if (days <= 0) return t("agreed.today");
  if (days === 1) return t("agreed.tomorrow");
  return t("agreed.left", { count: days });
}

// — My career —

/** My pay as the person reads it: "6 500 000 so‘m a month" (their own pay: no secret to them). */
export const payText = (t: RecordT, pay: JobPay, lang: Lang): string =>
  t(`pay.${pay.pay_type}` as RecordKey, { amount: formatMoney(pay.amount, pay.currency, lang) });
