/** The wallet's "See all" pages: every payslip, every bonus and fine by month, every advance. */
import { FileText, Gift, HandCoins } from "lucide-react";
import { Fragment } from "react";

import { useI18n } from "../../i18n";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { EmptyState, LoadError, PageHeader, Screen, ScreenSkeleton, SectionHead, Skeleton } from "../../ui";
import { useAdjustments, useAdvances, usePayslips } from "./api";
import { byMonth } from "./lib";
import { AdjustmentRow, AdvanceRow, CapCard, PayslipListRow } from "./parts";
import { monthLabel, useWalletT } from "./text";
import { useWalletNavigation } from "./nav";
import "./wallet.css";

export function PayslipsPage() {
  const t = useWalletT();
  const member = useMember();
  const navigation = useNavigation();
  const go = useWalletNavigation();
  const payslips = usePayslips(member.companyId);
  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.pay")} title={t("payslips.title")} onBack={navigation.pop} />
      {payslips.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : payslips.isError ? (
        <LoadError error={payslips.error} onRetry={() => void payslips.refetch()} onBack={navigation.pop} />
      ) : payslips.data.length === 0 ? (
        <EmptyState icon={FileText} tone="sage" title={t("payslips.empty")} body={t("payslips.emptyBody")} />
      ) : (
        payslips.data.map((row) => <PayslipListRow key={row.id} row={row} onOpen={() => go.page("payslip", { id: row.id })} />)
      )}
    </Screen>
  );
}

export function AdjustmentsPage() {
  const t = useWalletT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const go = useWalletNavigation();
  const adjustments = useAdjustments(member.companyId);
  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.pay")} title={t("adjustments.title")} onBack={navigation.pop} />
      {adjustments.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : adjustments.isError ? (
        <LoadError error={adjustments.error} onRetry={() => void adjustments.refetch()} onBack={navigation.pop} />
      ) : adjustments.data.length === 0 ? (
        <EmptyState icon={Gift} tone="sage" title={t("adjustments.empty")} body={t("adjustments.emptyBody")} />
      ) : (
        byMonth(adjustments.data).map((group) => (
          <Fragment key={group.period}>
            <SectionHead size="small" count={group.rows.length}>
              {monthLabel(group.period, locale)}
            </SectionHead>
            {group.rows.map((row) => (
              <AdjustmentRow key={row.id} row={row} onOpen={() => go.sheet("adjustment", { id: row.id })} />
            ))}
          </Fragment>
        ))
      )}
    </Screen>
  );
}

export function AdvancesPage() {
  const t = useWalletT();
  const member = useMember();
  const navigation = useNavigation();
  const go = useWalletNavigation();
  const advances = useAdvances(member.companyId);
  return (
    <Screen variant="detail">
      <PageHeader kicker={t("me.pay")} title={t("advances.title")} onBack={navigation.pop} />
      {advances.isPending ? (
        <>
          <Skeleton height={150} radius="calc(var(--radius-lg) * 1.15)" />
          <ScreenSkeleton variant="list" rows={2} />
        </>
      ) : advances.isError ? (
        <LoadError error={advances.error} onRetry={() => void advances.refetch()} onBack={navigation.pop} />
      ) : (
        <>
          <CapCard cap={advances.data.cap} onAsk={() => go.sheet("advance")} />
          {advances.data.advances.length === 0 ? (
            <EmptyState compact icon={HandCoins} tone="sage" title={t("advances.empty")} body={t("advances.emptyBody")} />
          ) : (
            advances.data.advances.map((advance) => (
              <AdvanceRow key={advance.id} advance={advance} onOpen={() => go.sheet("advanceInfo", { id: advance.id })} />
            ))
          )}
        </>
      )}
    </Screen>
  );
}
