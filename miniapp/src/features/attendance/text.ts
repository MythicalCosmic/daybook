/** The feature's translator and the wording helpers every attendance screen shares. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { LocationFailure } from "../../lib/location";
import { hoursMinutes } from "./lib";
import { messages } from "./messages";
import type { CellCode, RequestStatus, SwapStatus } from "./types";

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

/** A month's worth of time, short enough for a stat tile: "140 h" from ten hours up, else "8 h 7 min". */
export function hoursText(t: T, minutes: number): string {
  return minutes >= 600 ? t("duration.h", { h: Math.round(minutes / 60) }) : duration(t, minutes);
}

export const codeLabel = (t: T, code: CellCode) => t(`code.${code}` as MessageKey);
export const requestStatusLabel = (t: T, status: RequestStatus) => t(`status.${status}` as MessageKey);
export const swapStatusLabel = (t: T, status: SwapStatus) => t(`swapStatus.${status}` as MessageKey);
export const whereLabel = (t: T, reason: LocationFailure) => t(`where.${reason}` as MessageKey);

/** "October 2026" / "2026-yil oktabr" for "2026-10". */
export function monthTitle(t: T, month: string): string {
  const [year, number] = month.split("-").map(Number);
  return t("month.title", { month: t(`month.${number}` as MessageKey), year });
}
