/**
 * The translator of the attendance pages and sheets: their own strings (pageMessages.ts) over the
 * card's (messages.ts), then the app's. Only the lazily loaded screens import this file.
 */
import { defineMessages, useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { messages } from "./messages";
import { pageMessages } from "./pageMessages";
import { duration } from "./text";
import type { CellCode, RequestStatus, SwapStatus } from "./types";

export const allMessages = defineMessages({
  en: { ...messages.en, ...pageMessages.en },
  ru: { ...messages.ru, ...pageMessages.ru },
  uz: { ...messages.uz, ...pageMessages.uz },
});

export type PageKey = keyof typeof allMessages.en;
export type PageT = FeatureTranslate<PageKey>;

export const usePageT = (): PageT => useFeatureT(allMessages);

/** A month's worth of time, short enough for a stat tile: "140 h" from ten hours up, else "8 h 7 min". */
export function hoursText(t: PageT, minutes: number): string {
  return minutes >= 600 ? t("duration.h", { h: Math.round(minutes / 60) }) : duration(t, minutes);
}

export const codeLabel = (t: PageT, code: CellCode) => t(`code.${code}` as PageKey);
export const requestStatusLabel = (t: PageT, status: RequestStatus) => t(`status.${status}` as PageKey);
export const swapStatusLabel = (t: PageT, status: SwapStatus) => t(`swapStatus.${status}` as PageKey);

/** "October 2026" / "2026-yil oktabr" for "2026-10". */
export function monthTitle(t: PageT, month: string): string {
  const [year, number] = month.split("-").map(Number);
  return t("month.title", { month: t(`month.${number}` as PageKey), year });
}
