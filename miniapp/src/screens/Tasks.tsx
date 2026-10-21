import { CheckCheck, ListPlus } from "lucide-react";
import { useEffect } from "react";

import { useBoard, useReviewQueue } from "../api/hooks";
import type { Task } from "../api/types";
import { ReviewQueue, RoutinesTab } from "../components/Routines";
import { RowSkeleton, TaskRow } from "../components/TaskRow";
import { useCompleteTask } from "../lib/actions";
import { groupTasks, isDueToday, isOpen } from "../lib/taskView";
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

const KIND: Record<Exclude<TasksTab, "review">, Task["kind"]> = {
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
  const board = useBoard(member.companyId);
  const reviews = useReviewQueue(member.companyId, canReview);

  const tasks = board.data ?? [];
  const tab = navigation.tasksTab === "review" && !canReview ? "daily" : navigation.tasksTab;
  const leftToday = tasks.filter((task) => isOpen(task) && isDueToday(task, ctx)).length;
  const tabs: { key: TasksTab; count: number }[] = [
    { key: "daily", count: tasks.filter((task) => task.kind === "daily" && isOpen(task)).length },
    { key: "assigned", count: tasks.filter((task) => task.kind === "assigned" && isOpen(task)).length },
    { key: "personal", count: tasks.filter((task) => task.kind === "personal" && isOpen(task)).length },
  ];
  if (canReview) tabs.push({ key: "review", count: reviews.data?.length ?? 0 });

  const open = (task: Task) => navigation.openTask(task.id);
  // Counts and labels change the strip's width: say again which edges hide tabs.
  useEffect(strip.update);

  return (
    <div className="screen fade-in" style={{ gap: 10 }}>
      <div className="page-head">
        <h1 className="heading title-lg">{t("tasks.title")}</h1>
        <div className="subline">{t("tasks.left", { count: leftToday })}</div>
      </div>

      {/* Four tabs with counts don't fit a phone in every language: the strip scrolls sideways
          then, keeping the chosen tab in view. */}
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
      ) : board.isPending ? (
        <RowSkeleton count={4} />
      ) : board.isError && !board.data ? (
        // Not "All done here": the list didn't load, and saying so beats a false all-clear.
        <LoadError compact error={board.error} onRetry={() => void board.refetch()} />
      ) : tab === "daily" ? (
        <RoutinesTab tasks={tasks.filter((task) => task.kind === "daily")} ctx={ctx} onOpen={open} onTick={complete} />
      ) : (
        <Groups tasks={tasks.filter((task) => task.kind === KIND[tab])} tab={tab} onOpen={open} onTick={complete} ctx={ctx} />
      )}
    </div>
  );
}

function Groups({ tasks, tab, onOpen, onTick, ctx }: {
  tasks: Task[];
  tab: TasksTab;
  onOpen: (task: Task) => void;
  onTick: (task: Task) => void;
  ctx: ReturnType<typeof useViewContext>;
}) {
  const groups = groupTasks(tasks, ctx.now);
  if (!groups.length) {
    return tab === "personal" ? (
      <EmptyState compact icon={ListPlus} title={ctx.t("tasks.empty.personal")} body={ctx.t("tasks.empty.personalBody")} />
    ) : (
      <EmptyState compact tone="sage" icon={CheckCheck} title={ctx.t("tasks.empty.other")} body={ctx.t("tasks.empty.otherBody")} />
    );
  }
  return (
    <>
      {groups.map((group) => (
        <div key={group.key} style={{ display: "contents" }}>
          <div className="section-head section-head--small" style={{ justifyContent: "flex-start", gap: 8 }}>
            <span>{ctx.t(`tasks.group.${group.key}`)}</span>
            <span className="tag tag-neutral tag-small">{group.tasks.length}</span>
          </div>
          {group.tasks.map((task) => (
            <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => onOpen(task)} onTick={() => onTick(task)} />
          ))}
        </div>
      ))}
    </>
  );
}
