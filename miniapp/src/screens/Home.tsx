import { AlarmClock, ChevronRight, Eye, Flame, TreePalm } from "lucide-react";

import { useActivity, useBoard, useSummary } from "../api/hooks";
import { ActivityRow } from "../components/ActivityRow";
import { Ring } from "../components/Ring";
import { RowSkeleton, TaskRow } from "../components/TaskRow";
import { useCompleteTask } from "../lib/actions";
import { byDue, isDueToday, isLate, isOpen } from "../lib/taskView";
import { dayKey, dayMonth, hourIn, longDate } from "../lib/time";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";

export function Home() {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const complete = useCompleteTask();
  const summary = useSummary(member.companyId);
  const board = useBoard(member.companyId);
  const activity = useActivity(member.companyId);

  const tasks = board.data ?? [];
  const late = tasks.filter((task) => isLate(task, ctx.now)).sort(byDue);
  const upNext = tasks
    .filter((task) => isOpen(task) && isDueToday(task, ctx) && !isLate(task, ctx.now))
    .sort(byDue)
    .slice(0, 3);
  const news = (activity.data ?? []).filter((item) => !item.is_read).slice(0, 2);
  const hour = hourIn(ctx.now, ctx.timeZone);
  const greeting = hour < 12 ? "home.morning" : hour < 18 ? "home.afternoon" : "home.evening";
  const numbers = summary.data;

  return (
    <div className="screen fade-in">
      <div className="page-head">
        <h1 className="heading title-md">{t(greeting, { name: member.first_name })}</h1>
        <div className="subline">
          {longDate(ctx.now, ctx.timeZone, ctx.locale)} · {member.company.name}
        </div>
      </div>

      <button className="card" style={{ flexDirection: "row", alignItems: "center", gap: 16, padding: "16px 18px", border: 0, textAlign: "left" }} onClick={() => navigation.goTo("tasks")}>
        <Ring done={numbers?.today_done ?? 0} total={numbers?.today_total ?? 0} />
        <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.25 }}>
            {numbers && numbers.today_total > 0
              ? t("home.progress", { done: numbers.today_done, total: numbers.today_total })
              : t("home.nothingToday")}
          </span>
          {numbers && numbers.streak_days > 0 && (
            <span className="tag tag-sage" style={{ alignSelf: "flex-start", fontSize: 13, padding: "4px 10px 4px 8px" }}>
              <Flame size={15} strokeWidth={2.6} />
              {t("home.streak", { count: numbers.streak_days })}
            </span>
          )}
        </span>
      </button>

      {numbers?.off_today && (
        <div className="banner banner--sage" style={{ padding: "14px 16px", gap: 14 }}>
          <span className="circle" style={{ width: 42, height: 42, background: "var(--color-accent-2)", color: "var(--color-bg)" }}>
            <TreePalm size={21} strokeWidth={2.4} />
          </span>
          <span className="row-main">
            <span style={{ fontSize: 16, fontWeight: 700 }}>
              {numbers.off_today.kind === "holiday" ? numbers.off_today.name : t("home.offToday")}
            </span>
            <span className="row-meta" style={{ color: "inherit", whiteSpace: "normal" }}>
              {numbers.off_today.until === dayKey(ctx.now, ctx.timeZone)
                ? t("home.offTodayBody")
                : t("home.offUntil", { date: dayMonth(`${numbers.off_today.until}T12:00:00Z`, "UTC", ctx.locale) })}
            </span>
          </span>
        </div>
      )}

      {late.length > 0 && (
        <button className="banner banner--accent" style={{ padding: "14px 16px", gap: 14 }} onClick={() => navigation.openTask(late[0].id)}>
          <span className="circle" style={{ width: 42, height: 42, background: "var(--color-accent)", color: "var(--color-bg)" }}>
            <AlarmClock size={21} strokeWidth={2.4} />
          </span>
          <span className="row-main">
            <span style={{ fontSize: 16, fontWeight: 700 }}>{t("home.late", { count: late.length })}</span>
            <span className="row-meta" style={{ color: "inherit" }}>{late[0].title}</span>
          </span>
          <ChevronRight size={20} strokeWidth={2.5} />
        </button>
      )}

      {numbers && numbers.awaiting_review > 0 && (
        <button className="banner banner--sage" style={{ padding: "14px 16px", gap: 14 }} onClick={() => navigation.goTo("tasks", "review")}>
          <span className="circle" style={{ width: 42, height: 42, background: "var(--color-accent-2)", color: "var(--color-bg)" }}>
            <Eye size={21} strokeWidth={2.4} />
          </span>
          <span className="row-main">
            <span style={{ fontSize: 16, fontWeight: 700 }}>{t("home.toCheck", { count: numbers.awaiting_review })}</span>
            <span className="row-meta" style={{ color: "inherit" }}>{t("home.toCheckBody")}</span>
          </span>
          <ChevronRight size={20} strokeWidth={2.5} />
        </button>
      )}

      <div className="section-head">
        <span>{t("home.upNext")}</span>
        <button className="btn btn-ghost" style={{ marginRight: -10 }} onClick={() => navigation.goTo("tasks")}>
          {t("home.allTasks")}
        </button>
      </div>
      {board.isPending ? (
        <RowSkeleton />
      ) : upNext.length ? (
        upNext.map((task) => (
          <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => navigation.openTask(task.id)} onTick={() => complete(task)} />
        ))
      ) : (
        <div className="muted" style={{ padding: 4, fontSize: 15 }}>{t("home.nothingNext")}</div>
      )}

      {news.length > 0 && (
        <>
          <div className="section-head">
            <span>{t("home.news")}</span>
            <button className="btn btn-ghost" style={{ marginRight: -10 }} onClick={() => navigation.goTo("activity")}>
              {t("home.seeAll")}
            </button>
          </div>
          {news.map((item) => (
            <ActivityRow key={item.id} item={item} ctx={ctx} onOpen={() => navigation.openTask(item.task.id)} />
          ))}
        </>
      )}
    </div>
  );
}
