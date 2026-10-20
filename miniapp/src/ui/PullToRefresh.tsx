import { ArrowDown } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useI18n } from "../i18n";
import { haptic } from "../telegram";
import { Spinner } from "./Button";
import { cx } from "./cx";

/** Pull distance (after resistance) that triggers a refresh. */
const TRIGGER = 64;
const MAX = 110;

/**
 * A scrolling screen you can pull down to refresh (the body has `overscroll-behavior: none`, so
 * the gesture is ours). It renders the scroll container itself: pass the screen's classes.
 */
export function PullToRefresh({
  onRefresh,
  className = "screen fade-in",
  disabled = false,
  children,
}: {
  onRefresh: () => Promise<unknown>;
  className?: string;
  disabled?: boolean;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const state = useRef({ startY: null as number | null, pull: 0, refreshing: false, armed: false });
  const refresh = useRef(onRefresh);
  refresh.current = onRefresh;

  useEffect(() => {
    const element = container.current;
    if (!element || disabled) return;
    const current = state.current;

    const set = (value: number) => {
      current.pull = value;
      setPull(value);
    };
    const onStart = (event: TouchEvent) => {
      if (current.refreshing || element.scrollTop > 0 || event.touches.length !== 1) return;
      current.startY = event.touches[0].clientY;
      current.armed = false;
    };
    const onMove = (event: TouchEvent) => {
      if (current.startY === null) return;
      const distance = event.touches[0].clientY - current.startY;
      if (distance <= 0 || element.scrollTop > 0) {
        if (current.pull) set(0);
        return;
      }
      // Ours now: stop the page (and Telegram) from scrolling, and add resistance.
      if (event.cancelable) event.preventDefault();
      const next = Math.min(MAX, distance * 0.5);
      const armed = next >= TRIGGER;
      if (armed !== current.armed) {
        current.armed = armed;
        if (armed) haptic.impact("light");
      }
      set(next);
    };
    const onEnd = async () => {
      if (current.startY === null) return;
      current.startY = null;
      if (!current.armed) {
        set(0);
        return;
      }
      current.refreshing = true;
      setRefreshing(true);
      set(TRIGGER * 0.8);
      try {
        await refresh.current();
        haptic.select();
      } finally {
        current.refreshing = false;
        current.armed = false;
        setRefreshing(false);
        set(0);
      }
    };

    element.addEventListener("touchstart", onStart, { passive: true });
    element.addEventListener("touchmove", onMove, { passive: false });
    element.addEventListener("touchend", onEnd);
    element.addEventListener("touchcancel", onEnd);
    return () => {
      element.removeEventListener("touchstart", onStart);
      element.removeEventListener("touchmove", onMove);
      element.removeEventListener("touchend", onEnd);
      element.removeEventListener("touchcancel", onEnd);
    };
  }, [disabled]);

  const progress = Math.min(1, pull / TRIGGER);
  const caption = refreshing ? t("ui.pull.refreshing") : progress >= 1 ? t("ui.pull.release") : t("ui.pull.pull");
  return (
    <>
      <div
        className={cx("ui-ptr", (pull > 0 || refreshing) && "is-visible", state.current.startY === null && "is-settling")}
        style={{ transform: `translate(-50%, ${pull - 44}px)`, opacity: refreshing ? 1 : progress }}
        role="status"
        aria-label={caption}
      >
        {refreshing ? <Spinner size={18} /> : <ArrowDown size={18} strokeWidth={2.6} style={{ transform: `rotate(${progress >= 1 ? 180 : 0}deg)` }} aria-hidden />}
      </div>
      <div
        ref={container}
        className={cx(className, "ui-ptr-scroll", state.current.startY === null && "is-settling")}
        style={pull ? { transform: `translateY(${pull}px)` } : undefined}
      >
        {children}
      </div>
    </>
  );
}
