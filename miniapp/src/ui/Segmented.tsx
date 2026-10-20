import { useRef, type KeyboardEvent, type ReactNode } from "react";

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

const STEP: Partial<Record<string, 1 | -1>> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/**
 * A pill switch between a few options. `role="tablist"` when it switches what the screen shows
 * (Tasks tabs), radios otherwise (theme, period). Like native radios, only the chosen option is
 * a Tab stop, and the arrow keys (Home, End) move the choice.
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
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  const enabled = options.filter((option) => !option.disabled);
  // The chosen option is the Tab stop; when it can't take focus, the first enabled one is.
  const tabStop = enabled.some((option) => option.value === value) ? value : enabled[0]?.value;

  const choose = (next: T) => {
    if (next === value) return;
    haptic.select();
    onChange(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!enabled.length) return;
    const at = enabled.findIndex((option) => option.value === value);
    const step = STEP[event.key];
    let next: number | null = null;
    if (step) next = at < 0 ? 0 : (at + step + enabled.length) % enabled.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = enabled.length - 1;
    if (next === null) return;
    event.preventDefault();
    const target = enabled[next].value;
    buttons.current.get(target)?.focus();
    choose(target);
  };

  return (
    <div
      className={cx("seg", size === "small" && "seg--small", fit && "seg--fit", className)}
      role={role}
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(element) => {
              if (element) buttons.current.set(option.value, element);
              else buttons.current.delete(option.value);
            }}
            type="button"
            className="seg-opt"
            role={tabs ? "tab" : "radio"}
            aria-selected={tabs ? selected : undefined}
            aria-checked={tabs ? undefined : selected}
            tabIndex={option.value === tabStop ? 0 : -1}
            disabled={option.disabled}
            onClick={() => choose(option.value)}
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
