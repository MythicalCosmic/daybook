import type { ReactNode } from "react";

import { cx } from "./cx";

/**
 * A round progress ring with a label inside: the home "3/8", a team's on-time share, a project's
 * progress. The defaults draw the original 66 px home ring exactly.
 */
export function ProgressRing({
  value,
  total,
  size = 66,
  stroke = 7,
  tone = "accent",
  label,
  ariaLabel,
}: {
  value: number;
  total: number;
  size?: number;
  stroke?: number;
  tone?: "accent" | "sage";
  /** Inside the ring; defaults to "value/total". */
  label?: ReactNode;
  ariaLabel?: string;
}) {
  // 2.5 px of breathing room keeps the round caps clear of the edge.
  const radius = (size - stroke) / 2 - 2.5;
  const circumference = 2 * Math.PI * radius;
  const share = total ? Math.min(1, Math.max(0, value / total)) : 0;
  const text = label ?? `${value}/${total}`;
  const length = typeof text === "string" ? text.length : 4;
  // Longer counts, like a month of team work, get smaller so they stay inside the ring.
  const fontSize = ((length <= 4 ? 16 : length === 5 ? 13.5 : 11.5) * size) / 66;
  const center = size / 2;
  return (
    <span className="ui-ring" style={{ width: size, height: size }} role={ariaLabel ? "img" : undefined} aria-label={ariaLabel}>
      <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }} aria-hidden>
        <circle cx={center} cy={center} r={radius} fill="none" stroke="color-mix(in srgb, var(--color-text) 10%, transparent)" strokeWidth={stroke} />
        <circle
          className="ui-ring-value"
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={tone === "sage" ? "var(--color-accent-2)" : "var(--color-accent)"}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - share)}
        />
      </svg>
      <span className="ui-ring-label num" style={{ fontSize }}>
        {text}
      </span>
    </span>
  );
}

/**
 * A horizontal bar: bonus progress ("On time 93% → 95% gives +300 000"), budget burn, leave
 * balance. `target` draws a marker; going past `total` turns the bar terracotta.
 */
export function ProgressBar({
  value,
  total = 100,
  target,
  tone = "accent",
  label,
  valueLabel,
  caption,
  size = "md",
  ariaLabel,
}: {
  value: number;
  total?: number;
  target?: number;
  tone?: "accent" | "sage";
  label?: ReactNode;
  /** Right-hand text on the label line ("93%"). */
  valueLabel?: ReactNode;
  /** A line under the bar ("2% more gives +300 000 so‘m"). */
  caption?: ReactNode;
  size?: "sm" | "md";
  ariaLabel?: string;
}) {
  const percent = total > 0 ? (value / total) * 100 : 0;
  const over = percent > 100;
  const targetPercent = target !== undefined && total > 0 ? Math.min(100, Math.max(0, (target / total) * 100)) : null;
  return (
    <div className="ui-bar-block">
      {(label || valueLabel) && (
        <div className="ui-bar-head">
          <span>{label}</span>
          {valueLabel !== undefined && <span className="num">{valueLabel}</span>}
        </div>
      )}
      <div
        className={cx("ui-bar", `ui-bar--${tone}`, size === "sm" && "ui-bar--sm", over && "ui-bar--over")}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={value}
        aria-label={ariaLabel ?? (typeof label === "string" ? label : undefined)}
      >
        <span className="ui-bar-fill" style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
        {targetPercent !== null && <span className="ui-bar-target" style={{ left: `${targetPercent}%` }} />}
      </div>
      {caption && <div className="ui-bar-caption">{caption}</div>}
    </div>
  );
}
