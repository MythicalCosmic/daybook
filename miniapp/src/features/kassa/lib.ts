/** Small helpers the Kassa screens share: the translator, durations, and how a shift reads. */
import type { LucideIcon } from "lucide-react";
import { ArchiveRestore, ArrowRightLeft, HandCoins, Landmark, PiggyBank, Vault } from "lucide-react";

import { useI18n, type Lang } from "../../i18n";
import { useFeatureT, type FeatureTranslate } from "../../i18n/feature";
import { compareMoney, formatMoney, isZero, type MoneyFormat } from "../../lib/money";
import { clock, dayMonth, daysFromToday } from "../../lib/time";
import type { BadgeTone } from "../../ui";
import type { Movement, MovementKind, Shift } from "./api";
import { messages } from "./messages";

export type KassaKey = keyof typeof messages.en;
export type KassaT = FeatureTranslate<KassaKey>;

export function useKassaT(): KassaT {
  return useFeatureT(messages);
}

/** Money in the person's language with the company's currency ("1 250 000 so‘m"). */
export function useMoney(currency: string) {
  const { lang } = useI18n();
  return (amount: string | null | undefined, options: MoneyFormat = {}) => formatMoney(amount, currency, lang, options);
}

export function minutesBetween(from: string, to: Date): number {
  return Math.max(0, Math.floor((to.getTime() - new Date(from).getTime()) / 60_000));
}

/** "3 h 12 min", "25 min". */
export function duration(t: KassaT, minutes: number): string {
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? t("time.hm", { hours, minutes: minutes % 60 }) : t("time.m", { minutes });
}

/** "just now", "25 min ago", "3 h ago", then the date. */
export function ago(t: KassaT, moment: string, now: Date, timeZone: string, locale: string): string {
  const minutes = minutesBetween(moment, now);
  if (minutes < 1) return t("ago.now");
  if (minutes < 60) return t("ago.m", { minutes });
  if (minutes < 24 * 60 && daysFromToday(moment, now, timeZone) === 0) return t("ago.h", { hours: Math.floor(minutes / 60) });
  return dayMonth(moment, timeZone, locale);
}

export type Look = { tone: BadgeTone; label: string };

/**
 * How a shift reads to its cashier. The difference is there only once a manager checked the
 * shift (or right away when the company doesn't count blind).
 */
export function shiftLook(shift: Shift, t: KassaT, money: (amount: string) => string): Look {
  if (shift.status === "open") return { tone: "sage", label: t("status.open") };
  if (shift.status === "disputed") return { tone: "accent", label: t("status.disputed") };
  const difference = shift.difference;
  if (difference === null) return { tone: "neutral", label: t("status.waiting") };
  if (isZero(difference)) return { tone: "sage", label: shift.status === "verified" ? t("status.exact") : t("status.exactUnchecked") };
  const amount = money(difference.replace(/^-/, ""));
  return compareMoney(difference, "0") < 0 ? { tone: "accent", label: t("status.short", { amount }) } : { tone: "neutral", label: t("status.over", { amount }) };
}

export const MOVEMENT_ICON: Record<MovementKind, LucideIcon> = {
  payout: HandCoins,
  handover: ArrowRightLeft,
  to_safe: Vault,
  from_safe: ArchiveRestore,
  to_bank: Landmark,
  deposit: PiggyBank,
};

/** Cash leaving the till reads with a minus. */
export const leavesTill = (kind: MovementKind) => kind !== "from_safe" && kind !== "deposit";

export function movementTitle(movement: Movement, t: KassaT): string {
  switch (movement.kind) {
    case "payout":
      return movement.reason || movement.category?.name || t("move.payout");
    case "handover":
      return t("move.handoverTo", { name: movement.receiver?.name ?? "" });
    case "to_safe":
      return t("move.toSafe");
    case "from_safe":
      return t("move.fromSafe");
    case "to_bank":
      return t("move.toBank");
    case "deposit":
      return t("move.deposit");
  }
}

/** The line under a movement: when, what for, and where a handover stands. */
export function movementMeta(movement: Movement, t: KassaT, timeZone: string, locale: string): { text: string; alert: boolean } {
  const at = clock(movement.created_at, timeZone, locale);
  if (movement.status === "void") return { text: `${at} · ${t("move.voided")}`, alert: false };
  if (movement.kind === "handover") {
    const name = movement.receiver?.name ?? "";
    if (movement.status === "pending") return { text: `${at} · ${t("move.waiting", { name })}`, alert: true };
    if (movement.status === "declined") {
      return { text: movement.decline_reason ? t("move.declined", { reason: movement.decline_reason }) : t("move.declinedNoReason"), alert: true };
    }
    return { text: `${at} · ${t("move.confirmed", { time: movement.confirmed_at ? clock(movement.confirmed_at, timeZone, locale) : at })}`, alert: false };
  }
  // A payout's title is its reason (or its category when there is none); others show the note.
  const extra = movement.kind === "payout" ? (movement.reason ? movement.category?.name : null) : movement.reason;
  return { text: extra ? `${at} · ${extra}` : at, alert: false };
}

// Chromium may ship without Uzbek month names ("M10 2026"), as lib/time.ts notes.
const UZ_MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"];

/** "October 2026", "Октябрь 2026 г.", "Oktabr 2026" for "2026-10". */
export function monthYear(month: string, locale: string): string {
  const [year, number] = month.split("-").map(Number);
  if (locale.startsWith("uz")) return `${UZ_MONTHS[number - 1]} ${year}`;
  const text = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, number - 1, 15)));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Digits only, for counters typed into plain inputs. */
export const digits = (value: string, max = 6) => value.replace(/\D/g, "").slice(0, max);

export type { Lang };
