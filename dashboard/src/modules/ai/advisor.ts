/**
 * The Maslahatchi page's logic, free of Vue and the network so it is tested on its own: the
 * numbers on top of a review (read from its facts, never retyped), the period and the next
 * review in words, which signal a bullet rests on, and when the chat follows the newest message.
 */
import type { Language } from "@/api/types";
import { formatDay, formatInstant, formatRange } from "@/lib/dates";

import type { BriefingFacts, BriefingLatest, BriefingPeriod, BriefingSignal } from "./briefings";

/** vue-i18n's `t` as these functions use it. */
export type Translate = (key: string, named?: Record<string, unknown>) => string;

export interface ReviewKpi {
  id: string;
  label: string;
  value: string | number | null;
  format: "money" | "number" | "percent";
  compact?: boolean;
  /** A ready change: percent, or points with `points`. */
  delta?: number | null;
  points?: boolean;
  inverse?: boolean;
  deltaLabel?: string;
  hint?: string;
  to?: string;
}

function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * The four numbers over a review: revenue, gross margin, profit and cash's lowest point in the next
 * 30 days with the books on; without them the tills' net, receipts and average receipt and the
 * late arrivals. Each change is against the period before.
 */
export function reviewKpis(facts: BriefingFacts, t: Translate, lang: Language): ReviewKpi[] {
  const vs = t("ai.advisor.kpi.vsPrevious");
  const finance = facts.finance;
  if (finance) {
    const margin = finance.gross_margin;
    const low = finance.cash.low_30;
    return [
      { id: "revenue", label: t("ai.advisor.kpi.revenue"), value: finance.revenue.value, format: "money", compact: true, delta: num(finance.revenue.change_pct), deltaLabel: vs, to: finance.url },
      {
        id: "gross_margin",
        label: t("ai.advisor.kpi.grossMargin"),
        value: margin ? num(margin.value) : null,
        format: "percent",
        delta: margin ? num(margin.change_pts) : null,
        points: true,
        deltaLabel: vs,
        to: finance.url,
      },
      { id: "profit", label: t("ai.advisor.kpi.profit"), value: finance.profit.value, format: "money", compact: true, delta: num(finance.profit.change_pct), deltaLabel: vs, to: finance.url },
      {
        id: "cash_low",
        label: t("ai.advisor.kpi.cashLow"),
        value: low.balance,
        format: "money",
        compact: true,
        hint: t("ai.advisor.kpi.cashLowHint", { date: formatDay(low.date, lang, "short") }),
        to: finance.cash.url,
      },
    ];
  }
  const found: ReviewKpi[] = [];
  const sales = facts.sales;
  if (sales) {
    found.push(
      { id: "net", label: t("ai.advisor.kpi.sales"), value: sales.net.value, format: "money", compact: true, delta: num(sales.net.change_pct), deltaLabel: vs, to: sales.url },
      { id: "receipts", label: t("ai.advisor.kpi.receipts"), value: sales.receipts.value, format: "number", to: sales.url },
      { id: "average_receipt", label: t("ai.advisor.kpi.averageReceipt"), value: sales.average_receipt.value, format: "money", compact: true, delta: num(sales.average_receipt.change_pct), deltaLabel: vs, to: sales.url },
    );
  }
  const attendance = facts.attendance;
  if (attendance) {
    found.push({ id: "late", label: t("ai.advisor.kpi.late"), value: attendance.late.value, format: "number", inverse: true, to: attendance.url });
  }
  return found.slice(0, 4);
}

/** "9–15 Nov 2026" for a week, "October 2026" for a month. */
export function periodLabel(period: Pick<BriefingPeriod, "kind" | "start" | "end">, lang: Language): string {
  if (period.kind === "monthly") {
    const month = Number(period.start.slice(5, 7)) - 1;
    const year = period.start.slice(0, 4);
    return `${MONTHS[lang][month]} ${year}`;
  }
  return formatRange({ from: period.start, to: period.end }, lang);
}

const MONTHS: Record<Language, readonly string[]> = {
  uz: ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"],
  ru: ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

/** When the next weekly review goes out, in words ("Mon 23 Nov, 08:00"); null while it is off. */
export function nextReviewText(latest: Pick<BriefingLatest, "next"> | null | undefined, tz: string, lang: Language): string | null {
  const next = latest?.next.weekly;
  return next ? formatInstant(next, tz, lang, "short") : null;
}

/** The signals a review's bullets and suggestions rest on, by key. */
export function signalsByKey(facts: Pick<BriefingFacts, "signals"> | null | undefined): Map<string, BriefingSignal> {
  return new Map((facts?.signals ?? []).map((signal) => [signal.key, signal] as const));
}

/** Who wrote a review, as its badge says it. */
export function writerKey(writtenBy: "ai" | "template"): string {
  return writtenBy === "ai" ? "ai.advisor.writtenByAi" : "ai.advisor.writtenByTemplate";
}

/** What the empty page says: no data in the reader's scope, or the first review still to come. */
export function emptyKey(latest: Pick<BriefingLatest, "has_data" | "next"> | null | undefined): "noData" | "first" | "off" {
  if (!latest?.has_data) return "noData";
  return latest.next.weekly ? "first" : "off";
}

/** The questions the empty chat offers (i18n keys). */
export const ADVISOR_QUESTIONS = ["ai.advisor.chat.try.branch", "ai.advisor.chat.try.money", "ai.advisor.chat.try.best", "ai.advisor.chat.try.rent"] as const;

/** Close enough to the bottom of the chat that a new message scrolls it down (px). */
export const FOLLOW_SLACK = 80;

/** Whether the chat follows a new message: it does unless its reader scrolled up to read. */
export function followsNewest(box: { scrollTop: number; scrollHeight: number; clientHeight: number } | null): boolean {
  if (!box) return true;
  return box.scrollHeight - box.scrollTop - box.clientHeight <= FOLLOW_SLACK;
}
