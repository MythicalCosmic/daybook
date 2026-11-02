/**
 * What the wallet puts on Home and Me: the month so far at Home's end ("Bu oy: 3 450 000 so‘m
 * hozircha"), a card for a new payslip or pay to confirm, the Me row's amount and bubble, and
 * whether the (+) sheet offers an advance.
 */
import { FileText, HandCoins, Wallet } from "lucide-react";

import { useI18n } from "../../i18n";
import { compareMoney, formatMoney } from "../../lib/money";
import { Banner } from "../../ui";
import type { MeItemStatus, SlotProps } from "../registry";
import { useAdvances, useEarnings, usePayslips } from "./api";
import { homePay, payslipsToSee, payslipToAsk } from "./lib";
import { useWalletNavigation } from "./nav";
import { monthLabel, useWalletT } from "./text";

/** Home's overview of the month; nothing until the numbers come, or without a pay setup. */
export function MonthCard({ member }: SlotProps) {
  const t = useWalletT();
  const { lang } = useI18n();
  const go = useWalletNavigation();
  const earnings = useEarnings(member.companyId);
  const pay = homePay(earnings.data);
  if (!pay) return null;
  const money = (amount: string) => formatMoney(amount, pay.currency, lang);
  return (
    <Banner
      size="lg"
      iconTone="sage"
      icon={Wallet}
      title={t("home.month", { amount: money(pay.amount) })}
      body={pay.estimate ? t("home.estimate", { amount: money(pay.estimate) }) : undefined}
      wrap
      onClick={() => go.page("home")}
    />
  );
}

/** A payslip that asks something: pay to confirm ("I received it") first, else a new one to open. */
export function PayslipCard({ member }: SlotProps) {
  const t = useWalletT();
  const { lang, locale } = useI18n();
  const go = useWalletNavigation();
  const payslips = usePayslips(member.companyId);
  const ask = payslipToAsk(payslips.data);
  if (!ask) return null;
  const month = monthLabel(ask.row.period, locale);
  return (
    <Banner
      size="lg"
      iconTone="accent"
      icon={ask.state === "confirm" ? HandCoins : FileText}
      title={t(ask.state === "confirm" ? "home.paid" : "home.new", { month })}
      body={ask.state === "confirm" ? t("home.paidBody") : t("home.newBody", { amount: formatMoney(ask.row.net, ask.row.currency, lang) })}
      wrap
      onClick={() => go.page("payslip", { id: ask.row.id })}
    />
  );
}

/** Me → My pay: this month so far, short, and a bubble for payslips to open or confirm. */
export function useMeStatus({ member }: SlotProps): MeItemStatus {
  const { lang } = useI18n();
  const earnings = useEarnings(member.companyId);
  const payslips = usePayslips(member.companyId);
  const pay = homePay(earnings.data);
  return {
    value: pay ? formatMoney(pay.amount, pay.currency, lang, { compact: true }) : undefined,
    badge: payslipsToSee(payslips.data) || null,
  };
}

/** The (+) sheet offers an advance only while there is room under the cap. */
export function useCanAskAdvance({ member }: SlotProps): boolean {
  const advances = useAdvances(member.companyId);
  const cap = advances.data?.cap;
  return Boolean(cap && compareMoney(cap.available, "0") > 0);
}
