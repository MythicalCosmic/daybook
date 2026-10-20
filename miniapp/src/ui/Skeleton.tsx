import { useEffect, useState, type CSSProperties } from "react";

import { cx } from "./cx";

/** A shimmering placeholder block (`.skeleton`). */
export function Skeleton({
  height,
  width,
  radius,
  className,
  style,
}: {
  height: number | string;
  width?: number | string;
  radius?: number | string;
  className?: string;
  style?: CSSProperties;
}) {
  return <div className={cx("skeleton", className)} style={{ height, width, borderRadius: radius, ...style }} aria-hidden />;
}

/** Rows of list placeholders, as tall as task rows by default. */
export function SkeletonList({ count = 3, height = 68 }: { count?: number; height?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <Skeleton key={index} height={height} />
      ))}
    </>
  );
}

/** Lines of text: the last one shorter, like a paragraph. */
export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="ui-skeleton-text" aria-hidden>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} height={14} radius={7} width={index === lines - 1 ? "62%" : "100%"} />
      ))}
    </div>
  );
}

/** True once `ms` have passed, so quick loads never flash a skeleton. */
export function useDelay(ms: number): boolean {
  const [ready, setReady] = useState(ms <= 0);
  useEffect(() => {
    if (ms <= 0) return;
    const timer = window.setTimeout(() => setReady(true), ms);
    return () => window.clearTimeout(timer);
  }, [ms]);
  return ready;
}

export type ScreenSkeletonVariant = "hero" | "list" | "detail" | "table" | "payslip";

/**
 * Placeholders shaped like the screen that is loading: the home hero, a task list, a detail
 * page, the team table or a payslip. `delay` (ms) waits before showing anything; the polish
 * pass uses 150.
 */
export function ScreenSkeleton({ variant, delay = 0, rows }: { variant: ScreenSkeletonVariant; delay?: number; rows?: number }) {
  const ready = useDelay(delay);
  if (!ready) return null;
  switch (variant) {
    case "hero":
      return (
        <>
          <Skeleton height={98} radius="calc(var(--radius-lg) * 1.15)" />
          <Skeleton height={70} />
          <Skeleton height={22} width="38%" radius={8} style={{ marginTop: "var(--space-3)" }} />
          <SkeletonList count={rows ?? 3} />
        </>
      );
    case "list":
      return <SkeletonList count={rows ?? 4} />;
    case "detail":
      return (
        <>
          <Skeleton height={40} width="60%" />
          <Skeleton height={120} />
          <Skeleton height={180} />
        </>
      );
    case "table":
      return (
        <>
          <Skeleton height={132} />
          <SkeletonList count={rows ?? 5} height={64} />
        </>
      );
    case "payslip":
      return (
        <>
          <Skeleton height={148} radius="calc(var(--radius-lg) * 1.15)" />
          <div className="card ui-skeleton-lines" aria-hidden>
            {Array.from({ length: rows ?? 6 }, (_, index) => (
              <div key={index} className="ui-skeleton-line">
                <Skeleton height={14} width={`${42 + ((index * 17) % 30)}%`} radius={7} />
                <Skeleton height={14} width="22%" radius={7} />
              </div>
            ))}
          </div>
          <Skeleton height={64} />
        </>
      );
  }
}
