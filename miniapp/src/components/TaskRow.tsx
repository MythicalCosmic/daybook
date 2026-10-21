import { Check, Repeat } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";

import type { Task } from "../api/types";
import { glyph, needsAttention, rowMeta, rowRight, type ViewContext } from "../lib/taskView";
import { SkeletonList } from "../ui/Skeleton";

type Props = {
  task: Task;
  ctx: ViewContext;
  onOpen: () => void;
  /** The round button on the left; omitted where ticking makes no sense. */
  onTick?: () => void;
  meta?: string;
  /** In place of the time chip: a finished run's proof photo. */
  trailing?: ReactNode;
};

export function TaskRow({ task, ctx, onOpen, onTick, meta, trailing }: Props) {
  const kind = glyph(task, ctx.now);
  const alert = needsAttention(task, ctx.now);
  const right = rowRight(task, ctx);
  const tick = (event: MouseEvent) => {
    event.stopPropagation();
    (onTick ?? onOpen)();
  };
  return (
    <div className="row" role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <button className={`glyph glyph--${kind}`} onClick={tick} aria-label={ctx.t("detail.markDone")}>
        <span>{kind === "done" && <Check size={18} strokeWidth={3} />}</span>
      </button>
      <div className="row-main">
        <div className={kind === "done" ? "row-title row-title--done" : "row-title"}>{task.title}</div>
        <div className={alert ? "row-meta row-meta--alert" : "row-meta"}>
          {/* Routines carry a repeat mark, so they never read as one-off work. */}
          {task.kind === "daily" ? (
            <span className="row-meta-routine">
              <Repeat size={13} strokeWidth={2.6} aria-hidden />
              <span>{meta ?? rowMeta(task, ctx)}</span>
            </span>
          ) : (
            (meta ?? rowMeta(task, ctx))
          )}
        </div>
      </div>
      {trailing ?? (right && <span className={alert ? "tag tag-accent" : "tag tag-neutral"}>{right}</span>)}
    </div>
  );
}

/** Placeholders for task rows while the board loads. */
export function RowSkeleton({ count = 3 }: { count?: number }) {
  return <SkeletonList count={count} height={68} />;
}
