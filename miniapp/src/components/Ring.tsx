const RADIUS = 27;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** The home screen's "3/10" progress ring. */
export function Ring({ done, total }: { done: number; total: number }) {
  const share = total ? done / total : 0;
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
          fontSize: 16,
          fontWeight: 700,
        }}
      >
        {done}/{total}
      </span>
    </span>
  );
}
