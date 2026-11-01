import { Check, Flag, Gift, Repeat } from "lucide-react";
import { useId, type ReactNode } from "react";

import type { Task } from "../api/types";
import { asLang } from "../i18n";
import { formatMoney } from "../lib/money";
import { glyph, minutesLeft, needsAttention, priorityLevel, rowMeta, rowRight, type ViewContext } from "../lib/taskView";
import { SkeletonList } from "../ui/Skeleton";

type Props = {
  task: Task;
  ctx: ViewContext;
  onOpen: () => void;
  /** The round button on the left; without it the circle only shows the state (a tap opens). */
  onTick?: () => void;
  meta?: string;
  /** In place of the time chip: a finished run's proof photo; `false` for nothing at all. */
  trailing?: ReactNode;
  /** Let the line under the title wrap rather than cut (who has it and how late, for the giver). */
  wrapMeta?: boolean;
};

/**
 * A task in a list. The row and its tick are two buttons side by side, never one inside the other
 * (screen readers can't reach a button inside a button): the row's button is the whole card, and
 * the tick sits over the place the row keeps for it, so a tap lands where it always did.
 */
export function TaskRow({ task, ctx, onOpen, onTick, meta, trailing, wrapMeta = false }: Props) {
  const lang = asLang(ctx.locale.slice(0, 2));
  const titleId = useId();
  const kind = glyph(task, ctx.now);
  const alert = needsAttention(task, ctx.now);
  const right = rowRight(task, ctx);
  // Within the last hour the chip counts down ("25 min left"), outlined so it reads apart from late.
  const soon = !alert && minutesLeft(task, ctx.now) !== null;
  const prio = priorityLevel(task);
  const urgent = prio === "urgent" && task.status !== "done";
  const text = meta ?? rowMeta(task, ctx);
  const mark = <span>{kind === "done" && <Check size={18} strokeWidth={3} />}</span>;
  return (
    <div className="row-wrap">
      <button type="button" className="row" onClick={onOpen}>
        {onTick ? (
          <span className="glyph-slot" aria-hidden />
        ) : (
          <span className={`glyph glyph--${kind}`} aria-hidden>
            {mark}
          </span>
        )}
        <span className="row-main">
          <span id={titleId} className={kind === "done" ? "row-title row-title--done" : "row-title"}>
            {task.title}
          </span>
          {/* Urgency (a word with its flag, never colour alone) and the reward get their own line, so
              the line under them keeps who gave it or when it's due. */}
          {(urgent || task.reward) && (
            <span className="row-tags">
              {urgent && (
                <span className="prio prio--urgent">
                  <Flag size={12} strokeWidth={2.8} aria-hidden />
                  {ctx.t("priority.urgent")}
                </span>
              )}
              {task.reward && (
                <span className="row-reward">
                  <Gift size={13} strokeWidth={2.6} aria-hidden />
                  {formatMoney(task.reward, ctx.currency ?? "UZS", lang, { sign: "always", compact: true })}
                </span>
              )}
            </span>
          )}
          <span className={["row-meta", alert && "row-meta--alert", wrapMeta && "row-meta--wrap"].filter(Boolean).join(" ")}>
            {/* High is a quiet flag before the line. */}
            {prio === "high" && task.status !== "done" && (
              <span className="prio prio--high" role="img" aria-label={ctx.t("priority.high")} title={ctx.t("priority.high")}>
                <Flag size={13} strokeWidth={2.6} aria-hidden />
              </span>
            )}
            {/* Routines carry a repeat mark, so they never read as one-off work. */}
            {task.kind === "daily" ? (
              <span className="row-meta-routine">
                <Repeat size={13} strokeWidth={2.6} aria-hidden />
                <span>{text}</span>
              </span>
            ) : (
              <span className="row-meta-text">{text}</span>
            )}
          </span>
        </span>
        {trailing ?? (right && <span className={alert ? "tag tag-accent" : soon ? "tag tag-soon" : "tag tag-neutral"}>{right}</span>)}
      </button>
      {onTick && (
        <button type="button" className={`glyph glyph--${kind} row-tick`} onClick={onTick} aria-label={ctx.t("detail.markDone")} aria-describedby={titleId}>
          {mark}
        </button>
      )}
    </div>
  );
}

/** Placeholders for task rows while the board loads. */
export function RowSkeleton({ count = 3 }: { count?: number }) {
  return <SkeletonList count={count} height={68} />;
}
