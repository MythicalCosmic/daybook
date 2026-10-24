import { CheckCheck, ChevronDown, Eye, Repeat, Undo2 } from "lucide-react";
import { useState } from "react";

import type { Task } from "../api/types";
import { useConfirmTasks } from "../lib/actions";
import { byFinished, finishedAt, groupByRoutine, isRoutine, routineProgress, type RoutineGroup } from "../lib/routines";
import { groupTasks, repeatLabel, rowMeta, type ViewContext } from "../lib/taskView";
import { clock, dayMonth, daysFromToday } from "../lib/time";
import { useNavigation } from "../state/navigation";
import { haptic } from "../telegram";
import { Avatar, Button, EmptyState, IconButton, LoadError, ProgressBar, cx } from "../ui";
import { RowSkeleton, TaskRow } from "./TaskRow";

type Open = (task: Task) => void;

/** "09:12" today, "20 Oct 18:02" before. */
function when(at: string | null, ctx: ViewContext): string {
  if (!at) return "";
  const time = clock(at, ctx.timeZone, ctx.locale);
  return daysFromToday(at, ctx.now, ctx.timeZone) === 0 ? time : `${dayMonth(at, ctx.timeZone, ctx.locale)} ${time}`;
}

/** A finished run's line: when it was done (or checked), and the note it was finished with. */
function doneMeta(task: Task, ctx: ViewContext): string {
  const note = task.proof_text.trim();
  return note ? `${rowMeta(task, ctx)} · ${ctx.t("routines.quoted", { text: note })}` : rowMeta(task, ctx);
}

/** The proof photo, small, at the end of a finished run's row. */
function ProofThumb({ task }: { task: Task }) {
  if (!task.proof_thumb) return null;
  return <img className="row-thumb" src={task.proof_thumb} alt="" loading="lazy" decoding="async" />;
}

/**
 * My routines (Tasks → Routines): today's progress, what's still to do, and today's finished runs
 * kept in sight, folded under "Done today" with when and how each was done.
 */
export function RoutinesTab({ tasks, ctx, onOpen, onTick }: { tasks: Task[]; ctx: ViewContext; onOpen: Open; onTick: Open }) {
  const { t } = ctx;
  const [showDone, setShowDone] = useState(false);
  const { done: finished, total } = routineProgress(tasks, ctx);
  const groups = groupTasks(
    tasks.filter((task) => task.status !== "done"),
    ctx.now,
  );
  const done = tasks.filter((task) => task.status === "done").sort(byFinished);
  return (
    <>
      <div className="card routine-summary">
        <div className="routine-summary-row">
          <span className={cx("circle routine-summary-icon", total > 0 && finished === total && "routine-summary-icon--done")} aria-hidden>
            {total > 0 && finished === total ? <CheckCheck size={21} strokeWidth={2.5} /> : <Repeat size={20} strokeWidth={2.4} />}
          </span>
          <span className="row-main">
            <span className="routine-summary-title">{total ? t("routines.progress", { done: finished, total }) : t("routines.noneToday")}</span>
            {/* None today: what will show up here, and when (R2 T44). */}
            <span className="row-meta row-meta--wrap">{total ? t("routines.help") : t("routines.noneHelp")}</span>
          </span>
        </div>
        {total > 0 && <ProgressBar value={finished} total={total} size="sm" tone={finished === total ? "sage" : "accent"} ariaLabel={t("routines.progress", { done: finished, total })} />}
      </div>

      {groups.map((group) => (
        <div key={group.key} style={{ display: "contents" }}>
          <div className="section-head section-head--small section-head--count">
            <span>{t(`tasks.group.${group.key}`)}</span>
            <span className="tag tag-neutral tag-small">{group.tasks.length}</span>
          </div>
          {group.tasks.map((task) => (
            <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => onOpen(task)} onTick={() => onTick(task)} />
          ))}
        </div>
      ))}

      {done.length > 0 && (
        <>
          <button
            type="button"
            className="section-head section-head--small section-head--count routine-done-toggle"
            aria-expanded={showDone}
            onClick={() => {
              haptic.select();
              setShowDone((value) => !value);
            }}
          >
            <span>{t("tasks.group.doneToday")}</span>
            <span className="tag tag-sage tag-small">{done.length}</span>
            <ChevronDown size={19} strokeWidth={2.5} className="routine-done-chevron" aria-hidden />
          </button>
          {showDone &&
            done.map((task) => (
              <TaskRow key={task.id} task={task} ctx={ctx} onOpen={() => onOpen(task)} meta={doneMeta(task, ctx)} trailing={<ProofThumb task={task} />} />
            ))}
        </>
      )}
    </>
  );
}

/**
 * Work waiting for my check (Tasks → To check): routines' runs grouped by routine, photos side by
 * side, confirmed together or sent back one by one; one-off tasks below, one at a time.
 */
export function ReviewQueue({
  tasks,
  loading,
  error,
  onRetry,
  ctx,
  onOpen,
}: {
  tasks: Task[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  ctx: ViewContext;
  onOpen: Open;
}) {
  const { t } = ctx;
  if (loading) return <RowSkeleton count={3} />;
  if (!tasks && error) return <LoadError compact error={error} onRetry={onRetry} />;
  if (!tasks?.length) {
    return <EmptyState compact tone="sage" icon={Eye} title={t("tasks.empty.review")} body={t("tasks.empty.reviewBody")} />;
  }
  const routines = groupByRoutine(tasks.filter(isRoutine));
  const runs = routines.reduce((sum, group) => sum + group.tasks.length, 0);
  const oneOff = tasks.filter((task) => !isRoutine(task));
  return (
    <>
      {routines.length > 0 && (
        <>
          <div className="section-head section-head--small section-head--count">
            <span>{t("review.routines")}</span>
            <span className="tag tag-neutral tag-small">{runs}</span>
          </div>
          <p className="routine-hint">{t("review.routinesHelp")}</p>
          {routines.map((group) => (
            <RoutineCheck key={group.key} group={group} ctx={ctx} onOpen={onOpen} />
          ))}
        </>
      )}
      {oneOff.length > 0 && (
        <>
          <div className="section-head section-head--small section-head--count">
            <span>{t("review.oneOff")}</span>
            <span className="tag tag-neutral tag-small">{oneOff.length}</span>
          </div>
          {oneOff.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              ctx={ctx}
              onOpen={() => onOpen(task)}
              // The day too when it isn't today: work that has waited three days says so (audit M-8).
              meta={t("meta.finishedBy", { name: task.assignee.name, time: when(task.completed_at, ctx) || "—" })}
              trailing={false}
            />
          ))}
        </>
      )}
    </>
  );
}

/** One routine's runs waiting for a check: the proofs in a grid, Confirm all, Send back each. */
function RoutineCheck({ group, ctx, onOpen }: { group: RoutineGroup; ctx: ViewContext; onOpen: Open }) {
  const { t } = ctx;
  const navigation = useNavigation();
  const confirmTasks = useConfirmTasks();
  const count = group.tasks.length;
  const repeat = repeatLabel(group.tasks[0].repeat_weekdays, ctx);

  // Goes out after a moment, with Undo in the toast meanwhile (the server can't take it back).
  const confirmAll = () => confirmTasks(group.tasks);

  return (
    <div className="card routine-check">
      <div className="routine-check-head">
        <span className="circle routine-check-icon" aria-hidden>
          <Repeat size={18} strokeWidth={2.4} />
        </span>
        <span className="row-main">
          <span className="row-title">{group.title}</span>
          <span className="row-meta">{[repeat, t("review.runs", { count })].filter(Boolean).join(" · ")}</span>
        </span>
      </div>
      {/* The routine's action sits under its name: in sight as the card arrives, however many runs
          follow, and never at the foot of the screen under the tab bar and its (+). */}
      <Button variant="primary" block icon={CheckCheck} onClick={confirmAll} className="routine-check-confirm">
        {count > 1 ? t("review.confirmAll", { count }) : t("detail.confirm")}
      </Button>
      {/* One run alone gets the card's whole width rather than half of an empty grid. */}
      <div className={cx("routine-check-grid", count === 1 && "routine-check-grid--one")}>
        {group.tasks.map((task) => (
          <div key={task.id} className="run-tile">
            <button type="button" className="run-tile-proof" onClick={() => onOpen(task)} aria-label={t("review.openRun", { name: task.assignee.name })}>
              {task.proof_thumb ? (
                <img src={task.proof_thumb} alt="" loading="lazy" decoding="async" />
              ) : task.proof_text.trim() ? (
                <span className="run-tile-note">{task.proof_text.trim()}</span>
              ) : (
                <span className="run-tile-empty">
                  <Avatar name={task.assignee.name} size="md" />
                  <span>{t("review.noProof")}</span>
                </span>
              )}
            </button>
            <div className="run-tile-foot">
              <span className="run-tile-who">
                <span className="run-tile-name" title={task.assignee.name}>
                  {task.assignee.name}
                </span>
                <span className="run-tile-time num">{when(finishedAt(task), ctx)}</span>
              </span>
              <IconButton
                icon={Undo2}
                size={40}
                label={t("review.sendBack", { name: task.assignee.name })}
                className="run-tile-back"
                onClick={() => {
                  haptic();
                  navigation.openSheet({ kind: "return", taskId: task.id });
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
