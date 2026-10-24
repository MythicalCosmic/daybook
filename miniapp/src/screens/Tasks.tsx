import { CheckCheck, ChevronDown, ClipboardList, ListPlus, Plus, Send } from "lucide-react";
import { useEffect, useState } from "react";

import { useBoard, useGivenByMe, useReviewQueue } from "../api/hooks";
import type { Task } from "../api/types";
import { ReviewQueue, RoutinesTab } from "../components/Routines";
import { RowSkeleton, TaskRow } from "../components/TaskRow";
import { useCompleteTask } from "../lib/actions";
import { quickAddAvailable } from "../lib/quickAdd";
import {
  byFocus,
  duration,
  groupByDay,
  isDueToday,
  isLate,
  isOpen,
  lateBy,
  rowMeta,
  seenLabel,
  shortMoment,
  type ViewContext,
} from "../lib/taskView";
import { useViewContext } from "../lib/useNow";
import { useNavigation, type TasksTab } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";
import { EmptyState, LoadError } from "../ui";
import { useScrollEdges } from "../ui/useScrollEdges";

/** Scroll the tab strip just enough to show the chosen tab (no page jump). */
function keepInView(node: HTMLButtonElement | null) {
  const strip = node?.parentElement;
  if (!node || !strip || strip.scrollWidth <= strip.clientWidth) return;
  const left = node.offsetLeft - 8;
  const right = node.offsetLeft + node.offsetWidth + 8 - strip.clientWidth;
  if (strip.scrollLeft > left) strip.scrollTo({ left, behavior: "smooth" });
  else if (strip.scrollLeft < right) strip.scrollTo({ left: right, behavior: "smooth" });
}

const KIND: Record<"daily" | "assigned" | "personal", Task["kind"]> = {
  daily: "daily",
  assigned: "assigned",
  personal: "personal",
};

export function Tasks() {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
  const strip = useScrollEdges<HTMLDivElement>();
  const navigation = useNavigation();
  const complete = useCompleteTask();
  const canReview = member.permissions.includes("tasks.confirm");
  const canAssign = member.permissions.includes("tasks.assign");
  const board = useBoard(member.companyId);
  const reviews = useReviewQueue(member.companyId, canReview);
  const given = useGivenByMe(member.companyId, canAssign);

  const tasks = board.data ?? [];
  const wanted = navigation.tasksTab;
  const tab: TasksTab = (wanted === "review" && !canReview) || (wanted === "given" && !canAssign) ? "daily" : wanted;
  const leftToday = tasks.filter((task) => isOpen(task) && isDueToday(task, ctx)).length;
  const tabs: { key: TasksTab; count: number }[] = [
    { key: "daily", count: tasks.filter((task) => task.kind === "daily" && isOpen(task)).length },
    { key: "assigned", count: tasks.filter((task) => task.kind === "assigned" && isOpen(task)).length },
    { key: "personal", count: tasks.filter((task) => task.kind === "personal" && isOpen(task)).length },
  ];
  if (canReview) tabs.push({ key: "review", count: reviews.data?.length ?? 0 });
  if (canAssign) tabs.push({ key: "given", count: (given.data ?? []).filter(needsGiver(ctx.now)).length });

  const open = (task: Task) => navigation.openTask(task.id);
  const add = () => {
    haptic();
    navigation.openSheet({ kind: "add" });
  };
  // Counts and labels change the strip's width: say again which edges hide tabs, and keep the
  // chosen tab whole once its count arrives (a link straight to "Given by me" lands on the last).
  useEffect(strip.update);
  const counts = tabs.map((item) => item.count).join(",");
  useEffect(() => {
    keepInView(strip.ref.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]') ?? null);
  }, [tab, counts, strip.ref]);

  return (
    <div className="screen fade-in" style={{ gap: 10 }}>
      <div className="page-head">
        <h1 className="heading title-lg">{t("tasks.title")}</h1>
        {/* Counted once the list is here: "0 tasks left" while it loads would be a guess. */}
        <div className="subline">{board.data ? t("tasks.left", { count: leftToday }) : " "}</div>
      </div>

      {/* Four or five tabs with counts don't fit a phone in every language: the strip scrolls
          sideways then, keeping the chosen tab in view. */}
      <div ref={strip.ref} className="seg seg--scroll" role="tablist">
        {tabs.map(({ key, count }) => (
          <button
            key={key}
            ref={tab === key ? keepInView : undefined}
            className="seg-opt"
            role="tab"
            aria-pressed={tab === key}
            onClick={() => {
              haptic();
              navigation.setTasksTab(key);
            }}
          >
            <span>{t(`tasks.tab.${key}`)}</span>
            {count > 0 && <span className="count">{count}</span>}
          </button>
        ))}
      </div>

      {tab === "review" ? (
        <ReviewQueue tasks={reviews.data} loading={reviews.isPending} error={reviews.error} onRetry={() => void reviews.refetch()} ctx={ctx} onOpen={open} />
      ) : tab === "given" ? (
        <GivenByMe tasks={given.data} loading={given.isPending} error={given.error} onRetry={() => void given.refetch()} ctx={ctx} onOpen={open} onAdd={add} />
      ) : board.isPending ? (
        <RowSkeleton count={4} />
      ) : board.isError && !board.data ? (
        // Not "All done here": the list didn't load, and saying so beats a false all-clear.
        <LoadError compact error={board.error} onRetry={() => void board.refetch()} />
      ) : tab === "daily" ? (
        <RoutinesTab tasks={tasks.filter((task) => task.kind === "daily")} ctx={ctx} onOpen={open} onTick={complete} />
      ) : (
        <Groups tasks={tasks.filter((task) => task.kind === KIND[tab])} tab={tab} onOpen={open} onTick={complete} onAdd={add} ctx={ctx} />
      )}
    </div>
  );
}

function Groups({ tasks, tab, onOpen, onTick, onAdd, ctx }: {
  tasks: Task[];
  tab: "assigned" | "personal";
  onOpen: (task: Task) => void;
  onTick: (task: Task) => void;
  onAdd: () => void;
  ctx: ViewContext;
}) {
  const groups = groupByDay(tasks, ctx);
  // Work a week or more away waits folded, unless it's all there is.
  const [showLater, setShowLater] = useState(false);
  if (!groups.length) {
    // Each empty list says what will show up here and gives the one thing to do (R2 T44).
    return tab === "personal" ? (
      <EmptyState
        compact
        icon={ListPlus}
        title={ctx.t("tasks.empty.personal")}
        body={ctx.t(quickAddAvailable() ? "tasks.empty.personalQuick" : "tasks.empty.personalBody")}
        action={{ label: ctx.t("tasks.empty.add"), onClick: onAdd, icon: Plus }}
      />
    ) : (
      <EmptyState compact tone="sage" icon={ClipboardList} title={ctx.t("tasks.empty.assigned")} body={ctx.t("tasks.empty.assignedBody")} />
    );
  }
  const foldLater = groups.length > 1;
  return (
    <>
      {groups.map((group) => {
        const folded = group.key === "later" && foldLater && !showLater;
        return (
          <div key={group.key} style={{ display: "contents" }}>
            {group.key === "later" && foldLater ? (
              <button
                type="button"
                className="section-head section-head--small section-head--count routine-done-toggle"
                aria-expanded={!folded}
                onClick={() => {
                  haptic.select();
                  setShowLater((value) => !value);
                }}
              >
                <span>{ctx.t("tasks.group.later")}</span>
                <span className="tag tag-neutral tag-small">{group.tasks.length}</span>
                <ChevronDown size={19} strokeWidth={2.5} className="routine-done-chevron" aria-hidden />
              </button>
            ) : (
              <div className="section-head section-head--small" style={{ justifyContent: "flex-start", gap: 8 }}>
                <span>{ctx.t(`tasks.group.${group.key}`)}</span>
                <span className="tag tag-neutral tag-small">{group.tasks.length}</span>
              </div>
            )}
            {!folded &&
              group.tasks.map((task) => <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => onOpen(task)} onTick={() => onTick(task)} />)}
          </div>
        );
      })}
    </>
  );
}

/** Work I gave that wants something from me now: a blocker, a request for more time, lateness. */
const needsGiver = (now: Date) => (task: Task) => Boolean(task.blocker || task.extension) || isLate(task, now);

/** The line under a row I gave: who has it, and where it stands for me (seen, late, waiting). */
export function giverMeta(task: Task, ctx: ViewContext): string {
  const name = task.assignee.name;
  if (task.status === "review") {
    return task.completed_at ? `${name} · ${ctx.t("meta.doneAt", { time: shortMoment(task.completed_at, ctx) })}` : `${name} · ${ctx.t("status.review")}`;
  }
  if (task.blocker || task.extension || task.status === "returned") return `${name} · ${rowMeta(task, ctx)}`;
  if (isLate(task, ctx.now)) return `${name} · ${ctx.t("meta.late", { duration: duration(lateBy(task, ctx.now), ctx.t) })}`;
  return `${name} · ${seenLabel(task, ctx) ?? ctx.t(`status.${task.status}`)}`;
}

/**
 * Tasks → Given by me (R2 T9): work I handed out and haven't closed, what needs me first (a
 * blocker, more time, late), then work waiting for my check, then the rest still going.
 */
function GivenByMe({ tasks, loading, error, onRetry, ctx, onOpen, onAdd }: {
  tasks: Task[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  ctx: ViewContext;
  onOpen: (task: Task) => void;
  onAdd: () => void;
}) {
  if (loading) return <RowSkeleton count={3} />;
  if (!tasks && error) return <LoadError compact error={error} onRetry={onRetry} />;
  // Only work for others: someone's own tasks are theirs (a backend without `given_by` may send them).
  const mine = (tasks ?? []).filter((task) => task.kind !== "personal");
  if (!mine.length) {
    return (
      <EmptyState
        compact
        icon={Send}
        title={ctx.t("tasks.empty.given")}
        body={ctx.t("tasks.empty.givenBody")}
        action={{ label: ctx.t("tasks.empty.add"), onClick: onAdd, icon: Plus }}
      />
    );
  }
  const focus = byFocus(ctx.now);
  const attention = mine.filter((task) => isOpen(task) && needsGiver(ctx.now)(task)).sort(focus);
  const waiting = mine.filter((task) => task.status === "review").sort(focus);
  const going = mine.filter((task) => isOpen(task) && !needsGiver(ctx.now)(task)).sort(focus);
  const groups = [
    { key: "attention", label: ctx.t("tasks.group.attention"), tasks: attention },
    { key: "waitingYou", label: ctx.t("tasks.group.waitingYou"), tasks: waiting },
    { key: "going", label: ctx.t("tasks.group.going"), tasks: going },
  ].filter((group) => group.tasks.length > 0);
  if (!groups.length) {
    return <EmptyState compact tone="sage" icon={CheckCheck} title={ctx.t("tasks.empty.other")} body={ctx.t("tasks.empty.otherBody")} />;
  }
  return (
    <>
      {groups.map((group) => (
        <div key={group.key} style={{ display: "contents" }}>
          <div className="section-head section-head--small" style={{ justifyContent: "flex-start", gap: 8 }}>
            <span>{group.label}</span>
            <span className="tag tag-neutral tag-small">{group.tasks.length}</span>
          </div>
          {group.tasks.map((task) => (
            <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => onOpen(task)} meta={giverMeta(task, ctx)} wrapMeta />
          ))}
        </div>
      ))}
    </>
  );
}
