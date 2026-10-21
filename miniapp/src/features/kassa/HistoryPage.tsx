import { CalendarClock } from "lucide-react";

import { useI18n } from "../../i18n";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { Button, EmptyState, PageHeader, PullToRefresh, ScreenSkeleton, SectionHead } from "../../ui";
import type { PageProps } from "../registry";
import { isDenied, useHistory, useKassa, type Shift } from "./api";
import { monthYear, useKassaT } from "./lib";
import { Denied, ErrorScreen, ShiftRow } from "./parts";

/** All my shifts, newest first, by month. The result shows once a manager checked the shift. */
export default function HistoryPage(_: PageProps) {
  const t = useKassaT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const history = useHistory(member.companyId);
  const kassa = useKassa(member.companyId);
  const currency = kassa.data?.settings.currency ?? "UZS";
  const shifts = history.data?.pages.flatMap((page) => page.results) ?? [];
  const months = new Map<string, Shift[]>();
  for (const shift of shifts) {
    const month = shift.business_day.slice(0, 7);
    months.set(month, [...(months.get(month) ?? []), shift]);
  }

  return (
    <PullToRefresh className="screen screen--detail" onRefresh={() => history.refetch()}>
      <PageHeader kicker={t("kassa")} title={t("history.title")} subtitle={t("history.subtitle")} onBack={navigation.pop} />
      {history.isPending ? (
        <ScreenSkeleton variant="list" delay={150} />
      ) : history.isError ? (
        isDenied(history.error) ? (
          <Denied />
        ) : (
          <ErrorScreen error={history.error} retry={() => history.refetch()} />
        )
      ) : shifts.length === 0 ? (
        <EmptyState icon={CalendarClock} tone="sage" title={t("history.empty.title")} body={t("history.empty.body")} />
      ) : (
        <>
          {[...months.entries()].map(([month, rows]) => (
            <section key={month} className="kassa-month">
              <SectionHead size="small" count={rows.length}>
                <span className="kassa-month-name">{monthYear(month, locale)}</span>
              </SectionHead>
              {rows.map((shift) => (
                <ShiftRow key={shift.id} shift={shift} currency={currency} />
              ))}
            </section>
          ))}
          {history.hasNextPage && (
            <Button block loading={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>
              {t("history.more")}
            </Button>
          )}
        </>
      )}
    </PullToRefresh>
  );
}
