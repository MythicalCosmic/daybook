import { useBoard, useReviewQueue } from "../api/hooks";
import type { Task } from "../api/types";
import { RowSkeleton, TaskRow } from "../components/TaskRow";
import { useCompleteTask } from "../lib/actions";
import { groupTasks, isDueToday, isOpen } from "../lib/taskView";
import { clock } from "../lib/time";
import { useViewContext } from "../lib/useNow";
import { useNavigation, type TasksTab } from "../state/navigation";
import { useMember } from "../state/session";
import { haptic } from "../telegram";

const KIND: Record<Exclude<TasksTab, "review">, Task["kind"]> = {
  daily: "daily",
  assigned: "assigned",
  personal: "personal",
};

export function Tasks() {
  const ctx = useViewContext();
  const { t } = ctx;
  const member = useMember();
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

  return (
    <div className="screen fade-in" style={{ gap: 10 }}>
      <div className="page-head">
        <h1 className="heading title-lg">{t("tasks.title")}</h1>
        <div className="subline">{t("tasks.left", { count: leftToday })}</div>
      </div>

      <div className="seg" role="tablist">
        {tabs.map(({ key, count }) => (
          <button
            key={key}
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
        <ReviewList tasks={reviews.data} loading={reviews.isPending} onOpen={open} ctx={ctx} />
      ) : board.isPending ? (
        <RowSkeleton count={4} />
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
    return (
      <div className="muted" style={{ padding: "var(--space-6) 4px", fontSize: 16 }}>
        {tab === "personal" ? ctx.t("tasks.empty.personal") : ctx.t("tasks.empty.other")}
      </div>
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

function ReviewList({ tasks, loading, onOpen, ctx }: {
  tasks: Task[] | undefined;
  loading: boolean;
  onOpen: (task: Task) => void;
  ctx: ReturnType<typeof useViewContext>;
}) {
  if (loading) return <RowSkeleton count={3} />;
  if (!tasks?.length) {
    return <div className="muted" style={{ padding: "var(--space-6) 4px", fontSize: 16 }}>{ctx.t("tasks.empty.review")}</div>;
  }
  return (
    <>
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          ctx={ctx}
          onOpen={() => onOpen(task)}
          meta={ctx.t("meta.finishedBy", {
            name: task.assignee.name,
            time: task.completed_at ? clock(task.completed_at, ctx.timeZone, ctx.locale) : "—",
          })}
        />
      ))}
    </>
  );
}
