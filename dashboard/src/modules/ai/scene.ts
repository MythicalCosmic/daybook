/**
 * An agent's room on its own page (AgentScene.vue): the chibi at its desk — typing while the agent
 * works, looking at its screen and pulling faces while it waits, asleep on the desk when it's off —
 * and what the screen shows. The room is drawn in units (960 × 180, the middle 320 × 180 is the
 * stage) and scaled to cover its box, so the chibi (HTML) is placed with the same numbers.
 */
import { BUDDY_DURATION, type BuddyAction, type BuddyMood, type BuddyVariant } from "./lib";

export type SceneState = "working" | "idle" | "asleep";

/** In a chair it stays seated: no hops, dances or walks, only what reads well at a desk. */
export const SCENE_ACTIONS: Record<Exclude<SceneState, "asleep">, readonly BuddyAction[]> = {
  working: ["type", "type", "type", "type", "type", "think", "sparkle", "blink", "sweat"],
  idle: ["blink", "blink", "look", "think", "wink", "star", "hearts", "sparkle", "wave", "type", "shy", "love"],
};

/** Each chibi's own move, now and then at its desk: the voice chibi listens, the deadline one
 * rings its clock, the morning one cheers, the photo one winks (a snap), HR thinks it over. */
export const SIGNATURE_MOVE: Record<BuddyVariant, BuddyAction> = {
  claude: "sparkle",
  voice: "listen",
  morning: "cheer",
  deadline: "ring",
  photo: "wink",
  hr: "think",
};

/** How often it changes what it does. */
export const SCENE_BEAT_MS: Record<Exclude<SceneState, "asleep">, number> = { working: 2600, idle: 4200 };

/** The next thing it does: never the same face twice in a row, but typing may go on and on; about
 * one beat in seven its own `signature` move, when it has one. */
export function pickSceneAction(state: SceneState, previous: BuddyAction | null, random: () => number = Math.random, signature?: BuddyAction): BuddyAction {
  if (state === "asleep") return "idle";
  if (signature && signature !== previous && random() < 1 / 7) return signature;
  const pool = SCENE_ACTIONS[state];
  for (let tries = 0; tries < 6; tries += 1) {
    const next = pool[Math.min(pool.length - 1, Math.floor(random() * pool.length))]!;
    if (next !== previous || next === "type") return next;
  }
  return pool.find((action) => action !== previous) ?? pool[0]!;
}

/** How long an action shows before it settles back to watching the screen. */
export function sceneActionMs(action: BuddyAction): number {
  return action === "type" ? Number.POSITIVE_INFINITY : Math.max(BUDDY_DURATION[action] ?? 0, 600);
}

/** The chibi's own props for a state. */
export function sceneBuddy(state: SceneState): { mood: BuddyMood; asleep: boolean; gaze: "right" | undefined } {
  if (state === "asleep") return { mood: "on", asleep: true, gaze: undefined };
  return { mood: state === "working" ? "busy" : "on", asleep: false, gaze: "right" };
}

/** What its screen shows: the newest `max` lines, each on one line and cut to fit. */
export function screenLines(lines: readonly string[], max = 5, width = 30): string[] {
  return lines
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .slice(-max)
    .map((line) => (line.length > width ? `${line.slice(0, width - 1).trimEnd()}…` : line));
}

/** 20:00–06:00 by the company's clock is night in the room. */
export function isNightHour(hour: number): boolean {
  return hour >= 20 || hour < 6;
}

export const ROOM = { width: 960, height: 180, stageX: 320 } as const;

/** Where a room unit lands in a box of `width` × `height` px: scaled to cover it, centred. */
export function roomScale(width: number, height: number): { scale: number; offsetX: number; offsetY: number } {
  const scale = Math.max(width / ROOM.width, height / ROOM.height, 0);
  return { scale, offsetX: (width - ROOM.width * scale) / 2, offsetY: (height - ROOM.height * scale) / 2 };
}

/** The chibi on its chair behind the desk, in stage units (its body ends at the desk top, y 100);
 * asleep it slumps onto the desk. */
export const SEAT = { x: 119, y: 59, size: 62, slump: 5 } as const;

export function seatBox(width: number, height: number, asleep: boolean): { left: number; top: number; size: number } {
  const { scale, offsetX, offsetY } = roomScale(width, height);
  return {
    left: Math.round(offsetX + (ROOM.stageX + SEAT.x) * scale),
    top: Math.round(offsetY + (SEAT.y + (asleep ? SEAT.slump : 0)) * scale),
    size: Math.max(1, Math.round(SEAT.size * scale)),
  };
}

/** Where a stage point (room units) lands in a box of `width` × `height` px: the bubbles' anchors. */
export function stagePoint(x: number, y: number, width: number, height: number): { left: number; top: number } {
  const { scale, offsetX, offsetY } = roomScale(width, height);
  return { left: Math.round(offsetX + (ROOM.stageX + x) * scale), top: Math.round(offsetY + y * scale) };
}

/** The wall clock's hands for a time of day, in degrees clockwise from 12. */
export function clockHands(hours: number, minutes: number): { hour: number; minute: number } {
  return { hour: ((hours % 12) + minutes / 60) * 30, minute: (minutes % 60) * 6 };
}

/** What it thinks about now and then (a little picture in a thought bubble, no words). */
export type ThoughtIcon = "heart" | "star" | "coffee" | "note" | "idea";
export const THOUGHTS: Record<Exclude<SceneState, "asleep">, readonly ThoughtIcon[]> = {
  working: ["idea", "coffee", "note"],
  idle: ["heart", "star", "coffee", "note"],
};

export function pickThought(state: SceneState, previous: ThoughtIcon | null, random: () => number = Math.random): ThoughtIcon | null {
  if (state === "asleep") return null;
  const choices = THOUGHTS[state].filter((icon) => icon !== previous);
  return choices[Math.min(choices.length - 1, Math.floor(random() * choices.length))] ?? null;
}

export interface Saying {
  key: string;
  params?: Record<string, string | number>;
}

/** What it says when tapped, one after another: how it's doing, its own line, what it did today
 * and when it runs next; asleep, only that it's off. */
export function sceneSayings(state: SceneState, variant: BuddyVariant, next: string | null, doneToday: number | null): Saying[] {
  if (state === "asleep") return [{ key: "ai.agent.scene.say.asleep" }];
  const sayings: Saying[] = [{ key: state === "working" ? "ai.agent.scene.say.busy" : "ai.agent.scene.say.hi" }, { key: `ai.agent.scene.say.${variant}` }];
  if (doneToday !== null) sayings.push(doneToday > 0 ? { key: "ai.agent.scene.say.today", params: { count: doneToday } } : { key: "ai.agent.scene.say.nothingYet" });
  if (next) sayings.push({ key: "ai.agent.scene.say.next", params: { time: next } });
  return sayings;
}
