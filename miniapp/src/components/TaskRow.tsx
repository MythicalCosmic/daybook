import { Check, Flag, Gift, Repeat } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";

import type { Task } from "../api/types";
import { asLang } from "../i18n";
import { formatMoney } from "../lib/money";
import { glyph, minutesLeft, needsAttention, priorityLevel, rowMeta, rowRight, type ViewContext } from "../lib/taskView";
import { SkeletonList } from "../ui/Skeleton";

type Props = {
  task: Task;
  ctx: ViewContext;
  onOpen: () => void;
  /** The round button on the left; omitted where ticking makes no sense. */
  onTick?: () => void;
  meta?: string;
  /** In place of the time chip: a finished run's proof photo; `false` for nothing at all. */
  trailing?: ReactNode;
};

export function TaskRow({ task, ctx, onOpen, onTick, meta, trailing }: Props) {
  const lang = asLang(ctx.locale.slice(0, 2));
  const kind = glyph(task, ctx.now);
  const alert = needsAttention(task, ctx.now);
  const right = rowRight(task, ctx);
  // Within the last hour the chip counts down ("25 min left"), outlined so it reads apart from late.
  const soon = !alert && minutesLeft(task, ctx.now) !== null;
  const prio = priorityLevel(task);
  const tick = (event: MouseEvent) => {
    event.stopPropagation();
    (onTick ?? onOpen)();
  };
  const text = meta ?? rowMeta(task, ctx);
  return (
    <div className="row" role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <button className={`glyph glyph--${kind}`} onClick={tick} aria-label={ctx.t("detail.markDone")}>
        <span>{kind === "done" && <Check size={18} strokeWidth={3} />}</span>
      </button>
      <div className="row-main">
        <div className={kind === "done" ? "row-title row-title--done" : "row-title"}>{task.title}</div>
        <div className={alert ? "row-meta row-meta--alert" : "row-meta"}>
          {/* Urgency first, as a word with its flag (never colour alone); high is a quiet flag. */}
          {prio === "urgent" && task.status !== "done" && (
            <span className="prio prio--urgent">
              <Flag size={12} strokeWidth={2.8} aria-hidden />
              {ctx.t("priority.urgent")}
            </span>
          )}
          {prio === "high" && task.status !== "done" && (
            <span className="prio prio--high" role="img" aria-label={ctx.t("priority.high")} title={ctx.t("priority.high")}>
              <Flag size={13} strokeWidth={2.6} aria-hidden />
            </span>
          )}
          {task.reward && (
            <span className="row-reward">
              <Gift size={13} strokeWidth={2.6} aria-hidden />
              {formatMoney(task.reward, "UZS", lang, { sign: "always", compact: true })}
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
        </div>
      </div>
      {trailing ?? (right && <span className={alert ? "tag tag-accent" : soon ? "tag tag-soon" : "tag tag-neutral"}>{right}</span>)}
    </div>
  );
}

/** Placeholders for task rows while the board loads. */
export function RowSkeleton({ count = 3 }: { count?: number }) {
  return <SkeletonList count={count} height={68} />;
}
