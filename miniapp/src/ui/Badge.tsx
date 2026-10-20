import type { ReactNode } from "react";

import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

export type BadgeTone = "neutral" | "accent" | "sage";

/** A small pill label (`.tag`): statuses, counts, durations. */
export function Badge({
  tone = "neutral",
  size = "md",
  icon,
  className,
  children,
}: {
  tone?: BadgeTone;
  size?: "md" | "small";
  icon?: IconLike;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span className={cx("tag", `tag-${tone}`, size === "small" && "tag-small", className)}>
      {renderIcon(icon, size === "small" ? 13 : 15, 2.6)}
      {children}
    </span>
  );
}

/** A terracotta count bubble ("3", "99+"); renders nothing for zero. */
export function CountBadge({ count, max = 99, label }: { count: number | null | undefined; max?: number; label?: string }) {
  if (!count || count <= 0) return null;
  return (
    <span className="ui-count" aria-label={label}>
      {count > max ? `${max}+` : count}
    </span>
  );
}

/** A small round marker: unread, live, needs attention. */
export function Dot({ tone = "accent", pulse = false, label }: { tone?: "accent" | "sage"; pulse?: boolean; label?: string }) {
  return (
    <span className={cx("ui-dot", `ui-dot--${tone}`, pulse && "ui-dot--pulse")} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />
  );
}
