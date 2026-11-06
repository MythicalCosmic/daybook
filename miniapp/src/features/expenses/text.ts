/** The expenses translator and the wording its screens share: a claim's status, where it was paid from. */
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import type { BadgeTone } from "../../ui";
import type { Claim, ClaimStatus, PaidFrom } from "./api";
import { messages } from "./messages";

export type ExpensesKey = keyof typeof messages.en;
export type ExpensesT = FeatureTranslate<ExpensesKey>;

export const useExpensesT = (): ExpensesT => useFeatureT(messages);

const KNOWN: readonly ClaimStatus[] = ["submitted", "approved", "paid", "rejected", "cancelled"];

/** "Waiting for approval", "Paid back"…; a status this app doesn't know yet keeps the server's words. */
export function statusLabel(t: ExpensesT, claim: Pick<Claim, "status" | "status_label">): string {
  return KNOWN.includes(claim.status) ? t(`status.${claim.status}` as ExpensesKey) : claim.status_label || claim.status;
}

/** Waiting is terracotta (someone has to act), money that is settled sage, the rest grey. */
export function statusTone(status: ClaimStatus): BadgeTone {
  if (status === "submitted") return "accent";
  if (status === "approved" || status === "paid") return "sage";
  return "neutral";
}

export const paidFromLabel = (t: ExpensesT, paidFrom: PaidFrom): string => t(paidFrom === "held_cash" ? "from.held_cash" : "from.own_money");

/** How money from my own pocket comes back: with my pay or in cash. */
export const backLabel = (t: ExpensesT, via: "payroll" | "cash"): string => t(via === "payroll" ? "back.payroll" : "back.cash");
