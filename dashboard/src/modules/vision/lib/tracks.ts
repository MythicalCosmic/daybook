/**
 * The live overlay between two frames (docs/KOZ.md §5.6, §6.3). Frames come about twice a second;
 * the boxes glide from where they were to where the new frame puts them instead of jumping: people
 * are matched by `track`, a box that is in both frames moves, a new one fades in where it appears
 * and one that left fades out where it was last seen. Waits keep ticking every second between
 * frames, counted from when the frame arrived (the browser's clock, never the server's).
 */
import { easeOutCubic } from "@/lib/useTween";

import type { FramePerson } from "../types";

export type Box = [number, number, number, number];

export interface DrawnPerson extends FramePerson {
  /** 0..1: fading in (entered), 1 (kept), fading out (left). */
  opacity: number;
  state: "kept" | "entered" | "left";
}

export interface TrackMatch {
  kept: Array<{ from: FramePerson; to: FramePerson }>;
  entered: FramePerson[];
  left: FramePerson[];
}

/** Pairs the people of two frames by track id. */
export function matchTracks(previous: readonly FramePerson[], next: readonly FramePerson[]): TrackMatch {
  const before = new Map(previous.map((person) => [person.track, person]));
  const kept: TrackMatch["kept"] = [];
  const entered: FramePerson[] = [];
  for (const person of next) {
    const from = before.get(person.track);
    if (from) {
      kept.push({ from, to: person });
      before.delete(person.track);
    } else entered.push(person);
  }
  return { kept, entered, left: [...before.values()] };
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function lerpBox(a: Box, b: Box, t: number): Box {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t), lerp(a[3], b[3], t)];
}

/**
 * The people to draw at progress `t` (0 = the previous frame, 1 = the new one) of the glide. The
 * new frame's role, zone and wait show at once (they are facts of the new picture); only the box
 * moves. A person who left keeps the last box and fades out.
 */
export function interpolate(previous: readonly FramePerson[], next: readonly FramePerson[], t: number, ease: (t: number) => number = easeOutCubic): DrawnPerson[] {
  const progress = Math.min(1, Math.max(0, t));
  const eased = ease(progress);
  const { kept, entered, left } = matchTracks(previous, next);
  const out: DrawnPerson[] = [];
  for (const { from, to } of kept) out.push({ ...to, box: lerpBox(from.box, to.box, eased), opacity: 1, state: "kept" });
  for (const person of entered) out.push({ ...person, opacity: eased, state: "entered" });
  for (const person of left) out.push({ ...person, opacity: 1 - eased, state: "left" });
  // Farther people (higher in the picture) first, so nearer boxes draw over them.
  return out.filter((person) => person.opacity > 0.001).sort((a, b) => a.box[1] + a.box[3] - (b.box[1] + b.box[3]) || a.track - b.track);
}

/** How long one glide takes: a little less than the time between frames, within limits. */
export function glideDuration(interval: number | null): number {
  if (!interval || !Number.isFinite(interval)) return 420;
  return Math.round(Math.min(900, Math.max(180, interval * 0.85)));
}

/**
 * A wait that keeps counting between reports: the seconds the report said, plus the whole seconds
 * since it arrived. Null stays null (not in a queue zone). Never below the reported value.
 */
export function tickingWait(waitS: number | null | undefined, receivedAt: number, now: number): number | null {
  if (waitS === null || waitS === undefined || !Number.isFinite(waitS)) return null;
  const elapsed = Math.max(0, Math.floor((now - receivedAt) / 1000));
  return Math.max(0, Math.floor(waitS)) + elapsed;
}

/** "0:45", "12:03", "1:02:03": a wait on a label pill or a counter. */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** The point a person stands on: the bottom centre of the box (docs/KOZ.md §4). */
export function footPoint(box: Box): [number, number] {
  return [box[0] + box[2] / 2, box[1] + box[3]];
}

/**
 * How a wait reads against the rule: calm, getting long (half the queue rule), or past it. The
 * colours of the label pills and the big counter follow this.
 */
export function waitLevel(seconds: number | null | undefined, threshold: number): "calm" | "long" | "over" {
  if (seconds === null || seconds === undefined || !threshold) return "calm";
  if (seconds >= threshold) return "over";
  if (seconds >= threshold / 2) return "long";
  return "calm";
}
