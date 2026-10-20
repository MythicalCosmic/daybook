import type { ComponentPropsWithRef, ReactNode } from "react";

import { haptic as feel } from "../telegram";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

export type ButtonVariant = "primary" | "secondary" | "ghost";

export type ButtonProps = Omit<ComponentPropsWithRef<"button">, "children"> & {
  variant?: ButtonVariant;
  /** "lg" is the 56 px call to action at the bottom of sheets and screens. */
  size?: "md" | "lg";
  block?: boolean;
  icon?: IconLike;
  /** Spinner in place of the icon; the button can't be pressed meanwhile. */
  loading?: boolean;
  /** Feedback on press: a light tap, a success buzz, or a selection tick. */
  haptic?: false | "light" | "success" | "select";
  children?: ReactNode;
};

/** A small spinning ring in the current text color. */
export function Spinner({ size = 18 }: { size?: number }) {
  return <span className="ui-spinner" style={{ width: size, height: size }} aria-hidden />;
}

/** The app's pill buttons (`.btn`): primary terracotta, secondary outlined, ghost text. */
export function Button({
  variant = "secondary",
  size = "md",
  block,
  icon,
  loading = false,
  haptic = false,
  className,
  disabled,
  onClick,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  const iconSize = size === "lg" ? 20 : 17;
  const leading = loading ? <Spinner size={iconSize} /> : renderIcon(icon, iconSize, size === "lg" ? 3 : 2.6);
  return (
    <button
      type={type}
      className={cx("btn", `btn-${variant}`, size === "lg" && "btn-lg", block && "btn-block", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      onClick={(event) => {
        if (haptic === "select") feel.select();
        else if (haptic) feel(haptic);
        onClick?.(event);
      }}
      {...rest}
    >
      {leading}
      {leading ? children !== undefined && <span>{children}</span> : children}
    </button>
  );
}

export type IconButtonProps = Omit<ButtonProps, "children" | "block" | "size" | "icon"> & {
  icon: IconLike;
  /** Read by screen readers; icon buttons have no visible text. */
  label: string;
  size?: number;
};

/** A round icon-only button (send, back, close). */
export function IconButton({ icon, label, size = 48, variant = "secondary", className, style, ...rest }: IconButtonProps) {
  return (
    <Button
      {...rest}
      variant={variant}
      className={cx("btn-icon", className)}
      style={size === 48 ? style : { width: size, height: size, ...style }}
      aria-label={label}
      icon={renderIcon(icon, Math.round(size * 0.42), 2.5) ?? undefined}
    />
  );
}
