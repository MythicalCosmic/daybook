import { ArrowRight, Clock3, ExternalLink, Play, Square } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { clock, dayMonth } from "../../lib/time";
import { useNow } from "../../lib/useNow";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Button, Chip, SheetTitle } from "../../ui";
import type { SheetProps } from "../registry";
import { projectKeys, startTimer, stopTimer, useBoard, useMoveCard, useRefresh, useTimer, type Board } from "./api";
import { elapsed, endOf, hhmm } from "./lib";
import { messages } from "./messages";
import "./projects.css";

/**
 * A card from the board: where it is, its deadline and time, "Move to" (for my own cards), the
 * timer, "Log time", and the task itself (finishing with a photo happens there).
 */
export default function CardSheet({ params, close }: SheetProps) {
  const projectId = Number(params.project) || 0;
  const cardId = Number(params.id) || 0;
  const member = useMember();
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const navigation = useNavigation();
  const toast = useToast();
  const client = useQueryClient();
  const refresh = useRefresh(member.companyId);
  const board = useBoard(member.companyId, projectId);
  const timer = useTimer(member.companyId);
  const move = useMoveCard(member.companyId, projectId);
  const now = useNow(1000);

  const card = board.data?.cards.find((c) => c.id === cardId);
  if (!board.data || !card) return null;
  const data: Board = board.data;
  const list = data.lists.find((l) => l.id === card.list_id);
  const running = timer.data?.task?.id === card.id ? timer.data : null;
  const mine = card.assignee?.id === member.id;

  async function moveTo(listId: number) {
    const target = data.lists.find((l) => l.id === listId);
    if (!target || !card) return;
    haptic.select();
    try {
      const result = await move.mutateAsync({ card, list: listId, position: endOf(data.cards, listId) });
      haptic.notify("success");
      toast(result.card.status === "done" ? t("movedDone", { key: result.card.key }) : result.card.status === "review" ? t("movedReview") : t("moved", { list: target.name }), { tone: "success" });
    } catch (error) {
      haptic.notify("error");
      const code = (error as { body?: { code?: string } }).body?.code;
      toast(code === "needs_proof" ? t("card.needsProof") : ((error as { detail?: string | null }).detail ?? t("moveFailed")), { tone: "error" });
    }
  }

  async function toggleTimer() {
    if (!card) return;
    try {
      if (running) {
        const entry = await stopTimer(member.companyId);
        haptic.notify("success");
        if (entry) toast(t("timerLogged", { time: hhmm(entry.minutes) }), { tone: "success" });
      } else {
        await startTimer(member.companyId, { task: card.id });
        haptic.impact("light");
        toast(t("timerStarted"), { tone: "success" });
      }
      await client.invalidateQueries({ queryKey: projectKeys.timer(member.companyId) });
      void refresh();
    } catch (error) {
      toast((error as { detail?: string | null }).detail ?? t("moveFailed"), { tone: "error" });
    }
  }

  return (
    <div className="prj-sheet">
      <SheetTitle kicker={card.key}>{card.title}</SheetTitle>
      <div className="prj-facts">
        <div className="prj-fact">
          <span className="prj-fact-label">{t("card.list")}</span>
          <span className="prj-fact-value">{list?.name ?? "—"}</span>
        </div>
        <div className="prj-fact">
          <span className="prj-fact-label">{t("card.due")}</span>
          <span className="prj-fact-value">{card.due_at ? `${dayMonth(card.due_at, member.timeZone, locale)} · ${clock(card.due_at, member.timeZone, locale)}` : "—"}</span>
        </div>
        <div className="prj-fact">
          <span className="prj-fact-label">{t("card.assignee")}</span>
          <span className="prj-fact-value">{card.assignee?.name ?? "—"}</span>
        </div>
        <div className="prj-fact">
          <span className="prj-fact-label">{t("card.time")}</span>
          <span className="prj-fact-value">{hhmm(card.minutes)}</span>
        </div>
      </div>

      {card.can_move && card.status !== "done" && (
        <>
          <div className="section-head section-head--small">
            <span>{t("card.moveTo")}</span>
          </div>
          <div className="prj-moves">
            {data.lists
              .filter((l) => l.id !== card.list_id)
              .map((l) => (
                <Chip key={l.id} icon={ArrowRight} disabled={move.isPending} onClick={() => void moveTo(l.id)}>
                  {l.name}
                </Chip>
              ))}
          </div>
        </>
      )}

      {(mine || data.capabilities.edit_cards) && card.status !== "done" && (
        <Button variant={running ? "primary" : "secondary"} size="lg" block icon={running ? Square : Play} onClick={() => void toggleTimer()}>
          {running ? t("card.stop", { time: elapsed(running.started_at, now.getTime()) }) : t("card.start")}
        </Button>
      )}
      <Button
        variant="secondary"
        size="lg"
        block
        icon={Clock3}
        onClick={() => navigation.openSheet({ kind: "feature", feature: "projects", sheet: "log", params: { project: projectId, task: card.id } })}
      >
        {t("card.log")}
      </Button>
      {mine && (
        <Button
          variant="ghost"
          block
          icon={ExternalLink}
          onClick={() => {
            close();
            navigation.openTask(card.id);
          }}
        >
          {t("card.open")}
        </Button>
      )}
    </div>
  );
}
