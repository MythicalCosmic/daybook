import type { ReactNode } from "react";

import { haptic } from "../telegram";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

/** A selectable pill: categories, payment methods, quick filters. */
export function Chip({
  selected = false,
  onClick,
  icon,
  disabled,
  children,
}: {
  selected?: boolean;
  onClick?: () => void;
  icon?: IconLike;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button type="button" className="ui-chip" aria-pressed={selected} disabled={disabled} onClick={onClick}>
      {renderIcon(icon, 16, 2.5)}
      <span>{children}</span>
    </button>
  );
}

export type ChipOption<T extends string> = { value: T; label: ReactNode; icon?: IconLike };

/**
 * Pick one of a few options as chips (method chips, category chips "most used first").
 * `scroll` keeps them on one line that scrolls sideways to the screen edge.
 */
export function ChipGroup<T extends string>({
  options,
  value,
  onChange,
  allowNone = false,
  scroll = false,
  label,
}: {
  options: readonly ChipOption<T>[];
  value: T | null;
  onChange: (value: T | null) => void;
  /** Tapping the selected chip again clears the choice. */
  allowNone?: boolean;
  scroll?: boolean;
  label?: string;
}) {
  return (
    <div className={cx("ui-chips", scroll && "ui-chips--scroll")} role="group" aria-label={label}>
      {options.map((option) => (
        <Chip
          key={option.value}
          icon={option.icon}
          selected={option.value === value}
          onClick={() => {
            const next = option.value === value ? (allowNone ? null : value) : option.value;
            if (next === value) return;
            haptic.select();
            onChange(next);
          }}
        >
          {option.label}
        </Chip>
      ))}
    </div>
  );
}
