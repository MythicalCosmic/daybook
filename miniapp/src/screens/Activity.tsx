import { useActivity, useMarkFeedRead } from "../api/hooks";
import { ActivityRow } from "../components/ActivityRow";
import { RowSkeleton } from "../components/TaskRow";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";

export function ActivityScreen() {
  const ctx = useViewContext();
  const { t } = ctx;
  const { companyId } = useMember();
  const navigation = useNavigation();
  const activity = useActivity(companyId);
  const markRead = useMarkFeedRead(companyId);

  const items = activity.data ?? [];
  const unread = items.filter((item) => !item.is_read);
  const earlier = items.filter((item) => item.is_read);
  const groups = [
    { title: t("activity.groupNew"), items: unread },
    { title: t("activity.groupEarlier"), items: earlier },
  ].filter((group) => group.items.length > 0);

  return (
    <div className="screen fade-in" style={{ gap: 10 }}>
      <div className="page-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12 }}>
        <div>
          <h1 className="heading title-lg">{t("activity.title")}</h1>
          <div className="subline">
            {unread.length ? t("activity.new", { count: unread.length }) : t("activity.caughtUp")}
          </div>
        </div>
        {unread.length > 0 && (
          <button
            className="btn btn-ghost"
            style={{ marginRight: -10 }}
            disabled={markRead.isPending}
            onClick={() => {
              haptic();
              markRead.mutate();
            }}
          >
            {t("activity.markAll")}
          </button>
        )}
      </div>

      {activity.isPending && <RowSkeleton count={4} />}
      {!activity.isPending && !items.length && (
        <div className="muted" style={{ padding: "var(--space-6) 4px", fontSize: 16 }}>{t("activity.empty")}</div>
      )}
      {groups.map((group) => (
        <div key={group.title} style={{ display: "contents" }}>
          <div className="section-head section-head--small">{group.title}</div>
          {group.items.map((item) => (
            <ActivityRow key={item.id} item={item} ctx={ctx} onOpen={() => navigation.openTask(item.task.id)} />
          ))}
        </div>
      ))}
    </div>
  );
}
