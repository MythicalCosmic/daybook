/**
 * The project timer: the hook every place that starts or stops it shares (Home, the card sheet,
 * the task screen), and the task screen's block (`task.actions`, PLAN-OWNER §13.3 "a timer on
 * the task screen").
 */
import { Play, Square, Timer as TimerIcon } from "lucide-react";

import { useFeatureT } from "../../i18n/feature";
import { useNow } from "../../lib/useNow";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, Card } from "../../ui";
import type { TaskSlotProps } from "../registry";
import { useCardOfTask, useTimer, useTimerAction, type Timer } from "./api";
import { elapsed, hhmm } from "./lib";
import { messages } from "./messages";
import "./projects.css";

/** Start my timer on a card or stop it, with the haptics and toasts every place uses. */
export function useCardTimer(company: number) {
  const t = useFeatureT(messages);
  const toast = useToast();
  const action = useTimerAction(company);
  const failed = (error: unknown) => {
    haptic.notify("error");
    toast((error as { detail?: string | null }).detail ?? t("timerFailed"), { tone: "error" });
  };
  return {
    busy: action.isPending,
    start: (task: number) =>
      action.mutate(
        { kind: "start", task },
        {
          onSuccess: () => {
            haptic.impact("light");
            toast(t("timerStarted"), { tone: "success" });
          },
          onError: failed,
        },
      ),
    stop: () =>
      action.mutate(
        { kind: "stop" },
        {
          onSuccess: (entry) => {
            haptic.notify("success");
            if (entry) toast(t("timerLogged", { time: hhmm(entry.minutes) }), { tone: "success" });
          },
          onError: failed,
        },
      ),
  };
}

const CLOSED = ["done", "cancelled"];

/**
 * On the task screen: the timer for a project card. Running on this task: the clock and Stop
 * (whatever the card's state, so it can always be stopped). Otherwise, for an open card that is
 * mine or that I edit: what's logged and Start (which moves a timer running elsewhere here).
 * Nothing for a task that isn't on one of my projects' boards.
 */
export function TaskTimer({ member, task }: TaskSlotProps) {
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
      {/* "Start timer", not "Start": the task's own Start sits in the bar below. */}
      <Button variant="secondary" icon={Play} loading={busy} onClick={onStart}>
        {t("card.start")}
      </Button>
    </Card>
  );
}
