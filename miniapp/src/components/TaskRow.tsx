import { Check } from "lucide-react";
import type { MouseEvent } from "react";

import type { Task } from "../api/types";
import { glyph, needsAttention, rowMeta, rowRight, type ViewContext } from "../lib/taskView";

type Props = {
  task: Task;
  ctx: ViewContext;
  onOpen: () => void;
  /** The round button on the left; omitted where ticking makes no sense. */
  onTick?: () => void;
  meta?: string;
};

export function TaskRow({ task, ctx, onOpen, onTick, meta }: Props) {
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
        <div className={alert ? "row-meta row-meta--alert" : "row-meta"}>{meta ?? rowMeta(task, ctx)}</div>
      </div>
      {right && <span className={alert ? "tag tag-accent" : "tag tag-neutral"}>{right}</span>}
    </div>
  );
}

export function RowSkeleton({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="skeleton" style={{ height: 68 }} />
      ))}
    </>
  );
}
