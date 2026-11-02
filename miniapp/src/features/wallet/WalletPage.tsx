/**
 * "Maoshim" (Me → My pay, the bot's "Open my pay"): this month so far with its parts, the bonus
 * rules' progress, then my payslips, bonuses and fines, and advances, each with "See all".
 *
 * Someone without a pay setup sees why there is no month, and only the sections that have
 * something (an old payslip); a page whose month didn't load says so once, not per section.
 */
import { Hourglass, Wallet } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useI18n } from "../../i18n";
import { formatMoney } from "../../lib/money";
import { dayMonthLong } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Banner, Card, EmptyState, ListCard, ListRow, LoadError, MoneyText, PageHeader, Screen, SectionHead, Segmented, Skeleton, SkeletonList } from "../../ui";
import { useAdjustments, useAdvances, useEarnings, usePayslips, type Earnings } from "./api";
import { homePay, isOpenAdvance, partRows } from "./lib";
import { useWalletNavigation } from "./nav";
import { AdjustmentRow, AdvanceRow, CapCard, PayslipListRow, RuleCard } from "./parts";
import { monthLabel, useWalletT, type WalletKey } from "./text";
import "./wallet.css";

/** How many rows each section shows before "See all". */
const PREVIEW = 3;

/** A section's rows once they are here: a placeholder while they come, one line when there are none. */
function SectionBody<T>({
  query,
  empty,
  children,
}: {
  query: { data: T[] | undefined; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  empty: ReactNode;
  children: (rows: T[]) => ReactNode;
}) {
  if (query.isPending) return <SkeletonList count={2} />;
  if (!query.data) return <LoadError compact error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data.length) return <p className="wal-quiet">{empty}</p>;
  return <>{children(query.data)}</>;
}

export default function WalletPage() {
  const t = useWalletT();
  const member = useMember();
  const navigation = useNavigation();
  const go = useWalletNavigation();
  const company = member.companyId;
  const earnings = useEarnings(company);
  const payslips = usePayslips(company);
  const adjustments = useAdjustments(company);
  const advances = useAdvances(company);
  const header = <PageHeader kicker={member.company.name} title={t("me.pay")} onBack={navigation.pop} />;

  // Without the month there is no page to speak of: one message and one Try again for all of it.
  if (earnings.isError && !earnings.data) {
    const retry = () => [earnings, payslips, adjustments, advances].forEach((query) => query.isError && void query.refetch());
    return (
      <Screen variant="detail">
        {header}
        <LoadError error={earnings.error} onRetry={retry} onBack={navigation.pop} />
      </Screen>
    );
  }

  const setUp = earnings.data?.has_pay_setup ?? true;
  const slips = payslips.data ?? [];
  const rows = adjustments.data ?? [];
  const advanceList = advances.data?.advances ?? [];
  // Without a pay setup a section shows only when it has something from before.
  const show = (count: number) => setUp || count > 0;

  return (
    <Screen variant="detail">
      {header}

      <MonthBlock data={earnings.data} onProposed={() => go.page("adjustments")} />

      {earnings.data && earnings.data.progress.length > 0 && (
        <>
          <SectionHead>{t("rules.title")}</SectionHead>
          {earnings.data.progress.map((row) => (
            <RuleCard key={row.rule} row={row} currency={earnings.data.currency} />
          ))}
        </>
      )}

      {show(slips.length) && (
        <>
          <SectionHead action={slips.length > PREVIEW ? { label: t("all"), onClick: () => go.page("payslips") } : undefined}>{t("payslips.title")}</SectionHead>
          <SectionBody query={payslips} empty={t("payslips.emptyBody")}>
            {(list) => list.slice(0, PREVIEW).map((row) => <PayslipListRow key={row.id} row={row} onOpen={() => go.page("payslip", { id: row.id })} />)}
          </SectionBody>
        </>
      )}

      {show(rows.length) && (
        <>
          <SectionHead action={rows.length > PREVIEW ? { label: t("all"), onClick: () => go.page("adjustments") } : undefined}>{t("adjustments.title")}</SectionHead>
          <SectionBody query={adjustments} empty={t("adjustments.emptyBody")}>
            {(list) => list.slice(0, PREVIEW).map((row) => <AdjustmentRow key={row.id} row={row} onOpen={() => go.sheet("adjustment", { id: row.id })} />)}
          </SectionBody>
        </>
      )}

      {show(advanceList.length) && (
        <>
          <SectionHead action={advanceList.length > 0 ? { label: t("all"), onClick: () => go.page("advances") } : undefined}>{t("advances.title")}</SectionHead>
          {advances.isPending ? (
            <Skeleton height={150} radius="calc(var(--radius-lg) * 1.15)" />
          ) : !advances.data ? (
            <LoadError compact error={advances.error} onRetry={() => void advances.refetch()} />
          ) : (
            <>
              {setUp && <CapCard cap={advances.data.cap} onAsk={() => go.sheet("advance")} />}
              {advanceList
                .filter(isOpenAdvance)
                .slice(0, PREVIEW)
                .map((advance) => (
                  <AdvanceRow key={advance.id} advance={advance} onOpen={() => go.sheet("advanceInfo", { id: advance.id })} />
                ))}
            </>
          )}
        </>
      )}
    </Screen>
  );
}

type View = "soFar" | "month";

/** The month so far: the big number, the estimate, and its parts (so far or the whole month). */
function MonthBlock({ data, onProposed }: { data: Earnings | undefined; onProposed: () => void }) {
  const t = useWalletT();
  const { lang, locale } = useI18n();
  const [view, setView] = useState<View>("soFar");

  if (!data) {
    return (
      <>
        <Skeleton height={164} radius="calc(var(--radius-lg) * 1.15)" />
        <Skeleton height={44} radius={999} />
        <Skeleton height={168} radius="calc(var(--radius-lg) * 1.15)" />
      </>
    );
  }
  const pay = homePay(data);
  if (!pay) {
    return (
      <Card>
        <EmptyState compact icon={Wallet} tone="sage" title={t("hero.noSetup")} body={t("hero.noSetupBody")} />
      </Card>
    );
  }
  const sums = view === "soFar" ? data.so_far : data.estimate;
  return (
    <>
      <Card className="wal-hero">
        <div className="wal-hero-top">
          <span className="ui-kicker">{monthLabel(data.period, locale)}</span>
          <span className="wal-hint">{t("hero.asOf", { date: dayMonthLong(data.as_of, "UTC", locale) })}</span>
        </div>
        <span className="wal-label">{t("hero.soFar")}</span>
        <MoneyText amount={pay.amount} currency={pay.currency} size="hero" className="wal-hero-amount" />
        {pay.estimate && <span className="wal-hero-estimate">{t("home.estimate", { amount: formatMoney(pay.estimate, pay.currency, lang) })}</span>}
      </Card>

      <Segmented<View>
        options={[
          { value: "soFar", label: t("view.soFar") },
          { value: "month", label: t("view.month") },
        ]}
        value={view}
        onChange={setView}
        label={t("view.label")}
      />
      <ListCard className="wal-parts">
        {partRows(sums).map(({ part, amount }) => (
          <ListRow
            key={part}
            title={t(`part.${part}` as WalletKey)}
            value={<MoneyText amount={amount} currency={data.currency} sign={part === "base" ? "auto" : "always"} />}
          />
        ))}
        <ListRow className="wal-total" title={t("part.net")} value={<MoneyText amount={sums.net} currency={data.currency} />} />
      </ListCard>

      {data.proposed.length > 0 && (
        <Banner icon={Hourglass} title={t("proposed.count", { count: data.proposed.length })} body={t("proposed.hint")} chevron onClick={onProposed} />
      )}
    </>
  );
}
