import { Check, ChevronsRight } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { haptic } from "../telegram";
import { Spinner } from "./Button";
import { cx } from "./cx";
import { renderIcon, type IconLike } from "./icon";

const KNOB = 56;
const INSET = 4;
/** How far (share of the track) the knob must travel to count. */
const THRESHOLD = 0.88;

export type SlideState = "idle" | "loading" | "done";

/**
 * A deliberate action that a stray tap can't trigger: drag the knob to the end (check in, close
 * the till, sign). Keyboard and screen-reader users press the knob with Enter or Space.
 * The parent owns `state`: "loading" while the request runs, "done" after, back to "idle" on
 * failure (the knob slides home).
 */
export function SlideToConfirm({
  label,
  doneLabel,
  onConfirm,
  state = "idle",
  tone = "accent",
  icon,
  disabled = false,
}: {
  label: ReactNode;
  doneLabel?: ReactNode;
  onConfirm: () => void;
  state?: SlideState;
  tone?: "accent" | "sage";
  icon?: IconLike;
  disabled?: boolean;
}) {
  const labelId = useId();
  const track = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [max, setMax] = useState(0);
  const start = useRef<{ x: number; offset: number } | null>(null);
  const armed = useRef(false);

  useLayoutEffect(() => {
    const element = track.current;
    if (!element) return;
    const measure = () => setMax(Math.max(0, element.clientWidth - KNOB - INSET * 2));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // The parent decides where the knob rests: at the end while busy or done, home otherwise.
  useEffect(() => {
    if (!dragging) setOffset(state === "idle" ? 0 : max);
  }, [state, max, dragging]);

  const locked = disabled || state !== "idle";

  const confirm = () => {
    setOffset(max);
    haptic.notify("success");
    onConfirm();
  };

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (locked) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = { x: event.clientX, offset };
    armed.current = false;
    setDragging(true);
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (!start.current) return;
    const next = Math.min(max, Math.max(0, start.current.offset + event.clientX - start.current.x));
    const past = next >= max * THRESHOLD;
    if (past !== armed.current) {
      armed.current = past;
      if (past) haptic.impact("light");
    }
    setOffset(next);
  };

  const onPointerEnd = () => {
    if (!start.current) return;
    start.current = null;
    setDragging(false);
    if (armed.current && max > 0) confirm();
    else setOffset(0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (locked || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    confirm();
  };

  const progress = max > 0 ? offset / max : 0;
  return (
    <div
      ref={track}
      className={cx("ui-slide", `ui-slide--${tone}`, dragging && "is-dragging", state !== "idle" && `is-${state}`, disabled && "is-disabled")}
    >
      <span className="ui-slide-fill" style={{ width: offset + KNOB + INSET * 2 }} />
      {/* Hidden from the reading order (the knob reads it out instead), but still its name. */}
      <span id={labelId} className="ui-slide-label" style={{ opacity: state === "idle" ? 1 - Math.min(1, progress * 1.6) : 1 }} aria-hidden>
        {state === "done" && doneLabel ? doneLabel : label}
      </span>
      <button
        type="button"
        className="ui-slide-knob"
        style={{ transform: `translateX(${offset}px)` }}
        aria-labelledby={labelId}
        aria-disabled={locked || undefined}
        aria-busy={state === "loading" || undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onKeyDown={onKeyDown}
      >
        {state === "loading" ? (
          <Spinner size={22} />
        ) : state === "done" ? (
          <Check size={24} strokeWidth={3} aria-hidden />
        ) : (
          renderIcon(icon, 24, 2.6) ?? <ChevronsRight size={26} strokeWidth={2.6} aria-hidden />
        )}
      </button>
    </div>
  );
}
