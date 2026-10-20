/** The app's mark from the design: a terracotta sun with a tick, and a sage pebble. */
export function Mark({ size = 50, animated = false }: { size?: number; animated?: boolean }) {
  const scale = size / 50;
  return (
    <div
      className={animated ? "mark mark--animated" : "mark"}
      style={{ width: size, height: size, position: "relative", flex: "none" }}
      aria-hidden
    >
      <div
        className="mark-sun"
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: 42 * scale,
          height: 42 * scale,
          borderRadius: "50%",
          background: "var(--color-accent)",
          display: "grid",
          placeItems: "center",
        }}
      >
        <svg
          viewBox="0 0 24 24"
          style={{
            width: 24 * scale,
            height: 24 * scale,
            fill: "none",
            stroke: "var(--color-bg)",
            strokeWidth: 3,
            strokeLinecap: "round",
            strokeLinejoin: "round",
          }}
        >
          <path className="mark-check" d="M5 12.5 10 17.5 19 7.5" />
        </svg>
      </div>
      <div
        className="mark-pebble"
        style={{
          position: "absolute",
          right: 0,
          bottom: 0,
          width: 22 * scale,
          height: 22 * scale,
          borderRadius: "50%",
          background: "var(--color-accent-2)",
          boxShadow: "0 0 0 3px var(--color-bg)",
        }}
      />
    </div>
  );
}
