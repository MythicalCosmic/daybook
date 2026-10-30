import { AlarmClock, Eye, Flame, MessageCircleQuestion, Sun, TreePalm } from "lucide-react";

import { useActivity, useBoard, useGivenByMe, useSummary } from "../api/hooks";
import { givesWork } from "../api/permissions";
import { ActivityRow } from "../components/ActivityRow";
import { FeatureSlot } from "../features/FeatureSlot";
import { Ring } from "../components/Ring";
import { RowSkeleton, TaskRow } from "../components/TaskRow";
import { TeamCard } from "../components/TeamCard";
import { useCompleteTask } from "../lib/actions";
import { isFinished, isRoutine, routineProgress } from "../lib/routines";
import { byFocus, isDueToday, isLate, isOpen } from "../lib/taskView";
import { dayKey, dayMonthLong, hourIn, longDate } from "../lib/time";
import { useViewContext } from "../lib/useNow";
import { useNavigation } from "../state/navigation";
import { useMember } from "../state/session";
import { Banner, LoadError } from "../ui";

/**
 * Home, most urgent first: what to do right now (the hero: check in or out, the till), a head's
 * team, the shape of the day (off today, today's progress), what waits for me (late work, work to check, then
 * the feature cards: cash to confirm, the running timer, swaps, the next event, pages to read),
 * the next tasks and news, and overviews such as my projects at the end.
 *
 * Card anatomy: every notice is a Banner (icon circle, bold title, one line, chevron). Only what
 * can't wait is tinted (late work: accent) or the day itself (off today: sage); requests and
 * reminders sit on the plain surface with a coloured circle.
 */
export function Home() {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const navigation = useNavigation();
  const complete = useCompleteTask();
  const summary = useSummary(member.companyId);
  const board = useBoard(member.companyId);
  const activity = useActivity(member.companyId);
  const given = useGivenByMe(member.companyId, givesWork(member));
  const requests = (given.data ?? []).filter((task) => task.blocker || task.extension);

  const tasks = board.data ?? [];
  // Urgent work first, then the soonest deadline: the same order as the lists (R2 T7).
  const focus = byFocus(ctx.now);
  const late = tasks.filter((task) => isLate(task, ctx.now)).sort(focus);
  const upNext = tasks
    .filter((task) => isOpen(task) && isDueToday(task, ctx) && !isLate(task, ctx.now))
    .sort(focus)
    .slice(0, 3);
  const news = (activity.data ?? []).filter((item) => !item.is_read).slice(0, 2);
  const hour = hourIn(ctx.now, ctx.timeZone);
  // Before 05:00 is still the night (night shifts open the app then): "good evening", not "good morning".
  const greeting = hour < 5 ? "home.evening" : hour < 12 ? "home.morning" : hour < 18 ? "home.afternoon" : "home.evening";
  const numbers = summary.data;
  // Nothing due today: the progress card says so, and an empty "Up next" would say it twice.
  const showUpNext = !numbers || numbers.today_total > 0;
  // Routines and one-off work read apart: "Routines 2/4 · Tasks 1/3" when today has both.
  const routines = routineProgress(tasks, ctx);
  const oneOff = tasks.filter((task) => !isRoutine(task) && task.status !== "cancelled" && isDueToday(task, ctx));
  const split =
    routines.total > 0 && oneOff.length > 0
      ? t("home.split", { routines: `${routines.done}/${routines.total}`, tasks: `${oneOff.filter(isFinished).length}/${oneOff.length}` })
      : null;

  return (
    <div className="screen fade-in">
      <div className="page-head">
        <h1 className="heading title-md">{t(greeting, { name: member.first_name })}</h1>
        <div className="subline">
          {longDate(ctx.now, ctx.timeZone, ctx.locale)} · {member.company.name}
        </div>
      </div>

      <FeatureSlot name="home.hero" />

      <TeamCard />

      {numbers?.off_today && (
        <Banner
          tone="sage"
          size="lg"
          icon={TreePalm}
          title={numbers.off_today.kind === "holiday" ? numbers.off_today.name : t("home.offToday")}
          body={
            numbers.off_today.until === dayKey(ctx.now, ctx.timeZone)
              ? t("home.offTodayBody")
              : // The full month: "25-oktabrgacha" reads right, "25-oktgacha" would not.
                t("home.offUntil", { date: dayMonthLong(`${numbers.off_today.until}T12:00:00Z`, "UTC", ctx.locale) })
          }
          wrap
        />
      )}

      {/* Numbers that failed to load leave no card: a placeholder that never ends would say they're coming. */}
      {(numbers || !summary.isError) && (
      <button className="card card--tap home-today" onClick={() => navigation.goTo("tasks")}>
        {numbers && numbers.today_total === 0 ? (
          <span className="circle home-today-free" aria-hidden>
            <Sun size={28} strokeWidth={2.2} />
          </span>
        ) : (
          <Ring done={numbers?.today_done ?? 0} total={numbers?.today_total ?? 0} loading={!numbers} />
        )}
        <span className="home-today-text">
          {/* Before the numbers come, a placeholder line: "Nothing due today" would be a guess. */}
          {numbers ? (
            <span className="home-today-title">
              {numbers.today_total > 0
                ? t("home.progress", { done: numbers.today_done, total: numbers.today_total })
                : // With late work below, "nothing due today" would contradict it (audit M-11).
                  t(late.length > 0 ? "home.nothingNewToday" : "home.nothingToday")}
            </span>
          ) : (
            <span className="skeleton home-today-loading" aria-hidden />
          )}
          {split && numbers && numbers.today_total > 0 && <span className="home-today-split">{split}</span>}
          {numbers && numbers.streak_days > 0 && (
            <span className="tag tag-sage home-today-streak">
              <Flame size={15} strokeWidth={2.6} />
              {t("home.streak", { count: numbers.streak_days })}
            </span>
          )}
        </span>
      </button>
      )}

      {late.length > 0 && (
        <Banner
          tone="accent"
          size="lg"
          icon={AlarmClock}
          title={t("home.late", { count: late.length })}
          body={late[0].title}
          onClick={() => navigation.openTask(late[0].id)}
        />
      )}

      {/* Work I gave whose person can't do it or asks for more time: it waits for my answer. */}
      {requests.length > 0 && (
        <Banner
          size="lg"
          tone="accent"
          icon={MessageCircleQuestion}
          title={t("home.requests", { count: requests.length })}
          body={t("home.requestsBody")}
          wrap
          onClick={() => (requests.length === 1 ? navigation.openTask(requests[0].id) : navigation.goTo("tasks", "given"))}
        />
      )}

      {numbers && numbers.awaiting_review > 0 && (
        <Banner
          size="lg"
          iconTone="sage"
          icon={Eye}
          title={t("home.toCheck", { count: numbers.awaiting_review })}
          body={t("home.toCheckBody")}
          // A sentence, not a title: whole in Uzbek and Russian too, never cut to "…kutm…".
          wrap
          onClick={() => navigation.goTo("tasks", "review")}
        />
      )}

      <FeatureSlot name="home.cards" />

      {showUpNext && (
        <>
          <div className="section-head">
            <span>{t("home.upNext")}</span>
            <button className="btn btn-ghost" style={{ marginRight: -10 }} onClick={() => navigation.goTo("tasks")}>
              {t("home.allTasks")}
            </button>
          </div>
          {board.isPending ? (
            <RowSkeleton />
          ) : board.isError && !board.data ? (
            // Not "Nothing else due today": the list didn't load.
            <LoadError compact error={board.error} onRetry={() => void board.refetch()} />
          ) : upNext.length ? (
            upNext.map((task) => (
              <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => navigation.openTask(task.id)} onTick={() => complete(task)} />
            ))
          ) : (
            <div className="muted home-quiet">{t("home.nothingNext")}</div>
          )}
        </>
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

      {/* Overviews from feature folders (my projects): after the day's own work. */}
      <FeatureSlot name="home.end" />
    </div>
  );
}
