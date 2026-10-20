import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

export type Trend = {
  direction: "up" | "down" | "flat";
  text: ReactNode;
  /** Whether this direction is good news (more sales: yes; more late tasks: no). */
  good?: boolean;
};

/** A number tile: "67% on time this month", "8 tasks done", "1,2 mln earned". */
export function Stat({
  value,
  label,
  hint,
  trend,
  icon,
  tone = "plain",
  onClick,
  className,
}: {
  value: ReactNode;
  label: ReactNode;
  hint?: ReactNode;
  trend?: Trend;
  icon?: IconLike;
  tone?: "plain" | "accent" | "sage";
  onClick?: () => void;
  className?: string;
}) {
  const TrendIcon = trend?.direction === "up" ? TrendingUp : trend?.direction === "down" ? TrendingDown : Minus;
  const content = (
    <>
      {icon && <span className="ui-stat-icon">{renderIcon(icon, 18, 2.5)}</span>}
      <span className="heading num ui-stat-value">{value}</span>
      <span className="ui-stat-label">{label}</span>
      {hint && <span className="ui-stat-hint">{hint}</span>}
      {trend && (
        <span className={cx("ui-trend", trend.good === undefined ? "ui-trend--flat" : trend.good ? "ui-trend--good" : "ui-trend--bad")}>
          <TrendIcon size={14} strokeWidth={2.75} aria-hidden />
          {trend.text}
        </span>
      )}
    </>
  );
  const classes = cx("card ui-stat", tone !== "plain" && `card--${tone}`, onClick && "card--tap", className);
  return onClick ? (
    <button type="button" className={classes} onClick={onClick}>
      {content}
    </button>
  ) : (
    <div className={classes}>{content}</div>
  );
}

/** Stat tiles side by side (two per row by default). */
export function StatGrid({ children, columns = 2 }: { children: ReactNode; columns?: 2 | 3 }) {
  return <div className={cx("ui-stat-grid", columns === 3 && "ui-stat-grid--3")}>{children}</div>;
}
