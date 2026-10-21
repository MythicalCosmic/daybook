import { ArrowLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../i18n";
import { hasNativeBackButton } from "../telegram";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

/**
 * A scrolling screen. "tab" screens fade in and leave room for the tab bar; "detail" screens sit
 * in a pushed page and leave room for an action bar; "plain" ones have neither (gates, errors).
 */
export function Screen({
  variant = "tab",
  className,
  children,
}: {
  variant?: "tab" | "detail" | "plain";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cx("screen", variant === "tab" && "fade-in", variant === "detail" && "screen--detail", variant === "plain" && "screen--plain fade-in", className)}>
      {children}
    </div>
  );
}

/**
 * The top of a pushed page: a small line above (company, feature), the Caprasimo title and a
 * subline. Telegram draws the back button; when it can't, `onBack` shows one here.
 */
export function PageHeader({
  title,
  kicker,
  subtitle,
  onBack,
  actions,
}: {
  title: ReactNode;
  kicker?: ReactNode;
  subtitle?: ReactNode;
  onBack?: () => void;
  /** Buttons on the right of the title. */
  actions?: ReactNode;
}) {
  const { t } = useI18n();
  const inlineBack = onBack && !hasNativeBackButton();
  return (
    <div className="ui-page-head">
      {inlineBack && (
        <button type="button" className="btn btn-secondary btn-icon ui-back" aria-label={t("ui.back")} onClick={onBack}>
          <ArrowLeft size={20} strokeWidth={2.5} aria-hidden />
        </button>
      )}
      <div className="ui-page-head-row">
        <div className="ui-page-head-text">
          {kicker && <div className="ui-page-kicker">{kicker}</div>}
          <h1 className="heading ui-page-title">{title}</h1>
          {subtitle && <div className="subline">{subtitle}</div>}
        </div>
        {actions && <div className="ui-page-actions">{actions}</div>}
      </div>
    </div>
  );
}

/** A heading between blocks, with an optional count and a "See all" style action on the right. */
export function SectionHead({
  children,
  count,
  action,
  size = "md",
}: {
  children: ReactNode;
  count?: number;
  action?: { label: ReactNode; onClick: () => void };
  size?: "md" | "small";
}) {
  return (
    <div className={cx("section-head", size === "small" && "section-head--small", count !== undefined && "section-head--count")}>
      <span>{children}</span>
      {count !== undefined && <span className="tag tag-neutral tag-small">{count}</span>}
      {action && (
        <button type="button" className="btn btn-ghost section-head-action" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}

export type BannerTone = "plain" | "accent" | "sage";

/**
 * A full-width notice. "lg" is the Home style (42 px circle, bold title, one-line body, chevron
 * when it opens something); "md" is the detail style (small icon, wrapping note).
 *
 * Home's rule: a tinted `tone` is for what can't wait (late work, cash to confirm: accent) or the
 * shape of the day (off today: sage); requests and reminders stay on the plain surface and get
 * their colour from the circle (`iconTone`), so a busy Home stays calm.
 */
export function Banner({
  tone = "plain",
  iconTone,
  size = "md",
  icon,
  title,
  body,
  wrap = false,
  onClick,
  chevron,
  className,
}: {
  tone?: BannerTone;
  /** The lg circle's colour on a plain banner (a tinted banner's circle follows its tone). */
  iconTone?: "accent" | "sage";
  size?: "md" | "lg";
  icon?: IconLike;
  title: ReactNode;
  body?: ReactNode;
  /** Let the body wrap instead of ending in an ellipsis (lg). */
  wrap?: boolean;
  onClick?: () => void;
  chevron?: boolean;
  className?: string;
}) {
  const classes = cx(
    "banner",
    tone !== "plain" && `banner--${tone}`,
    size === "lg" && "banner--lg",
    size === "md" && body && "banner--top",
    onClick && "banner--tap",
    className,
  );
  const content =
    size === "lg" ? (
      <>
        {icon && <span className={cx("circle banner-circle", iconTone && `banner-circle--${iconTone}`)}>{renderIcon(icon, 21)}</span>}
        <span className="row-main">
          <span className="banner-title">{title}</span>
          {body && <span className={cx("row-meta banner-body", wrap && "row-meta--wrap")}>{body}</span>}
        </span>
        {(chevron ?? Boolean(onClick)) && <ChevronRight size={20} strokeWidth={2.5} aria-hidden />}
      </>
    ) : (
      <>
        {icon && <span className="banner-icon">{renderIcon(icon, 17, 2.6)}</span>}
        <span className="ui-banner-text">
          <span className="ui-banner-title num">{title}</span>
          {body && <span className="ui-banner-body">{body}</span>}
        </span>
        {(chevron ?? false) && <ChevronRight className="ui-banner-chevron" size={19} strokeWidth={2.5} aria-hidden />}
      </>
    );
  return onClick ? (
    <button type="button" className={classes} onClick={onClick}>
      {content}
    </button>
  ) : (
    <div className={classes}>{content}</div>
  );
}
