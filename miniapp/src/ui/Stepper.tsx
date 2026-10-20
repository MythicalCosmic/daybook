import { Minus, Plus } from "lucide-react";
import { useEffect, useRef, type PointerEvent } from "react";

import { useI18n } from "../i18n";
import { haptic } from "../telegram";
import { cx } from "./cx";

/**
 * Press-and-hold repeat for +/− buttons: one step on press, then faster steps while held.
 * Returns pointer handlers; a click from the keyboard still does exactly one step.
 */
function useRepeat(step: () => void) {
  const latest = useRef(step);
  latest.current = step;
  const timer = useRef<number | undefined>(undefined);
  const repeated = useRef(false);
  const stop = () => window.clearTimeout(timer.current);
  useEffect(() => stop, []);
  return {
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return;
      repeated.current = false;
      const tick = (delay: number) => {
        timer.current = window.setTimeout(() => {
          repeated.current = true;
          latest.current();
          tick(Math.max(60, delay * 0.8));
        }, delay);
      };
      tick(420);
    },
    onPointerUp: stop,
    onPointerLeave: stop,
    onPointerCancel: stop,
    /** The click that ends a hold has already been counted by the repeats. */
    shouldSkipClick: () => {
      const skip = repeated.current;
      repeated.current = false;
      return skip;
    },
  };
}

export function Stepper({
  value,
  onChange,
  min = 0,
  max = 9999,
  step = 1,
  label,
  editable = false,
  size = "md",
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  /** What is being counted, for screen readers. */
  label?: string;
  /** Let the person type the number too (counting 37 notes is quicker typed). */
  editable?: boolean;
  size?: "md" | "sm";
}) {
  const { t } = useI18n();
  const clamp = (next: number) => Math.min(max, Math.max(min, next));
  const current = useRef(value);
  current.current = value;
  const set = (next: number) => {
    const clamped = clamp(next);
    if (clamped === current.current) return;
    haptic.select();
    current.current = clamped;
    onChange(clamped);
  };
  const less = useRepeat(() => set(current.current - step));
  const more = useRepeat(() => set(current.current + step));

  const button = (kind: "less" | "more") => {
    const repeat = kind === "less" ? less : more;
    const { shouldSkipClick, ...handlers } = repeat;
    return (
      <button
        type="button"
        className="ui-stepper-btn"
        aria-label={t(kind === "less" ? "ui.stepper.decrease" : "ui.stepper.increase")}
        disabled={kind === "less" ? value <= min : value >= max}
        {...handlers}
        onClick={() => {
          if (shouldSkipClick()) return;
          set(current.current + (kind === "less" ? -step : step));
        }}
      >
        {kind === "less" ? <Minus size={18} strokeWidth={2.75} aria-hidden /> : <Plus size={18} strokeWidth={2.75} aria-hidden />}
      </button>
    );
  };

  return (
    <div className={cx("ui-stepper", size === "sm" && "ui-stepper--sm", value > min && "ui-stepper--active")} role="group" aria-label={label}>
      {button("less")}
      {editable ? (
        <input
          className="ui-stepper-input num"
          inputMode="numeric"
          aria-label={label}
          value={String(value)}
          onFocus={(event) => event.target.select()}
          onChange={(event) => {
            const digits = event.target.value.replace(/\D/g, "");
            set(digits ? Number(digits) : min);
          }}
        />
      ) : (
        <span className="ui-stepper-value num" aria-live="polite">
          {value}
        </span>
      )}
      {button("more")}
    </div>
  );
}
