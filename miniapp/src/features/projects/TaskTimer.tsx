/**
 * The project timer on the task screen (`task.actions`, PLAN-OWNER §13.3 "a timer on the task
 * screen"). Loaded lazily with the task screen, so the board lookup stays out of the first load.
 */
import { useQueries } from "@tanstack/react-query";
import { Play, Square, Timer as TimerIcon } from "lucide-react";

import { useFeatureT } from "../../i18n/feature";
import { useNow } from "../../lib/useNow";
import { Button, Card } from "../../ui";
import type { TaskSlotProps } from "../registry";
import { getBoard, projectKeys, useMyProjects, useTimer, type Board, type Card as BoardCard, type Project, type Timer } from "./api";
import { elapsed, hhmm } from "./lib";
import { messages } from "./messages";
import { useCardTimer } from "./useCardTimer";
import "./projects.css";

/** Projects whose cards still take time: not completed or cancelled. */
const takesTime = (project: Project) => project.status !== "completed" && project.status !== "cancelled";

/**
 * The card a task is, with its board, looked up in the boards of my live projects (the employee
 * task carries no project yet). `undefined` while that loads, `null` when it's on none of them.
 * Boards are shared with the board page's cache.
 */
export function useCardOfTask(company: number, taskId: number): { card: BoardCard; board: Board } | null | undefined {
  const projects = useMyProjects(company);
  const live = (projects.data ?? []).filter(takesTime);
  const boards = useQueries({
    queries: live.map((project) => ({
      queryKey: projectKeys.board(company, project.id),
      queryFn: () => getBoard(company, project.id),
      staleTime: 30_000,
    })),
  });
  if (!projects.data) return projects.isError ? null : undefined;
  for (const board of boards) {
    const card = board.data?.cards.find((c) => c.id === taskId);
    if (board.data && card) return { card, board: board.data };
  }
  return boards.some((board) => board.isPending) ? undefined : null;
}

const CLOSED = ["done", "cancelled"];

/**
 * On the task screen: the timer for a project card. Running on this task: the clock and Stop
 * (whatever the card's state, so it can always be stopped). Otherwise, for an open card that is
 * mine or that I edit: what's logged and Start (which moves a timer running elsewhere here).
 * Nothing for a task that isn't on one of my projects' boards.
 */
export default function TaskTimer({ member, task }: TaskSlotProps) {
  const timer = useTimer(member.companyId);
  const found = useCardOfTask(member.companyId, task.id);
  const controls = useCardTimer(member.companyId);
  const running = timer.data && timer.data.task?.id === task.id ? timer.data : null;
  if (running) return <RunningHere running={running} cardKey={found?.card.key ?? running.task_key} onStop={controls.stop} busy={controls.busy} />;
  if (!found || timer.isPending) return null;
  const { card, board } = found;
  const mine = task.assignee.id === member.id;
  if (CLOSED.includes(task.status) || !(mine || board.capabilities.edit_cards)) return null;
  return <StartHere cardKey={card.key} minutes={card.minutes} elsewhere={timer.data ?? null} onStart={() => controls.start(task.id)} busy={controls.busy} />;
}

function RunningHere({ running, cardKey, onStop, busy }: { running: Timer; cardKey: string | null; onStop: () => void; busy: boolean }) {
  const t = useFeatureT(messages);
  // Its own component, so only the running clock re-renders every second.
  const now = useNow(1000);
  return (
    <Card tone="accent" className="prj-timer prj-task-timer" layout="row" padding="flush" role="timer" aria-label={t("timerOn")}>
      <span className="circle ui-row-icon ui-row-icon--accent" aria-hidden>
        <TimerIcon size={20} strokeWidth={2.4} className="prj-pulse" />
      </span>
      <span className="row-main">
        <span className="prj-timer-clock">{elapsed(running.started_at, now.getTime())}</span>
        <span className="row-meta">{cardKey ? `${t("timerOn")} · ${cardKey}` : t("timerOn")}</span>
      </span>
      <Button variant="primary" icon={Square} loading={busy} onClick={onStop}>
        {t("timerStop")}
      </Button>
    </Card>
  );
}

function StartHere({
  cardKey,
  minutes,
  elsewhere,
  onStart,
  busy,
}: {
  cardKey: string;
  minutes: number;
  elsewhere: Timer | null;
  onStart: () => void;
  busy: boolean;
}) {
  const t = useFeatureT(messages);
  const away = elsewhere ? (elsewhere.task_key ?? elsewhere.project_key) : null;
  const meta = away
    ? t("timerElsewhere", { key: away })
    : minutes > 0
      ? `${cardKey} · ${t("timerLogged", { time: hhmm(minutes) })}`
      : cardKey;
  return (
    <Card className="prj-timer prj-task-timer" layout="row" padding="flush">
      <span className="circle ui-row-icon" aria-hidden>
        <TimerIcon size={20} strokeWidth={2.4} />
      </span>
      <span className="row-main">
        <span className="row-title">{t("card.timer")}</span>
        <span className="row-meta">{meta}</span>
      </span>
      {/* Never the same word as the task's own Start in the bar below ("Start timer", "Запустить"). */}
      <Button variant="secondary" icon={Play} loading={busy} onClick={onStart}>
        {t("timerStart")}
      </Button>
    </Card>
  );
}
