import type { ReactNode } from "react";

import { haptic } from "../telegram";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

export type SegmentOption<T extends string> = {
  value: T;
  label: ReactNode;
  /** A muted number after the label (open tasks per tab); hidden when 0. */
  count?: number;
  icon?: IconLike;
  disabled?: boolean;
};

/**
 * A pill switch between a few options. `role="tablist"` when it switches what the screen shows
 * (Tasks tabs), radios otherwise (theme, period).
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  fit = false,
  role = "radiogroup",
  label,
  className,
}: {
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** small sits inside a list row (theme picker). */
  size?: "md" | "small";
  /** Options as wide as their labels, for long words in some languages. */
  fit?: boolean;
  role?: "radiogroup" | "tablist";
  label?: string;
  className?: string;
}) {
  const tabs = role === "tablist";
  return (
    <div className={cx("seg", size === "small" && "seg--small", fit && "seg--fit", className)} role={role} aria-label={label}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            className="seg-opt"
            role={tabs ? "tab" : "radio"}
            aria-selected={tabs ? selected : undefined}
            aria-checked={tabs ? undefined : selected}
            disabled={option.disabled}
            onClick={() => {
              if (selected) return;
              haptic.select();
              onChange(option.value);
            }}
          >
            {renderIcon(option.icon, 16, 2.5)}
            <span>{option.label}</span>
            {option.count ? <span className="count">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
