/**
 * Transfers in (PLAN-OWNER §14.17): the goods other pharmacies sent here and nobody received
 * yet, "From Chilonzor: 8 items", each opening the screen that counts what arrived.
 */
import { Truck } from "lucide-react";

import { useI18n } from "../../i18n";
import { clock, dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { EmptyState, ListRow, LoadError, PageHeader, Screen } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { useIncoming } from "./api";
import { RowsSkeleton } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

export default function TransfersPage() {
  const t = useStockT();
  const { locale } = useI18n();
  const member = useMember();
  const navigation = useNavigation();
  const open = useFeatureOpen("stock");
  const incoming = useIncoming(member.companyId);
  const header = <PageHeader kicker={member.home_branch?.name ?? member.company.name} title={t("transfers.title")} subtitle={t("transfers.subtitle")} onBack={navigation.pop} />;
  if (!incoming.data) {
    return (
      <Screen variant="detail">
        {header}
        {incoming.isError ? <LoadError error={incoming.error} onRetry={() => void incoming.refetch()} onBack={navigation.pop} /> : <RowsSkeleton rows={2} />}
      </Screen>
    );
  }
  return (
    <Screen variant="detail">
      {header}
      {incoming.data.length === 0 ? (
        <EmptyState icon={Truck} tone="sage" title={t("transfers.emptyTitle")} body={t("transfers.emptyBody")} />
      ) : (
        <div className="stk-list">
          {incoming.data.map(({ transfer }) => {
            const sent = transfer.sent_at ? t("transfers.sent", { day: `${dayMonth(transfer.sent_at, member.timeZone, locale)} ${clock(transfer.sent_at, member.timeZone, locale)}` }) : null;
            return (
              <ListRow
                key={transfer.id}
                variant="card"
                tone="sage"
                icon={Truck}
                title={t("transfers.from", { branch: transfer.from_branch.name })}
                subtitle={[transfer.number, t("transfers.items", { count: transfer.lines_count }), sent].filter(Boolean).join(" · ")}
                onClick={() => open.page("transfer", { id: transfer.id })}
              />
            );
          })}
        </div>
      )}
    </Screen>
  );
}
