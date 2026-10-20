/** The feature's translator for what Home shows, and the wording helpers the card shares. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { LocationFailure } from "../../lib/location";
import { hoursMinutes } from "./lib";
import { messages } from "./messages";

export type MessageKey = keyof typeof messages.en;
export type T = FeatureTranslate<MessageKey>;

export const useT = (): T => useFeatureT(messages);

/** "8 h 7 min", "45 min", "2 h". */
export function duration(t: T, minutes: number): string {
  const { h, m } = hoursMinutes(minutes);
  if (!h) return t("duration.m", { m });
  if (!m) return t("duration.h", { h });
  return t("duration.hm", { h, m });
}

export const whereLabel = (t: T, reason: LocationFailure) => t(`where.${reason}` as MessageKey);
