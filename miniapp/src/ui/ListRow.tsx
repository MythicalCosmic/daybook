import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { CountBadge } from "./Badge";
import { Card } from "./Card";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

export type ListRowProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: IconLike;
  /** Text on the right (a date, an amount, a state). */
  value?: ReactNode;
  /** A count bubble before the chevron. */
  badge?: number | null;
  /** Shown by default when the row opens something. */
  chevron?: boolean;
  onClick?: () => void;
  /**
   * inset: a line inside a `ListCard` (settings, Me entries). card: a standalone surface row with
   * a round icon (feeds, people, documents).
   */
  variant?: "inset" | "card";
  /** Tint of the round icon in card rows. */
  tone?: "plain" | "accent" | "sage";
  /** Subtitle in terracotta, for things that need attention. */
  alert?: boolean;
  disabled?: boolean;
  className?: string;
};

export function ListRow({
  title,
  subtitle,
  icon,
  value,
  badge,
  chevron,
  onClick,
  variant = "inset",
  tone = "plain",
  alert = false,
  disabled,
  className,
}: ListRowProps) {
  const showChevron = chevron ?? Boolean(onClick);
  const tappable = Boolean(onClick);

  if (variant === "card") {
    const content = (
      <>
        {icon && <span className={cx("circle ui-row-icon", tone !== "plain" && `ui-row-icon--${tone}`)}>{renderIcon(icon, 19)}</span>}
        <span className="row-main">
          <span className="row-title">{title}</span>
          {subtitle && <span className={cx("row-meta", alert && "row-meta--alert")}>{subtitle}</span>}
        </span>
        {value !== undefined && value !== null && <span className="ui-row-value num">{value}</span>}
        <CountBadge count={badge} />
        {showChevron && <ChevronRight className="ui-row-chevron" size={19} strokeWidth={2.5} aria-hidden />}
      </>
    );
    return tappable ? (
      <button type="button" className={cx("row", className)} onClick={onClick} disabled={disabled}>
        {content}
      </button>
    ) : (
      <div className={cx("row row--static", className)}>{content}</div>
    );
  }

  const label = (
    <span className="list-item-label">
      {renderIcon(icon, 20)}
      {subtitle ? (
        <span className="list-item-text">
          <span>{title}</span>
          <span className={cx("list-item-sub", alert && "row-meta--alert")}>{subtitle}</span>
        </span>
      ) : (
        title
      )}
    </span>
  );
  const right =
    value !== undefined || badge || showChevron ? (
      <span className="list-item-value">
        {value}
        <CountBadge count={badge} />
        {showChevron && <ChevronRight size={18} strokeWidth={2.5} aria-hidden />}
      </span>
    ) : null;
  const classes = cx("list-item", subtitle && "list-item--two-line", className);
  return tappable ? (
    <button type="button" className={classes} onClick={onClick} disabled={disabled}>
      {label}
      {right}
    </button>
  ) : (
    <div className={classes}>
      {label}
      {right}
    </div>
  );
}

/** The card that holds inset rows, with hairlines between them. */
export function ListCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <Card padding="list" className={className}>
      {children}
    </Card>
  );
}
