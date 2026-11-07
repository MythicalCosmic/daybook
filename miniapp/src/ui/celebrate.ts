/**
 * Little celebrations (docs/PLAN-LEARNING.md §12.3): a burst of confetti over the screen and a
 * success buzz, for a passed quiz, a finished course, a new level or badge, a task done on time.
 *
 *   celebrate();                                  // confetti from the top centre + success haptic
 *   celebrate({ from: buttonRef.current, pieces: 40 });   // from a button, smaller
 *
 * One canvas per burst, removed when the last piece falls (about 1.6 s); nothing is drawn when the
 * person asked for reduced motion (the haptic still plays), and nothing at all outside a browser.
 * No dependency: ~80 rectangles under requestAnimationFrame.
 */
import { haptic } from "../telegram";

export type CelebrateOptions = {
  /** Where the burst starts: an element (its centre) or a point; default the top centre. */
  from?: Element | { x: number; y: number } | null;
  /** How many pieces (default 80). */
  pieces?: number;
  /** The buzz: "success" (default), "light" or none. */
  haptic?: "success" | "light" | null;
};

const COLORS = ["#2f9e6e", "#f4b740", "#ef5d60", "#4f8ff7", "#a970ff", "#ff8fb1"];
const DURATION_MS = 1600;
const GRAVITY = 0.0016;

type Piece = { x: number; y: number; vx: number; vy: number; size: number; spin: number; angle: number; color: string };

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function origin(from: CelebrateOptions["from"]): { x: number; y: number } {
  if (from && "getBoundingClientRect" in from) {
    const box = from.getBoundingClientRect();
    return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
  }
  if (from && "x" in from) return from;
  return { x: window.innerWidth / 2, y: Math.min(120, window.innerHeight / 4) };
}

/** Confetti and a buzz. Returns a function that stops the burst early (for tests and unmounts). */
export function celebrate(options: CelebrateOptions = {}): () => void {
  const buzz = options.haptic === undefined ? "success" : options.haptic;
  if (buzz) haptic(buzz);
  if (typeof document === "undefined" || prefersReducedMotion()) return () => {};
  const canvas = document.createElement("canvas");
  const context = canvas.getContext?.("2d");
  if (!context) return () => {};
  const ratio = window.devicePixelRatio || 1;
  canvas.width = window.innerWidth * ratio;
  canvas.height = window.innerHeight * ratio;
  canvas.setAttribute("aria-hidden", "true");
  canvas.className = "celebrate-canvas";
  Object.assign(canvas.style, { position: "fixed", inset: "0", width: "100%", height: "100%", pointerEvents: "none", zIndex: "9999" });
  document.body.appendChild(canvas);
  context.scale(ratio, ratio);

  const start = origin(options.from);
  const pieces: Piece[] = Array.from({ length: options.pieces ?? 80 }, (_, index) => {
    const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 0.9;
    const speed = 0.35 + Math.random() * 0.55;
    return {
      x: start.x,
      y: start.y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      size: 5 + Math.random() * 5,
      spin: (Math.random() - 0.5) * 0.02,
      angle: Math.random() * Math.PI,
      color: COLORS[index % COLORS.length],
    };
  });

  let frame = 0;
  let last = performance.now();
  const began = last;
  const stop = () => {
    cancelAnimationFrame(frame);
    canvas.remove();
  };
  const step = (now: number) => {
    const dt = Math.min(32, now - last);
    last = now;
    const left = 1 - (now - began) / DURATION_MS;
    if (left <= 0) return stop();
    context.clearRect(0, 0, window.innerWidth, window.innerHeight);
    context.globalAlpha = Math.min(1, left * 2);
    for (const piece of pieces) {
      piece.vy += GRAVITY * dt;
      piece.x += piece.vx * dt;
      piece.y += piece.vy * dt;
      piece.angle += piece.spin * dt;
      context.save();
      context.translate(piece.x, piece.y);
      context.rotate(piece.angle);
      context.fillStyle = piece.color;
      context.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
      context.restore();
    }
    frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return stop;
}
