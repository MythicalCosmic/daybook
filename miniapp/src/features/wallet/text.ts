/** The wallet's translator and the wording helpers its screens share. */
import type { Lang } from "../../i18n";
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { formatMoney } from "../../lib/money";
import { monthYear } from "../../lib/time";
import type { AdjustmentKind, Advance } from "./api";
import { plainNumber, type MetricUnit, type PayslipState, type ProgressCaption } from "./lib";
import { messages } from "./messages";

export type WalletKey = keyof typeof messages.en;
export type WalletT = FeatureTranslate<WalletKey>;

export const useWalletT = (): WalletT => useFeatureT(messages);

/** "2026-10-01" → "Oktabr 2026", "Октябрь 2026 г.", "October 2026". */
export const monthLabel = (period: string, locale: string): string => monthYear(period.slice(0, 7), locale);

export const kindLabel = (t: WalletT, kind: AdjustmentKind | string): string => t(`kind.${kind}` as WalletKey);

export const advanceStatus = (t: WalletT, status: Advance["status"]): string => t(`advance.status.${status}` as WalletKey);

export const payslipStateLabel = (t: WalletT, state: PayslipState): string => t(`state.${state}` as WalletKey);

/** A metric's value in its unit: "93%", "12", "150 soat", "1 250 000 so‘m". */
export function metricText(t: WalletT, unit: MetricUnit, value: string, lang: Lang, currency: string): string {
  switch (unit) {
    case "money":
      return formatMoney(value, currency, lang);
    case "percent":
      return t("unit.percent", { value: plainNumber(value, lang) });
    case "hours":
      return t("unit.hours", { hours: plainNumber(value, lang) });
    case "minutes":
      return t("unit.minutes", { count: Math.round(Number(value) || 0) });
    default:
      return plainNumber(value, lang);
  }
}

/** The line under a rule's bar. */
export function captionText(t: WalletT, caption: ProgressCaption, unit: MetricUnit, lang: Lang, currency: string): string {
  const money = (amount: string) => formatMoney(amount, currency, lang);
  switch (caption.key) {
    case "progress.next":
    case "progress.atMost":
      return t(caption.key, { target: metricText(t, unit, caption.target, lang, currency), amount: money(caption.amount) });
    case "progress.keepLate":
    case "progress.keepLeft":
    case "progress.keepMinutes":
      return t(caption.key, { count: caption.count });
    case "progress.keepLimit":
      return t(caption.key, { limit: metricText(t, unit, caption.limit, lang, currency) });
    case "progress.earned":
      return t(caption.key, { amount: money(caption.amount) });
    case "progress.minTasks":
      return t(caption.key, { min: caption.min, count: caption.count });
    default:
      return t(caption.key);
  }
}
