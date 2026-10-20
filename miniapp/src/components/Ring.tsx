const RADIUS = 27;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** The home screen's "3/10" progress ring. */
export function Ring({ done, total }: { done: number; total: number }) {
  const share = total ? done / total : 0;
  const label = `${done}/${total}`;
  // Longer counts, like a month of team work, get smaller so they stay inside the ring.
  const fontSize = label.length <= 4 ? 16 : label.length === 5 ? 13.5 : 11.5;
  return (
    <span style={{ position: "relative", width: 66, height: 66, flex: "none" }}>
      <svg viewBox="0 0 66 66" style={{ width: 66, height: 66, transform: "rotate(-90deg)" }} aria-hidden>
        <circle
          cx="33"
          cy="33"
          r={RADIUS}
          fill="none"
          stroke="color-mix(in srgb, var(--color-text) 10%, transparent)"
          strokeWidth="7"
        />
        <circle
          cx="33"
          cy="33"
          r={RADIUS}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - share)}
          style={{ transition: "stroke-dashoffset 0.6s cubic-bezier(.2,.8,.2,1)" }}
        />
      </svg>
      <span
        className="num"
        style={{
          position: "absolute",
          inset: 0,
          display: "grid",
          placeItems: "center",
          fontSize,
          fontWeight: 700,
        }}
      >
        {label}
      </span>
    </span>
  );
}
