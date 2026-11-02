/**
 * One payslip (the bot's `payslip:<id>` link): net pay with where it stands, every line, the
 * month in numbers, the PDF, and "I received it" once it is paid.
 */
import { CheckCheck, CircleCheck, HandCoins } from "lucide-react";

import { useI18n } from "../../i18n";
import { errorText } from "../../lib/actions";
import { toMinor } from "../../lib/money";
import { dayMonthLong } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Banner, BottomBar, Card, ListCard, ListRow, LoadError, MoneyText, PageHeader, PdfLink, Screen, ScreenSkeleton, SectionHead, Stat, StatGrid } from "../../ui";
import type { PageProps } from "../registry";
import { payslipPdf, usePayslip, useReceived, type Payslip } from "./api";
import { payslipState, plainNumber } from "./lib";
import { useWalletT, type WalletKey } from "./text";
import "./wallet.css";

/** 151 minutes → "2,5"; 12119 → "202". */
const hours = (minutes: number, lang: Parameters<typeof plainNumber>[1]) => plainNumber(String(Math.round(minutes / 6) / 10), lang);

export default function PayslipPage({ params }: PageProps) {
  const t = useWalletT();
  const { t: appT, locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const toast = useToast();
  const id = Number(params.id);
  const payslip = usePayslip(member.companyId, id);
  const received = useReceived(member.companyId);

  if (!payslip.data) {
    return (
      <Screen variant="detail">
        {payslip.isError ? (
          <LoadError error={payslip.error} onRetry={() => void payslip.refetch()} onBack={navigation.pop} />
        ) : (
          <ScreenSkeleton variant="payslip" delay={150} />
        )}
      </Screen>
    );
  }

  const data = payslip.data;
  const state = payslipState(data);
  const date = (moment: string) => dayMonthLong(moment, member.timeZone, locale);
  const paidLine = data.paid_at
    ? `${t("payslip.paidOn", { date: date(data.paid_at) })} · ${t(`payslip.method.${data.payout_method}` as WalletKey)}`
    : t("payslip.notPaid");
  const confirm = () => {
    if (received.isPending) return;
    received.mutate(data.id, {
      onSuccess: () => {
        haptic.notify("success");
        toast(t("payslip.receivedToast"), { tone: "success" });
      },
      onError: (error) => {
        haptic.notify("error");
        toast(errorText(error, appT), { tone: "error" });
      },
    });
  };

  return (
    <>
      <Screen variant="detail">
        <PageHeader
          kicker={t("payslip.kicker")}
          title={data.month}
          subtitle={[data.member.position, data.member.home_branch].filter(Boolean).join(" · ") || undefined}
          onBack={navigation.pop}
        />

        <Card className="wal-hero">
          <span className="wal-label">{t("part.net")}</span>
          <MoneyText amount={data.net} currency={data.currency} size="hero" className="wal-hero-amount" />
          <span className="ft-hint">{paidLine}</span>
        </Card>

        {state === "confirm" && <Banner tone="accent" icon={HandCoins} title={t("payslip.confirmAsk")} body={t("payslip.confirmBody")} />}
        {state === "received" && data.received_at && (
          <Banner tone="sage" icon={CircleCheck} title={t("payslip.received", { date: date(data.received_at) })} />
        )}

        <SectionHead size="small">{t("payslip.lines")}</SectionHead>
        <ListCard className="wal-lines">
          {data.lines.map((line) => {
            // What was taken off reads in terracotta; rounding is arithmetic, not a deduction.
            const taken = toMinor(line.amount) < 0n && line.kind !== "rounding";
            return (
              <ListRow
                key={line.id}
                title={line.label}
                value={<MoneyText amount={line.amount} currency={data.currency} tone={taken ? "auto" : "plain"} />}
              />
            );
          })}
          <ListRow className="wal-total" title={t("part.net")} value={<MoneyText amount={data.net} currency={data.currency} />} />
        </ListCard>

        <MonthNumbers data={data} />

        <PdfLink href={payslipPdf(member.companyId, data.id)} title={t("payslip.pdf")} subtitle={t("payslip.pdfSub", { month: data.month })} />
      </Screen>
      {/* Outside the scrolling screen, so it stays at the bottom however far one reads. */}
      {state === "confirm" && (
        <BottomBar primary={{ text: t("payslip.receivedButton"), onClick: confirm, loading: received.isPending, icon: CheckCheck, shine: true }} />
      )}
    </>
  );
}

/** The month in numbers: days paid, hours, and the extras that happened. */
function MonthNumbers({ data }: { data: Payslip }) {
  const t = useWalletT();
  const { lang } = useI18n();
  const days = (value: string) => plainNumber(value, lang);
  const extra = (value: string) => Number(value) > 0;
  return (
    <>
      <SectionHead size="small">{t("payslip.work")}</SectionHead>
      <StatGrid>
        <Stat label={t("payslip.days")} value={t("payslip.daysValue", { paid: days(data.paid_days), scheduled: days(data.scheduled_days) })} />
        <Stat label={t("payslip.hours")} value={t("unit.hours", { hours: hours(data.worked_minutes, lang) })} />
        {data.overtime_minutes > 0 && <Stat label={t("payslip.overtime")} value={t("unit.hours", { hours: hours(data.overtime_minutes, lang) })} />}
        {data.night_minutes > 0 && <Stat label={t("payslip.night")} value={t("unit.hours", { hours: hours(data.night_minutes, lang) })} />}
        <Stat label={t("payslip.late")} value={String(data.late_arrivals)} tone={data.late_arrivals ? "accent" : "plain"} />
        {extra(data.absent_days) && <Stat label={t("payslip.absent")} value={days(data.absent_days)} tone="accent" />}
        {extra(data.paid_leave_days) && <Stat label={t("payslip.leave")} value={days(data.paid_leave_days)} />}
      </StatGrid>
    </>
  );
}
