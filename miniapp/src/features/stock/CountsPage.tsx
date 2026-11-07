/**
 * The stock counts open at my pharmacies (PLAN-OWNER §14.17), each opening the blind count. The
 * head starts a count in the dashboard; until the server lists them for the app (a hand-off
 * item), a count opens from its link (`stock.count:<id>`) and this page says none is open.
 */
import { ClipboardList } from "lucide-react";

import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { EmptyState, ListRow, LoadError, PageHeader, Screen } from "../../ui";
import { useFeatureOpen } from "../useFeatureOpen";
import { useOpenCounts } from "./api";
import { RowsSkeleton } from "./parts";
import { useStockT } from "./text";
import "./stock.css";

export default function CountsPage() {
  const t = useStockT();
  const member = useMember();
  const navigation = useNavigation();
  const open = useFeatureOpen("stock");
  const counts = useOpenCounts(member.companyId);
  const header = <PageHeader kicker={member.home_branch?.name ?? member.company.name} title={t("count.title")} subtitle={t("count.intro")} onBack={navigation.pop} />;
  if (counts.isPending) {
    return (
      <Screen variant="detail">
        {header}
        <RowsSkeleton rows={2} />
      </Screen>
    );
  }
  if (counts.isError) {
    return (
      <Screen variant="detail">
        {header}
        <LoadError error={counts.error} onRetry={() => void counts.refetch()} onBack={navigation.pop} />
      </Screen>
    );
  }
  const rows = (counts.data ?? []).filter((count) => count.status === "open");
  return (
    <Screen variant="detail">
      {header}
      {rows.length === 0 ? (
        <EmptyState icon={ClipboardList} tone="sage" title={t("count.noneTitle")} body={t("count.noneBody")} />
      ) : (
        <div className="stk-list">
          {rows.map((count) => (
            <ListRow
              key={count.id}
              variant="card"
              icon={ClipboardList}
              title={t(`count.kind.${count.kind}`)}
              subtitle={`${count.branch.name} · ${t("count.progress", { done: count.counted_count, total: count.lines_count })}`}
              onClick={() => open.page("count", { id: count.id })}
            />
          ))}
        </div>
      )}
    </Screen>
  );
}
