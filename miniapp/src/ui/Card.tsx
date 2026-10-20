import type { ComponentPropsWithRef, ReactNode } from "react";

import { cx } from "./cx";

export type CardTone = "plain" | "accent" | "sage" | "outline";

type CardLook = {
  /** plain: sand surface; accent: soft terracotta (streaks, late work); sage: soft green; outline: hairline only. */
  tone?: CardTone;
  /** "row" lays children side by side, like the home progress card. */
  layout?: "column" | "row";
  /** md is the default 18×20 padding; list is for ListRow stacks; flush has none. */
  padding?: "md" | "sm" | "lg" | "list" | "flush";
};

function cardClass({ tone = "plain", layout = "column", padding = "md" }: CardLook, extra?: string): string {
  return cx(
    "card",
    tone !== "plain" && `card--${tone}`,
    layout === "row" && "card--row",
    padding === "list" ? "list-card" : padding !== "md" && `card--${padding}`,
    extra,
  );
}

export type CardProps = ComponentPropsWithRef<"div"> & CardLook;

/** The rounded surface everything sits on. */
export function Card({ tone, layout, padding, className, ...rest }: CardProps) {
  return <div className={cardClass({ tone, layout, padding }, className)} {...rest} />;
}

export type CardButtonProps = ComponentPropsWithRef<"button"> & CardLook;

/** A card that is one big tap target (opens a page), with a gentle press. */
export function CardButton({ tone, layout, padding, className, type = "button", ...rest }: CardButtonProps) {
  return <button type={type} className={cardClass({ tone, layout, padding }, cx("card--tap", className))} {...rest} />;
}

export function CardTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  if (!action) return <div className="card-title">{children}</div>;
  return (
    <div className="ui-card-head">
      <span className="card-title">{children}</span>
      {action}
    </div>
  );
}
