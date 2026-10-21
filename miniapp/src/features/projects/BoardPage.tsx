import { AlarmClock, CheckSquare, CircleCheck, Lock, MessageSquare, Timer } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { useI18n } from "../../i18n";
import { useFeatureT } from "../../i18n/feature";
import { daysFromToday, dayMonth } from "../../lib/time";
import { useNavigation } from "../../state/navigation";
import { useMember } from "../../state/session";
import { useToast } from "../../state/toast";
import { haptic } from "../../telegram";
import { Avatar, Badge, EmptyState, IconButton, PageHeader, PullToRefresh, ScreenSkeleton, Segmented, cx } from "../../ui";
import type { PageProps } from "../registry";
import { useBoard, useMoveCard, useTimer, type Board, type Card } from "./api";
import { colorClass, endOf, hhmm } from "./lib";
import { messages } from "./messages";
import "./projects.css";

const HOLD_MS = 320;
const SLOP = 8;

type Drag = { card: Card; from: number; x: number; y: number; width: number; offsetX: number; offsetY: number; over: number | null };

/**
 * A project's board, made for a phone: lists stacked top to bottom, my cards marked. Hold one of
 * your cards to lift it, drag it onto another list and let go (a light buzz on lift, a click on
 * each list it passes, success on drop). A tap opens the card sheet, where "Move to" does the
 * same without dragging.
 */
export default function BoardPage({ params }: PageProps) {
  const projectId = Number(params.id) || 0;
  const member = useMember();
  const t = useFeatureT(messages);
  const navigation = useNavigation();
  const toast = useToast();
  const query = useBoard(member.companyId, projectId);
  const timer = useTimer(member.companyId);
  const move = useMoveCard(member.companyId, projectId);
  const [mine, setMine] = useState<"mine" | "all">("all");
  const [drag, setDrag] = useState<Drag | null>(null);
  const hold = useRef<{ timer: number; x: number; y: number; card: Card; element: HTMLElement; pointer: number } | null>(null);
  const screen = useRef<HTMLElement | null>(null);

  const board = query.data;
  const cards = useMemo(
    () => (board?.cards ?? []).filter((card) => mine === "all" || card.assignee?.id === member.id).sort((a, b) => a.position - b.position || a.id - b.id),
    [board, mine, member.id],
  );

  const openCard = (card: Card) => navigation.openSheet({ kind: "feature", feature: "projects", sheet: "card", params: { project: projectId, id: card.id } });

  const drop = useCallback(
    async (current: Drag) => {
      if (!board || current.over === null || current.over === current.from) return;
      const target = board.lists.find((list) => list.id === current.over);
      if (!target) return;
      haptic.impact("medium");
      try {
        const result = await move.mutateAsync({ card: current.card, list: target.id, position: endOf(board.cards, target.id) });
        haptic.notify("success");
        const status = result.card.status;
        toast(status === "done" ? t("movedDone", { key: result.card.key }) : status === "review" ? t("movedReview") : t("moved", { list: target.name }), { tone: "success" });
      } catch (error) {
        haptic.notify("error");
        const detail = (error as { detail?: string | null }).detail;
        toast(detail ?? t("moveFailed"), { tone: "error" });
        if ((error as { body?: { code?: string } }).body?.code === "needs_proof") openCard(current.card);
      }
    },
    [board, move, t],
  );

  // While a card is lifted the finger drags it, not the page.
  useEffect(() => {
    if (!drag) return;
    const stop = (event: TouchEvent) => event.preventDefault();
    document.addEventListener("touchmove", stop, { passive: false });
    return () => document.removeEventListener("touchmove", stop);
  }, [drag !== null]);

  function onPointerDown(event: ReactPointerEvent<HTMLButtonElement>, card: Card) {
    if (!card.can_move || event.button > 0) return;
    const element = event.currentTarget;
    screen.current = element.closest(".screen");
    const pointer = event.pointerId;
    const { clientX: x, clientY: y } = event;
    hold.current = {
      x,
      y,
      card,
      element,
      pointer,
      timer: window.setTimeout(() => {
        const rect = element.getBoundingClientRect();
        try {
          element.setPointerCapture(pointer);
        } catch {
          // Not every webview supports capture on buttons; moves still reach us.
        }
        haptic.impact("light");
        setDrag({ card, from: card.list_id ?? 0, x, y, width: rect.width, offsetX: x - rect.left, offsetY: y - rect.top, over: card.list_id });
        hold.current = null;
      }, HOLD_MS),
    };
  }

  function onPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const pending = hold.current;
    if (pending && (Math.abs(event.clientX - pending.x) > SLOP || Math.abs(event.clientY - pending.y) > SLOP)) {
      window.clearTimeout(pending.timer);
      hold.current = null;
    }
    if (!drag) return;
    const under = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-list-id]");
    const over = under ? Number(under.dataset.listId) : null;
    if (over !== drag.over && over !== null) haptic.select();
    setDrag({ ...drag, x: event.clientX, y: event.clientY, over });
    // Near the top or bottom edge, the page scrolls to reach lists out of sight.
    const box = screen.current;
    if (box) {
      const edge = 80;
      if (event.clientY < edge) box.scrollBy({ top: -14 });
      else if (event.clientY > window.innerHeight - edge) box.scrollBy({ top: 14 });
    }
  }

  function onPointerUp(card: Card) {
    const pending = hold.current;
    if (pending) {
      window.clearTimeout(pending.timer);
      hold.current = null;
      openCard(card);
      return;
    }
    if (drag) {
      const current = drag;
      setDrag(null);
      void drop(current);
    }
  }

  function onPointerCancel() {
    if (hold.current) window.clearTimeout(hold.current.timer);
    hold.current = null;
    setDrag(null);
  }

  if (query.isPending) {
    return (
      <div className="screen screen--detail enter">
        <ScreenSkeleton variant="list" delay={150} />
      </div>
    );
  }
  if (!board) {
    return (
      <div className="screen screen--detail enter">
        <PageHeader title={t("board")} onBack={navigation.pop} />
        <EmptyState compact title={t("error")} />
      </div>
    );
  }

  const project = board.project;
  const timedCard = timer.data?.task?.id ?? null;
  const hasMine = board.cards.some((card) => card.assignee?.id === member.id);

  return (
    <PullToRefresh onRefresh={() => query.refetch()} className={cx("screen screen--detail enter", colorClass(project.color))} disabled={drag !== null}>
      <PageHeader
        kicker={
          <>
            <span className="prj-key">{project.key}</span>
            {project.health && project.status === "active" ? ` · ${t(`health.${project.health}`)}` : ""}
          </>
        }
        title={project.name}
        onBack={navigation.pop}
        actions={
          <IconButton icon={MessageSquare} label={t("updates")} onClick={() => navigation.push({ feature: "projects", page: "updates", params: { id: projectId } })} />
        }
      />
      {hasMine && (
        <Segmented
          value={mine}
          onChange={setMine}
          options={[
            { value: "all", label: t("all"), count: board.cards.length },
            { value: "mine", label: t("mine"), count: board.cards.filter((card) => card.assignee?.id === member.id && card.status !== "done").length },
          ]}
          label={t("board")}
        />
      )}
      {board.lists.map((list) => {
        const inList = cards.filter((card) => card.list_id === list.id);
        const over = list.wip_limit !== null && inList.length > list.wip_limit;
        return (
          <section key={list.id} className={cx("prj-list", drag && drag.over === list.id && drag.from !== list.id && "prj-list--target")} data-list-id={list.id} aria-label={list.name}>
            <div className={cx("prj-list-head", list.is_done && "prj-list-done")}>
              {list.is_done && <CircleCheck size={16} strokeWidth={2.5} aria-hidden />}
              <span>{list.name}</span>
              <span className={cx("tag tag-neutral tag-small", over && "prj-wip--over")}>
                {inList.length}
                {list.wip_limit ? ` / ${list.wip_limit}` : ""}
              </span>
            </div>
            {inList.length === 0 ? (
              <div className="prj-empty-list">{drag && drag.from !== list.id ? t("dropHere") : t("noCards")}</div>
            ) : (
              inList.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  className={cx("prj-tile", card.assignee?.id === member.id && "prj-tile--mine", drag?.card.id === card.id && "prj-tile--lifted")}
                  onPointerDown={(event) => onPointerDown(event, card)}
                  onPointerMove={onPointerMove}
                  onPointerUp={() => onPointerUp(card)}
                  onPointerCancel={onPointerCancel}
                  onContextMenu={(event) => event.preventDefault()}
                  onClick={(event) => {
                    // Keyboard and screen readers: Enter/Space open the card (pointers use pointerup).
                    if (event.detail === 0) openCard(card);
                  }}
                >
                  <CardFace card={card} board={board} timed={timedCard === card.id} />
                </button>
              ))
            )}
          </section>
        );
      })}
      {hasMine && <p className="prj-hint">{t("dragHint")}</p>}
      {drag && (
        <div className="prj-tile prj-ghost" style={{ left: drag.x - drag.offsetX, top: drag.y - drag.offsetY, width: drag.width }} aria-hidden>
          <CardFace card={drag.card} board={board} timed={timedCard === drag.card.id} />
        </div>
      )}
    </PullToRefresh>
  );
}

function CardFace({ card, board, timed }: { card: Card; board: Board; timed: boolean }) {
  const t = useFeatureT(messages);
  const { locale } = useI18n();
  const member = useMember();
  const labels = card.label_ids.map((id) => board.labels.find((label) => label.id === id)).filter((label) => !!label);
  const days = card.due_at ? daysFromToday(card.due_at, new Date(), member.timeZone) : null;
  const dueClass = card.status === "done" ? "prj-chip--done" : card.overdue ? "prj-chip--late" : days !== null && days <= 1 ? "prj-chip--soon" : "";
  const dueText = !card.due_at ? "" : card.overdue ? t("late") : days === 0 ? t("today") : days === 1 ? t("tomorrow") : dayMonth(card.due_at, member.timeZone, locale);
  return (
    <>
      {labels.length > 0 && (
        <span className="prj-labels">
          {labels.map((label) => (
            <span key={label!.id} className={cx("prj-label", colorClass(label!.color))}>
              {label!.name}
            </span>
          ))}
        </span>
      )}
      <span className={cx("prj-tile-title", card.status === "done" && "prj-tile-title--done")}>{card.title}</span>
      {card.status === "review" && (
        <Badge size="small" tone="accent" className="prj-tile-badge">
          {t("movedReview")}
        </Badge>
      )}
      <span className="prj-tile-foot">
        <span className="prj-key">{card.key}</span>
        {card.due_at && (
          <span className={cx("prj-chip", dueClass)}>
            <AlarmClock size={11} strokeWidth={2.6} aria-hidden />
            {dueText}
          </span>
        )}
        {card.checklist_total > 0 && (
          <span className="prj-chip">
            <CheckSquare size={11} strokeWidth={2.6} aria-hidden />
            {card.checklist_done}/{card.checklist_total}
          </span>
        )}
        {(card.minutes > 0 || timed) && (
          <span className={cx("prj-chip", timed && "prj-chip--soon")}>
            <Timer size={11} strokeWidth={2.6} aria-hidden className={timed ? "prj-pulse" : undefined} />
            {hhmm(card.minutes)}
          </span>
        )}
        <span className="prj-spacer" />
        {!card.can_move && <Lock size={12} strokeWidth={2.4} aria-label={t("locked")} />}
        {card.assignee && <Avatar name={card.assignee.name} src={card.assignee.photo_url} size="xs" />}
      </span>
    </>
  );
}
