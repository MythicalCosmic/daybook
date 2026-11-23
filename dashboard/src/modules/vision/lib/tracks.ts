/**
 * The live overlay between two frames (docs/KOZ.md §5.6, §6.3). Frames come about twice a second;
 * the boxes glide from where they were to where the new frame puts them instead of jumping: people
 * are matched by `track`, a box that is in both frames moves, a new one fades in where it appears
 * and one that left fades out where it was last seen. Waits keep ticking every second between
 * frames, counted from when the frame arrived (the browser's clock, never the server's), and read
 * as of the page's one-second clock, so every wait on the page turns over at the same moment.
 */
import { easeOutCubic } from "@/lib/useTween";

import type { FramePerson, Live } from "../types";

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
 * A wait that keeps counting between reports, as of `now` (the page clock's last tick): the
 * seconds the report said plus the time since it arrived, in whole seconds. A report that came in
 * just after the tick reads what the wait was at the tick, so two reports of one wait (a frame and
 * the live numbers) read the same. Null stays null (not in a queue zone).
 */
export function tickingWait(waitS: number | null | undefined, receivedAt: number, now: number): number | null {
  if (waitS === null || waitS === undefined || !Number.isFinite(waitS)) return null;
  // In whole milliseconds first, so 140.9 s + 0.1 s is 141 and never 140.99999.
  return Math.max(0, Math.floor(Math.round(waitS * 1000 + now - receivedAt) / 1000));
}

/** When a wait began (`Date.now()` time), and when it was last reported. */
export interface WaitStart {
  start: number;
  seen: number;
}
export type WaitStarts = ReadonlyMap<number, WaitStart>;

/** Two reports of one wait further apart than this are a new wait (the agent started over). */
const SAME_WAIT_MS = 1_500;
/** How long a wait is kept for someone the reports stopped showing (a box fading out). */
const KEEP_WAIT_MS = 5_000;

/**
 * When each wait began, by track (or camera), kept steady from one report to the next. A report
 * gives whole seconds and arrives after the network, so counting back from its arrival puts the
 * start up to a second late: the earliest estimate wins, and one more than 1.5 s away is a new
 * wait. Without it, a wait read from alternate reports would step back a second now and then. A
 * reading without a wait ends that wait; one missing from the report is kept for 5 s.
 */
export function steadyStarts(previous: WaitStarts, readings: readonly { key: number; wait: number | null | undefined }[], at: number): Map<number, WaitStart> {
  const next = new Map<number, WaitStart>();
  for (const [key, entry] of previous) if (at - entry.seen < KEEP_WAIT_MS) next.set(key, entry);
  for (const { key, wait } of readings) {
    if (wait === null || wait === undefined || !Number.isFinite(wait)) {
      next.delete(key);
      continue;
    }
    const estimate = Math.round(at - Math.max(0, wait) * 1000);
    const before = next.get(key);
    const start = before && Math.abs(before.start - estimate) <= SAME_WAIT_MS ? Math.min(before.start, estimate) : estimate;
    next.set(key, { start, seen: at });
  }
  return next;
}

/** The whole seconds waited by `now` (the page clock's last tick); null without a start. */
export function waitedBy(start: number | null | undefined, now: number): number | null {
  if (start === null || start === undefined || !Number.isFinite(start)) return null;
  return Math.max(0, Math.floor((now - start) / 1000));
}

/**
 * The live report with each camera's longest wait read the freshest way: from its frames while
 * they arrive (`frames`, by camera: when the longest wait began, null when nobody waits), else
 * from the report itself, steady from one report to the next. Each `wait_s` is then the wait as
 * of `at`, which may be below zero for a wait that began after the report came, so
 * `tickingWait(wait_s, at, now)` reads the same second as the pill of the one waiting.
 */
export function freshReport(data: Live, at: number, previous: WaitStarts, frames: ReadonlyMap<number, number | null>): { report: Live; starts: Map<number, WaitStart> } {
  const starts = steadyStarts(
    previous,
    data.cameras.map((camera) => ({ key: camera.id, wait: camera.wait_s })),
    at,
  );
  const cameras = data.cameras.map((camera) => {
    const seen = frames.get(camera.id);
    if (typeof seen === "number") return { ...camera, wait_s: (at - seen) / 1000 };
    // The pictures show nobody waiting: the report's wait is from before they left.
    if (seen === null) return camera.wait_s === null ? camera : { ...camera, wait_s: 0 };
    const start = camera.wait_s === null ? undefined : starts.get(camera.id)?.start;
    return start === undefined ? camera : { ...camera, wait_s: (at - start) / 1000 };
  });
  return { report: { ...data, cameras }, starts };
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
