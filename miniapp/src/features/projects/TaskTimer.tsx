/**
 * The project timer on the task screen (`task.actions`, PLAN-OWNER §13.3 "a timer on the task
 * screen"). Loaded lazily with the task screen, so the board lookup stays out of the first load.
 */
import { Play, Square, Timer as TimerIcon } from "lucide-react";

import type { Task } from "../../api/types";
import { useFeatureT } from "../../i18n/feature";
import { useNow } from "../../lib/useNow";
import { Button, Card } from "../../ui";
import type { TaskSlotProps } from "../registry";
import { useBoard, useTimer, type Board, type Card as BoardCard, type Project, type Timer } from "./api";
import { elapsed, hhmm } from "./lib";
import { messages } from "./messages";
import { useCardTimer } from "./useCardTimer";
import "./projects.css";

/** Projects whose cards still take time: not completed or cancelled. */
const takesTime = (project: Pick<Project, "status">) => project.status !== "completed" && project.status !== "cancelled";

/**
 * The card a task is, with its board. The task names its card's project (`task.card`), so only
 * that one board loads, shared with the board page's cache; a task that isn't a card loads
 * nothing. `undefined` while the board loads, `null` for a task that isn't a card, a card the
 * board doesn't show me, or a project that takes no more time.
 */
export function useCardOfTask(company: number, task: Pick<Task, "id" | "card">): { card: BoardCard; board: Board } | null | undefined {
  const board = useBoard(company, task.card?.project_id ?? 0, { staleTime: 30_000 });
  if (!task.card) return null;
  if (!board.data) return board.isError ? null : undefined;
  if (!takesTime(board.data.project)) return null;
  const card = board.data.cards.find((c) => c.id === task.id);
  return card ? { card, board: board.data } : null;
}

const CLOSED = ["done", "cancelled"];

/**
 * On the task screen: the timer for a project card. Running on this task: the clock and Stop
 * (whatever the card's state, so it can always be stopped). Otherwise, for an open card that is
 * mine or that I edit: what's logged and Start (which moves a timer running elsewhere here).
 * Nothing, and no request, for a task that isn't a card (a timer only ever runs on a card).
 */
export default function TaskTimer({ member, task }: TaskSlotProps) {
  const timer = useTimer(member.companyId, Boolean(task.card));
  const found = useCardOfTask(member.companyId, task);
  const controls = useCardTimer(member.companyId);
  const running = timer.data && timer.data.task?.id === task.id ? timer.data : null;
  if (running) return <RunningHere running={running} cardKey={task.card?.key ?? running.task_key} onStop={controls.stop} busy={controls.busy} />;
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
